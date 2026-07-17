from __future__ import annotations

import base64
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from .audit import AuditLog
from .client import DataEaseClient
from .config import Settings
from .errors import DataEaseError
from .redact import redact_configuration
from .safety import PlanStore


def _envelope(operation: str, result: Any, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ok": True,
        "operation": operation,
        "result": result,
        "warnings": extra.pop("warnings", []),
        **extra,
    }


def _load_spec(path: str) -> dict[str, Any]:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8-sig")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataEaseError(f"JSON 配置无效: {exc}", code="invalid_spec", stage="input") from exc
    if not isinstance(value, dict):
        raise DataEaseError("配置根节点必须是 JSON 对象", code="invalid_spec", stage="input")
    return value


def _digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _plan_context(client: DataEaseClient) -> dict[str, Any]:
    version = None
    try:
        version = client.data("GET", "/license/version")
    except DataEaseError:
        pass
    return {
        "base_url": client.settings.base_url,
        "api_prefix": client.settings.api_prefix,
        "org_id": client.settings.org_id or None,
        "version": version,
    }


def _snapshot(settings: Settings, resource: str, resource_id: str, data: Any) -> str:
    directory = settings.output_dir / "snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(char for char in str(resource_id) if char.isalnum() or char in {"-", "_"})
    path = directory / f"{resource}-{safe_id}-{int(time.time())}.json"
    path.write_text(json.dumps(redact_configuration(data), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def _validate_required(spec: dict[str, Any], required: tuple[str, ...]) -> None:
    missing = [key for key in required if key not in spec or spec.get(key) in (None, "")]
    if missing:
        raise DataEaseError(
            f"配置缺少必填字段: {', '.join(missing)}",
            code="invalid_spec",
            stage="input",
        )


def _load_digest_bound_spec(args: Any, plan: dict[str, Any]) -> dict[str, Any]:
    spec = _load_spec(args.spec)
    if _digest(spec) != plan.get("spec", {}).get("payload_sha256"):
        raise DataEaseError("apply 配置与 dry-run 内容不一致", code="spec_changed", stage="safety")
    return spec


def _datasource_public(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    fields = (
        "id",
        "pid",
        "name",
        "nodeType",
        "type",
        "typeAlias",
        "status",
        "taskStatus",
        "enableDataFill",
        "updateTime",
    )
    return {key: value.get(key) for key in fields if key in value}


def _datasource_request(spec: dict[str, Any]) -> dict[str, Any]:
    request = dict(spec)
    configuration = request.get("configuration")
    if isinstance(configuration, (dict, list)):
        raw = json.dumps(configuration, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request["configuration"] = base64.b64encode(raw).decode("ascii")
    return request


def _dataset_public(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    fields = (
        "id",
        "pid",
        "name",
        "nodeType",
        "type",
        "mode",
        "level",
        "syncStatus",
        "lastUpdateTime",
        "createTime",
    )
    return {key: value.get(key) for key in fields if key in value}


def _datasource_detail(client: DataEaseClient, resource_id: str) -> dict[str, Any]:
    try:
        value = client.data("GET", f"/datasource/hidePw/{resource_id}")
    except DataEaseError:
        value = next(
            (item for item in _tree(client, "datasource") if str(item.get("id")) == str(resource_id)),
            None,
        )
    public = _datasource_public(value)
    if not public or str(public.get("id")) != str(resource_id):
        raise DataEaseError("找不到目标数据源", code="resource_not_found", stage="datasource")
    return public


def _dataset_detail(client: DataEaseClient, resource_id: str, *, full: bool = False) -> dict[str, Any]:
    endpoint = "details" if full else "get"
    value = client.data("POST", f"/datasetTree/{endpoint}/{resource_id}", {})
    if not isinstance(value, dict) or str(value.get("id")) != str(resource_id):
        raise DataEaseError("找不到目标数据集", code="resource_not_found", stage="dataset")
    return value


def _tree(client: DataEaseClient, domain: str) -> list[dict[str, Any]]:
    endpoint = "/datasource/tree" if domain == "datasource" else "/datasetTree/tree"
    value = client.data("POST", endpoint, {"busiFlag": domain})
    result: list[dict[str, Any]] = []

    def visit(nodes: list[dict[str, Any]], parent_id: str) -> None:
        for item in nodes:
            normalized = dict(item)
            normalized.pop("children", None)
            normalized["pid"] = item.get("pid") if item.get("pid") is not None else parent_id
            normalized["nodeType"] = item.get("nodeType") or item.get("type")
            result.append(normalized)
            children = item.get("children")
            if isinstance(children, list):
                visit(children, str(item.get("id")))

    visit(value if isinstance(value, list) else [], "0")
    return result


def datasource_tables(client: DataEaseClient, datasource_id: str) -> list[dict[str, Any]]:
    value = client.data("POST", "/datasource/getTables", {"datasourceId": str(datasource_id)})
    if not isinstance(value, list):
        raise DataEaseError("数据源表查询接口未返回数组", code="invalid_response", stage="datasource")
    return [item for item in value if isinstance(item, dict)]


def datasource_table_fields(
    client: DataEaseClient,
    datasource_id: str,
    table_name: str,
) -> dict[str, Any]:
    table = next(
        (
            item
            for item in datasource_tables(client, datasource_id)
            if str(item.get("tableName")) == str(table_name)
        ),
        None,
    )
    if table is None:
        raise DataEaseError("数据源中找不到目标表", code="resource_not_found", stage="datasource")
    request = dict(table)
    request["name"] = request.get("name") or str(table_name)
    request["type"] = request.get("type") or "db"
    if request.get("isCross") is None:
        request["isCross"] = False
    if not request.get("info"):
        request["info"] = json.dumps({"table": str(table_name)}, ensure_ascii=False, separators=(",", ":"))
    value = client.data("POST", "/datasetData/tableField", request)
    if not isinstance(value, list):
        raise DataEaseError("数据表字段查询接口未返回数组", code="invalid_response", stage="dataset")
    return {"table": request, "fields": [item for item in value if isinstance(item, dict)]}


def _extract_id(value: Any) -> str:
    resource_id = value.get("id") if isinstance(value, dict) else value
    if resource_id in (None, ""):
        raise DataEaseError("创建接口没有返回资源 ID", code="invalid_response", stage="verification")
    return str(resource_id)


def _create_from_spec(
    args: Any,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
    *,
    domain: str,
) -> dict[str, Any]:
    operation = f"{domain}.create"
    required = ("name", "pid", "type", "configuration") if domain == "datasource" else ("name", "pid", "nodeType")
    endpoint = "/datasource/save" if domain == "datasource" else "/datasetTree/create"
    if not args.apply:
        spec = _load_spec(args.spec)
        _validate_required(spec, required)
        if domain == "dataset" and spec.get("nodeType") != "dataset":
            raise DataEaseError("dataset create 的 nodeType 必须为 dataset", code="invalid_spec", stage="input")
        plan = plans.create(
            operation,
            target={"type": domain, "name": str(spec["name"]).strip(), "pid": spec.get("pid", "0")},
            changes=[{"action": "create", "resource": domain}],
            risk="L1",
            spec={"payload_sha256": _digest(spec)},
            rollback={"strategy": "delete-created-resource", "requires_confirmation": True},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])

    if not args.plan_id:
        raise DataEaseError("执行创建需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError(f"plan-id 不属于 {operation}", code="invalid_plan", stage="safety")
    spec = _load_digest_bound_spec(args, plan)
    request = _datasource_request(spec) if domain == "datasource" else spec
    response = client.data("POST", endpoint, request)
    resource_id = _extract_id(response)
    after = _datasource_detail(client, resource_id) if domain == "datasource" else _dataset_public(
        _dataset_detail(client, resource_id)
    )
    if str(after.get("name")) != str(spec.get("name")):
        raise DataEaseError("创建后名称回读不一致", code="verification_failed", stage="verification")
    audit_id = audit.write(
        operation,
        status="success",
        risk="L1",
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=after,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, after, mode="apply", adapter="official-api", audit_id=audit_id)


def _folder_create(
    args: Any,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
    *,
    domain: str,
) -> dict[str, Any]:
    operation = f"{domain}.folder-create"
    endpoint = "/datasource/createFolder" if domain == "datasource" else "/datasetTree/create"
    payload = {"name": args.name.strip(), "pid": args.pid or "0", "nodeType": "folder"}
    if domain == "datasource":
        payload["action"] = "create"
    if not payload["name"]:
        raise DataEaseError("需要非空 --name", code="invalid_input", stage="input")
    if not args.apply:
        plan = plans.create(
            operation,
            target={"type": f"{domain}-folder", "name": payload["name"], "pid": payload["pid"]},
            changes=[{"action": "create-folder", "resource": domain}],
            risk="L1",
            spec={"payload_sha256": _digest(payload)},
            rollback={"strategy": "delete-created-folder", "requires_confirmation": True},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])
    if not args.plan_id:
        raise DataEaseError("执行创建需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation or _digest(payload) != plan.get("spec", {}).get("payload_sha256"):
        raise DataEaseError("创建参数与 dry-run 不一致", code="spec_changed", stage="safety")
    response = client.data("POST", endpoint, payload)
    resource_id = _extract_id(response)
    after = _datasource_detail(client, resource_id) if domain == "datasource" else _dataset_public(
        _dataset_detail(client, resource_id)
    )
    if after.get("name") != payload["name"] or after.get("nodeType") != "folder":
        raise DataEaseError("目录创建后回读不一致", code="verification_failed", stage="verification")
    audit_id = audit.write(operation, status="success", risk="L1", target=plan.get("target"), changes=plan.get("changes"), result=after)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, after, mode="apply", adapter="official-api", audit_id=audit_id)


def _rename(
    args: Any,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
    *,
    domain: str,
) -> dict[str, Any]:
    operation = f"{domain}.rename"
    if not args.id or not args.current_name or not args.name:
        raise DataEaseError("需要 --id、--current-name 与 --name", code="invalid_input", stage="input")
    detail = _datasource_detail(client, args.id) if domain == "datasource" else _dataset_public(
        _dataset_detail(client, args.id)
    )
    if str(detail.get("name")) != str(args.current_name):
        raise DataEaseError("--current-name 与目标资源不一致", code="target_mismatch", stage="safety")
    payload = {"id": str(args.id), "name": args.name.strip(), "nodeType": detail.get("nodeType")}
    if domain == "datasource":
        payload["action"] = "rename"
    if not args.apply:
        plan = plans.create(
            operation,
            target={"id": str(args.id), "type": domain, "name": args.current_name},
            changes=[{"action": "rename", "from": args.current_name, "to": payload["name"]}],
            risk="L2",
            spec={"payload": payload, "precondition_sha256": _digest(detail)},
            rollback={"strategy": "rename", "name": args.current_name},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])
    if not args.plan_id:
        raise DataEaseError("执行重命名需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    stored = plan.get("spec", {})
    if plan.get("operation") != operation or stored.get("payload") != payload:
        raise DataEaseError("重命名参数与 dry-run 不一致", code="spec_changed", stage="safety")
    if _digest(detail) != stored.get("precondition_sha256"):
        raise DataEaseError("目标资源已变化，请重新 dry-run", code="target_changed", stage="safety")
    endpoint = "/datasource/reName" if domain == "datasource" else "/datasetTree/rename"
    client.data("POST", endpoint, payload)
    after = _datasource_detail(client, args.id) if domain == "datasource" else _dataset_public(
        _dataset_detail(client, args.id)
    )
    if str(after.get("name")) != payload["name"]:
        raise DataEaseError("重命名后回读不一致", code="verification_failed", stage="verification")
    result = {"before": detail, "after": after}
    audit_id = audit.write(operation, status="success", risk="L2", target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id)


def _update_from_spec(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
    *,
    domain: str,
) -> dict[str, Any]:
    operation = f"{domain}.update"
    risk = "L3" if domain == "datasource" else "L2"
    if not args.apply:
        if domain == "datasource" and not args.ack_no_rollback:
            raise DataEaseError(
                "数据源连接配置无法从脱敏接口完整恢复；dry-run 需要 --ack-no-rollback",
                code="rollback_ack_required",
                stage="safety",
            )
        spec = _load_spec(args.spec)
        required = ("id", "name", "type", "configuration") if domain == "datasource" else ("id", "name", "nodeType")
        _validate_required(spec, required)
        resource_id = str(spec["id"])
        current_full = _datasource_detail(client, resource_id) if domain == "datasource" else _dataset_detail(
            client, resource_id, full=True
        )
        current_public = current_full if domain == "datasource" else _dataset_public(current_full)
        snapshot = _snapshot(settings, domain, resource_id, current_full)
        plan = plans.create(
            operation,
            target={"id": resource_id, "type": domain, "name": current_public.get("name")},
            changes=[{"action": "update", "resource": domain}],
            risk=risk,
            spec={
                "id": resource_id,
                "payload_sha256": _digest(spec),
                "precondition_sha256": _digest(current_full),
                "snapshot": snapshot,
            },
            rollback=(
                {"available": False, "reason": "DataEase 脱敏接口不返回旧连接密钥", "snapshot": snapshot}
                if domain == "datasource"
                else {"strategy": "manual-restore-snapshot", "snapshot": snapshot}
            ),
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"], artifacts=[snapshot])
    if not args.plan_id:
        raise DataEaseError("执行更新需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError(f"plan-id 不属于 {operation}", code="invalid_plan", stage="safety")
    spec = _load_digest_bound_spec(args, plan)
    stored = plan["spec"]
    current_full = _datasource_detail(client, stored["id"]) if domain == "datasource" else _dataset_detail(
        client, stored["id"], full=True
    )
    if _digest(current_full) != stored.get("precondition_sha256"):
        raise DataEaseError("目标资源已变化，请重新 dry-run", code="target_changed", stage="safety")
    before = current_full if domain == "datasource" else _dataset_public(current_full)
    endpoint = "/datasource/update" if domain == "datasource" else "/datasetTree/save"
    request = _datasource_request(spec) if domain == "datasource" else spec
    client.data("POST", endpoint, request)
    after = _datasource_detail(client, stored["id"]) if domain == "datasource" else _dataset_public(
        _dataset_detail(client, stored["id"])
    )
    if str(after.get("name")) != str(spec.get("name")):
        raise DataEaseError("更新后名称回读不一致", code="verification_failed", stage="verification")
    result = {"before": before, "after": after}
    audit_id = audit.write(operation, status="success", risk=risk, target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", artifacts=[stored["snapshot"]], audit_id=audit_id)


def _delete(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
    *,
    domain: str,
) -> dict[str, Any]:
    operation = f"{domain}.delete"
    if not args.apply:
        if not args.ack_no_rollback:
            raise DataEaseError(
                f"{domain} 删除没有已验证的自动恢复流程；dry-run 需要 --ack-no-rollback",
                code="rollback_ack_required",
                stage="safety",
            )
        if not args.id or not args.name:
            raise DataEaseError("需要 --id 与 --name", code="invalid_input", stage="input")
        current_full = _datasource_detail(client, args.id) if domain == "datasource" else _dataset_detail(
            client, args.id, full=True
        )
        current_public = current_full if domain == "datasource" else _dataset_public(current_full)
        if str(current_public.get("name")) != str(args.name):
            raise DataEaseError("--name 与目标资源不一致", code="target_mismatch", stage="safety")
        nodes = _tree(client, domain)
        if current_public.get("nodeType") == "folder" and any(str(item.get("pid")) == str(args.id) for item in nodes):
            raise DataEaseError("目录非空，拒绝删除", code="resource_not_empty", stage="safety")
        referenced = False
        if current_public.get("nodeType") != "folder":
            endpoint = f"/datasource/perDelete/{args.id}" if domain == "datasource" else f"/datasetTree/perDelete/{args.id}"
            referenced = client.data("POST", endpoint, {}) is True
        snapshot = _snapshot(settings, domain, args.id, current_full)
        changes = [{"action": "delete", "resource": domain, "referenced_by_downstream": referenced}]
        plan = plans.create(
            operation,
            target={"id": str(args.id), "type": domain, "name": args.name},
            changes=changes,
            risk="L3",
            spec={"id": str(args.id), "precondition_sha256": _digest(current_full), "snapshot": snapshot},
            rollback={"available": False, "reason": "未验证自动反删除接口", "snapshot": snapshot},
            context=_plan_context(client),
        )
        warnings = ["目标仍被下游资源引用；执行删除会破坏依赖关系"] if referenced else []
        return _envelope(operation, plan, mode="dry-run", changes=changes, artifacts=[snapshot], warnings=warnings)
    if not args.plan_id:
        raise DataEaseError("执行删除需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError(f"plan-id 不属于 {operation}", code="invalid_plan", stage="safety")
    stored = plan["spec"]
    current_full = _datasource_detail(client, stored["id"]) if domain == "datasource" else _dataset_detail(
        client, stored["id"], full=True
    )
    if _digest(current_full) != stored.get("precondition_sha256"):
        raise DataEaseError("目标资源已变化，请重新 dry-run", code="target_changed", stage="safety")
    if any(str(item.get("pid")) == str(stored["id"]) for item in _tree(client, domain)):
        raise DataEaseError("目录非空，拒绝删除", code="resource_not_empty", stage="safety")
    endpoint = f"/datasource/delete/{stored['id']}" if domain == "datasource" else f"/datasetTree/delete/{stored['id']}"
    method = "GET" if domain == "datasource" else "POST"
    response = client.data(method, endpoint, {} if method == "POST" else None)
    if any(str(item.get("id")) == str(stored["id"]) for item in _tree(client, domain)):
        raise DataEaseError("删除后资源仍然可见", code="verification_failed", stage="verification")
    result = {"id": stored["id"], "name": plan.get("target", {}).get("name"), "deleted": True, "response": response}
    audit_id = audit.write(operation, status="success", risk="L3", target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", artifacts=[stored["snapshot"]], audit_id=audit_id)


def _datasource_sync(
    args: Any,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "datasource.sync"
    if not args.id or not args.name:
        raise DataEaseError("需要 --id 与 --name", code="invalid_input", stage="input")
    current = _datasource_detail(client, args.id)
    if str(current.get("name")) != str(args.name):
        raise DataEaseError("--name 与目标数据源不一致", code="target_mismatch", stage="safety")
    source_type = str(current.get("type") or "")
    if "API" not in source_type.upper() and source_type != "ExcelRemote":
        raise DataEaseError(
            "官方 syncApiDs 仅适用于 API 或 ExcelRemote 数据源",
            code="unsupported_datasource_sync",
            stage="datasource",
        )
    if not args.apply:
        plan = plans.create(
            operation,
            target={"id": str(args.id), "type": "datasource", "name": args.name},
            changes=[{"action": "synchronize", "scope": "entire-datasource"}],
            risk="L2",
            spec={"id": str(args.id), "precondition_sha256": _digest(current)},
            rollback={"available": False, "reason": "同步会刷新目标数据，DataEase 不提供通用撤销接口"},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])
    if not args.plan_id:
        raise DataEaseError("执行同步需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation or str(plan.get("spec", {}).get("id")) != str(args.id):
        raise DataEaseError("同步参数与 dry-run 不一致", code="spec_changed", stage="safety")
    if _digest(current) != plan["spec"].get("precondition_sha256"):
        raise DataEaseError("目标数据源已变化，请重新 dry-run", code="target_changed", stage="safety")
    response = client.data("POST", "/datasource/syncApiDs", {"datasourceId": str(args.id)})
    result = {"id": str(args.id), "name": args.name, "sync_requested": True, "response": response}
    audit_id = audit.write(operation, status="success", risk="L2", target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id)


def handle_data_mutation(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    domain = args.domain
    if args.action == "folder-create":
        return _folder_create(args, client, plans, audit, domain=domain)
    if args.action == "rename":
        return _rename(args, client, plans, audit, domain=domain)
    if args.action == "create":
        return _create_from_spec(args, client, plans, audit, domain=domain)
    if args.action == "update":
        return _update_from_spec(args, settings, client, plans, audit, domain=domain)
    if args.action == "delete":
        return _delete(args, settings, client, plans, audit, domain=domain)
    if domain == "datasource" and args.action == "validate-spec":
        spec = _load_spec(args.spec)
        _validate_required(spec, ("name", "type", "configuration"))
        return _envelope(
            "datasource.validate-spec",
            _datasource_public(client.data("POST", "/datasource/validate", _datasource_request(spec))),
        )
    if domain == "datasource" and args.action == "sync":
        return _datasource_sync(args, client, plans, audit)
    if domain == "datasource" and args.action == "sync-logs":
        result = client.data("POST", f"/datasource/listSyncRecord/{args.id}/{args.page}/{args.size}", {})
        return _envelope("datasource.sync-logs", result)
    raise DataEaseError(
        f"未实现数据操作: {domain}.{args.action}",
        code="unsupported_operation",
        stage="routing",
    )
