from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .admin_ops import handle_admin_mutation
from .audit import AuditLog
from .automation_ops import handle_automation_operation
from .capabilities import CapabilityService
from .client import DataEaseClient
from .config import Settings
from .data_ops import handle_data_mutation
from .datasets import DatasetService
from .errors import DataEaseError
from .intelligence import build_visual_plan
from .platform import PlatformService
from .redact import redact_configuration
from .safety import PlanStore
from .settings_ops import handle_settings_operation
from .trees import flatten_tree


def _json(data: Any, code: int = 0) -> int:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return code


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
    if path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path).read_text(encoding="utf-8-sig")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataEaseError(f"JSON 配置无效: {exc}", code="invalid_spec", stage="input") from exc
    if not isinstance(value, dict):
        raise DataEaseError("配置根节点必须是 JSON 对象", code="invalid_spec", stage="input")
    return value


def _plan_context(client: DataEaseClient | None) -> dict[str, Any]:
    if client is None:
        return {}
    settings = client.settings
    version: Any = None
    try:
        version = client.data("GET", "/license/version")
    except DataEaseError:
        pass
    return {
        "base_url": settings.base_url,
        "api_prefix": settings.api_prefix,
        "org_id": settings.org_id or None,
        "version": version,
    }


def _visual_resource_detail(client: DataEaseClient, busi_type: str, resource_id: str) -> dict[str, Any]:
    detail = client.data(
        "POST",
        "/dataVisualization/findById",
        {"id": str(resource_id), "busiFlag": busi_type, "source": "main", "taskId": None},
    )
    if not isinstance(detail, dict):
        raise DataEaseError(
            f"找不到 {busi_type} 资源: {resource_id}",
            code="resource_not_found",
            stage="visualization",
        )
    return detail


def _visual_target_state(client: DataEaseClient, busi_type: str, resource_id: str) -> dict[str, Any]:
    detail = _visual_resource_detail(client, busi_type, resource_id)
    return {
        key: detail.get(key)
        for key in ("id", "name", "type", "status", "pid", "updateTime", "checkVersion")
        if key in detail
    }


def _active_view_ids(detail: dict[str, Any]) -> list[str]:
    view_info = detail.get("canvasViewInfo") or {}
    if isinstance(view_info, dict) and view_info:
        return [str(item) for item in view_info.keys()]
    raw_components = detail.get("componentData") or "[]"
    try:
        components = json.loads(raw_components) if isinstance(raw_components, str) else raw_components
    except json.JSONDecodeError:
        components = []
    if not isinstance(components, list):
        return []
    return [
        str(item["id"])
        for item in components
        if isinstance(item, dict) and item.get("component") == "UserView" and item.get("id") is not None
    ]


def _settings(args: argparse.Namespace) -> Settings:
    settings = Settings.load(args.env_file)
    overrides: dict[str, Any] = {}
    if args.base_url:
        overrides["base_url"] = args.base_url.rstrip("/")
    if args.org_id:
        overrides["org_id"] = str(args.org_id)
    if args.insecure:
        overrides["verify_ssl"] = False
        overrides["ca_bundle"] = ""
    return settings.with_overrides(**overrides) if overrides else settings


def _capture(settings: Settings, resource_id: str, busi_type: str, pixel: str) -> dict[str, Any]:
    script = settings.skill_root / "scripts" / "capture_dashboard.py"
    cmd = [
        sys.executable,
        str(script),
        "capture",
        "--resource-id",
        resource_id,
        "--busi-type",
        busi_type,
        "--output-dir",
        str(settings.output_dir),
        "--base-url",
        settings.base_url,
        "--pixel",
        pixel,
    ]
    if settings.org_id:
        cmd.extend(["--org-id", settings.org_id])
    child_env = os.environ.copy()
    configured_env = {
        "DATAEASE_BASE_URL": settings.base_url,
        "DATAEASE_API_PREFIX": settings.api_prefix,
        "DATAEASE_ACCESS_KEY": settings.access_key,
        "DATAEASE_SECRET_KEY": settings.secret_key,
        "DATAEASE_USERNAME": settings.username,
        "DATAEASE_PASSWORD": settings.password,
        "DATAEASE_LOGIN_ORIGIN": str(settings.login_origin),
        "DATAEASE_REQUEST_MODE": settings.request_mode,
        "DATAEASE_PROXY_MODE": settings.proxy_mode,
        "DATAEASE_NO_PROXY": settings.no_proxy,
        "NO_PROXY": settings.no_proxy,
        "no_proxy": settings.no_proxy,
        "DATAEASE_ORG_ID": settings.org_id,
        "DATAEASE_X_DE_TOKEN": settings.x_de_token,
        "DATAEASE_TIMEOUT": str(settings.timeout),
        "DATAEASE_VERIFY_SSL": str(settings.verify_ssl).lower(),
        "DATAEASE_CA_BUNDLE": settings.ca_bundle,
        "DATAEASE_OUTPUT_DIR": str(settings.output_dir),
    }
    child_env.update({key: value for key, value in configured_env.items() if value})
    process = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(180, int(settings.timeout)),
        env=child_env,
    )
    if process.returncode != 0:
        raise DataEaseError(
            process.stderr.strip() or process.stdout.strip() or "截图失败",
            code="capture_failed",
            stage="capture",
        )
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise DataEaseError("截图脚本返回了非 JSON 内容", code="invalid_capture_response", stage="capture") from exc


def _visual_create(
    args: argparse.Namespace,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    if not args.apply:
        spec = _load_spec(args.spec)
        title = str(spec.get("title") or "智能分析")
        busi_type = str(spec.get("kind") or "dashboard")
        if busi_type not in {"dashboard", "dataV"}:
            raise DataEaseError("kind 必须是 dashboard 或 dataV", code="invalid_spec", stage="input")
        charts = spec.get("charts")
        if not isinstance(charts, list) or not charts:
            raise DataEaseError("配置中必须包含非空 charts", code="invalid_spec", stage="input")
        plan = plans.create(
            "visual.create",
            target={"name": title, "type": busi_type},
            changes=[{"action": "create", "resource": busi_type, "charts": len(charts)}],
            risk="L1",
            spec=spec,
            rollback={"strategy": "delete-created-resource", "requires_confirmation": True},
            context=_plan_context(client),
        )
        return _envelope("visual.create", plan, mode="dry-run", changes=plan["changes"])

    if not args.plan_id:
        raise DataEaseError("执行创建需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != "visual.create":
        raise DataEaseError("plan-id 不属于 visual.create", code="invalid_plan", stage="safety")
    spec = plan["spec"]
    from .visual_engine import MultiDataEaseChartEngine

    engine = MultiDataEaseChartEngine(
        settings.base_url,
        settings.access_key,
        settings.secret_key,
        settings=settings,
    )
    dashboard_id, url = engine.deploy_multi(
        str(spec.get("title") or "智能分析"),
        spec["charts"],
        busi_type=str(spec.get("kind") or "dashboard"),
        theme=str(spec.get("theme") or "business-light"),
        publish=False,
        append_timestamp=False,
    )
    detail = _visual_resource_detail(client, str(spec.get("kind") or "dashboard"), str(dashboard_id))
    if detail.get("status") not in {0, False, None}:
        raise DataEaseError(
            "资源创建后意外处于发布状态",
            code="unexpected_publish_state",
            stage="verification",
            details={"id": str(dashboard_id), "status": detail.get("status")},
        )
    capture = None
    if not args.no_capture:
        capture = _capture(settings, str(dashboard_id), str(spec.get("kind") or "dashboard"), args.pixel)
    result = {
        "id": str(dashboard_id),
        "name": spec.get("title"),
        "type": spec.get("kind") or "dashboard",
        "url": url,
        "status": detail.get("status"),
        "capture": capture,
    }
    audit_id = audit.write(
        "visual.create",
        status="success",
        risk="L1",
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=result,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(
        "visual.create",
        result,
        mode="apply",
        adapter="official-api",
        changes=plan.get("changes", []),
        artifacts=[capture.get("saved_file")] if isinstance(capture, dict) and capture.get("saved_file") else [],
        audit_id=audit_id,
    )


def _visual_publish(
    args: argparse.Namespace,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    if not args.apply:
        if not args.resource_id or not args.name:
            raise DataEaseError(
                "dry-run 需要 --resource-id 与 --name",
                code="invalid_input",
                stage="input",
            )
        state = _visual_target_state(client, args.busi_type, args.resource_id)
        if str(state.get("name")) != args.name:
            raise DataEaseError(
                "--name 与目标资源的当前名称不一致",
                code="target_mismatch",
                stage="safety",
                details={"id": args.resource_id, "current_name": state.get("name")},
            )
        spec = {
            "id": args.resource_id,
            "name": args.name,
            "type": args.busi_type,
            "status": args.status,
            "precondition": state,
        }
        plan = plans.create(
            "visual.publish",
            target={"id": args.resource_id, "name": args.name, "type": args.busi_type},
            changes=[{"action": "publish" if args.status == 1 else "unpublish", "status": args.status}],
            risk="L2",
            spec=spec,
            rollback={"status": 0 if args.status == 1 else 1},
            context=_plan_context(client),
        )
        return _envelope("visual.publish", plan, mode="dry-run", changes=plan["changes"])
    if not args.plan_id:
        raise DataEaseError("执行发布变更需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != "visual.publish":
        raise DataEaseError("plan-id 不属于 visual.publish", code="invalid_plan", stage="safety")
    spec = plan["spec"]
    detail = _visual_resource_detail(client, spec["type"], spec["id"])
    current_state = _visual_target_state(client, spec["type"], spec["id"])
    if current_state != spec.get("precondition"):
        raise DataEaseError(
            "目标资源在 dry-run 后已变化，请重新生成计划",
            code="target_changed",
            stage="safety",
            details={"planned": spec.get("precondition"), "current": current_state},
        )
    response = client.post(
        "/dataVisualization/updatePublishStatus",
        {
            "id": spec["id"],
            "name": spec["name"],
            "status": spec["status"],
            "type": spec["type"],
            "mobileLayout": False,
            "activeViewIds": _active_view_ids(detail),
        },
    )
    after = _visual_target_state(client, spec["type"], spec["id"])
    if after.get("status") != spec["status"]:
        raise DataEaseError(
            "发布状态回读不一致",
            code="verification_failed",
            stage="verification",
            details={"expected": spec["status"], "actual": after.get("status")},
        )
    audit_id = audit.write(
        "visual.publish",
        status="success",
        risk="L2",
        target=plan.get("target"),
        changes=plan.get("changes"),
        result={"response": response, "before": current_state, "after": after},
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(
        "visual.publish",
        {"response": response, "before": current_state, "after": after},
        mode="apply",
        adapter="official-api",
        audit_id=audit_id,
    )


def _filling_create(
    args: argparse.Namespace,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "filling.task-create" if args.action == "task-create" else "filling.create"
    endpoint = "/data-filling/task/save" if args.action == "task-create" else "/data-filling/save"
    resource = "data-filling-task" if args.action == "task-create" else "data-filling"
    if not args.apply:
        spec = _load_spec(args.spec)
        if not str(spec.get("name") or "").strip():
            raise DataEaseError("配置中必须包含 name", code="invalid_spec", stage="input")
        if args.action == "task-create":
            if not spec.get("formId"):
                raise DataEaseError("任务配置中必须包含 formId", code="invalid_spec", stage="input")
            target = {"name": spec["name"], "formId": str(spec["formId"])}
        else:
            node_type = str(spec.get("nodeType") or "").strip()
            if node_type not in {"folder", "form"}:
                raise DataEaseError("nodeType 必须是 folder 或 form", code="invalid_spec", stage="input")
            target = {"name": spec["name"], "nodeType": node_type, "pid": str(spec.get("pid") or "0")}
        plan = plans.create(
            operation,
            target=target,
            changes=[{"action": "create", "resource": resource}],
            risk="L1",
            spec=spec,
            rollback={"strategy": "delete-created-resource", "requires_confirmation": True},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])

    if not args.plan_id:
        raise DataEaseError("执行创建需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError(f"plan-id 不属于 {operation}", code="invalid_plan", stage="safety")
    response = client.data("POST", endpoint, plan["spec"])
    audit_id = audit.write(
        operation,
        status="success",
        risk="L1",
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=response,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(
        operation,
        response,
        mode="apply",
        adapter="official-api",
        changes=plan.get("changes", []),
        audit_id=audit_id,
    )


def _write_snapshot(settings: Settings, resource_type: str, resource_id: str, data: Any) -> str:
    directory = settings.output_dir / "snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    safe_type = "".join(char for char in resource_type if char.isalnum() or char in {"-", "_"})
    path = directory / f"{safe_type}-{resource_id}-{int(time.time())}.json"
    path.write_text(
        json.dumps(redact_configuration(data), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(path.resolve())


def _visual_delete(
    args: argparse.Namespace,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "visual.delete"
    if not args.apply:
        if not args.ack_no_rollback:
            raise DataEaseError(
                "该软删除接口没有已验证的自动恢复流程；dry-run 需要 --ack-no-rollback",
                code="rollback_ack_required",
                stage="safety",
            )
        if not args.resource_id or not args.name:
            raise DataEaseError("需要 --resource-id 与 --name", code="invalid_input", stage="input")
        detail = _visual_resource_detail(client, args.busi_type, args.resource_id)
        if detail.get("name") != args.name:
            raise DataEaseError("--name 与目标资源不一致", code="target_mismatch", stage="safety")
        snapshot = _write_snapshot(settings, args.busi_type, args.resource_id, detail)
        state = _visual_target_state(client, args.busi_type, args.resource_id)
        plan = plans.create(
            operation,
            target={"id": args.resource_id, "name": args.name, "type": args.busi_type},
            changes=[{"action": "delete", "resource": args.busi_type}],
            risk="L3",
            spec={
                "id": args.resource_id,
                "name": args.name,
                "type": args.busi_type,
                "precondition": state,
                "snapshot": snapshot,
            },
            rollback={
                "available": False,
                "reason": "DataEase V2 未提供经过验证的可视化资源反删除接口",
                "snapshot": snapshot,
            },
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"], artifacts=[snapshot])

    if not args.plan_id:
        raise DataEaseError("执行删除需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError("plan-id 不属于 visual.delete", code="invalid_plan", stage="safety")
    spec = plan["spec"]
    current = _visual_target_state(client, spec["type"], spec["id"])
    if current != spec.get("precondition"):
        raise DataEaseError("目标资源已变化，请重新生成删除计划", code="target_changed", stage="safety")
    response = client.post(f"/dataVisualization/deleteLogic/{spec['id']}/{spec['type']}")
    remaining = PlatformService(client).resources(spec["type"])
    if any(str(item.get("id")) == str(spec["id"]) for item in remaining):
        raise DataEaseError("删除后资源仍然可见", code="verification_failed", stage="verification")
    result = {"id": spec["id"], "name": spec["name"], "type": spec["type"], "deleted": True, "response": response}
    audit_id = audit.write(
        operation,
        status="success",
        risk="L3",
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=result,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(
        operation,
        result,
        mode="apply",
        adapter="official-api",
        changes=plan.get("changes", []),
        artifacts=[spec["snapshot"]],
        audit_id=audit_id,
    )


def _filling_state(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        key: detail.get(key)
        for key in ("id", "name", "pid", "nodeType", "tableName", "datasource", "updateTime")
        if key in detail
    }


def _filling_tree(client: DataEaseClient) -> list[dict[str, Any]]:
    data = client.data("POST", "/data-filling/tree", {"busiFlag": "dataFilling"})
    return flatten_tree(data if isinstance(data, list) else [])


def _content_digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _filling_table_data(
    client: DataEaseClient,
    form_id: str,
    *,
    page: int = 1,
    size: int = 20,
    row_ids: list[str] | None = None,
    without_logs: bool = True,
) -> dict[str, Any]:
    result = client.data(
        "POST",
        f"/data-filling/form/{form_id}/tableData",
        {
            "id": str(form_id),
            "currentPage": page,
            "pageSize": size,
            "withoutLogs": without_logs,
            "primaryKeyValueList": row_ids,
            "searchParams": [],
        },
    )
    if not isinstance(result, dict):
        raise DataEaseError("填报行查询返回格式无效", code="invalid_response", stage="data_filling")
    return result


def _filling_row_save(
    args: argparse.Namespace,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "filling.row-save"
    if not args.apply:
        request_spec = _load_spec(args.spec)
        form_id = str(request_spec.get("formId") or "").strip()
        row_data = request_spec.get("data")
        if not form_id or not isinstance(row_data, dict) or not row_data:
            raise DataEaseError("配置必须包含 formId 与非空 data 对象", code="invalid_spec", stage="input")
        detail = client.data("GET", f"/data-filling/get/{form_id}")
        if not isinstance(detail, dict) or detail.get("nodeType") != "form":
            raise DataEaseError("目标不是有效的数据填报表单", code="resource_not_found", stage="data_filling")
        plan = plans.create(
            operation,
            target={"id": form_id, "name": detail.get("name"), "type": "data-filling-row"},
            changes=[{"action": "insert-or-update", "resource": "data-filling-row"}],
            risk="L2",
            spec={
                "formId": form_id,
                "data_sha256": _content_digest(row_data),
                "precondition": _filling_state(detail),
            },
            rollback={"strategy": "delete-or-restore-row", "requires_row_snapshot": True},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])

    if not args.plan_id:
        raise DataEaseError("执行行写入需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError("plan-id 不属于 filling.row-save", code="invalid_plan", stage="safety")
    request_spec = _load_spec(args.spec)
    row_data = request_spec.get("data")
    form_id = str(request_spec.get("formId") or "").strip()
    spec = plan["spec"]
    if (
        form_id != str(spec.get("formId"))
        or not isinstance(row_data, dict)
        or _content_digest(row_data) != spec.get("data_sha256")
    ):
        raise DataEaseError("apply 的行数据与 dry-run 内容不一致", code="spec_changed", stage="safety")
    detail = client.data("GET", f"/data-filling/get/{form_id}")
    if not isinstance(detail, dict) or _filling_state(detail) != spec.get("precondition"):
        raise DataEaseError("目标填报表单已变化，请重新 dry-run", code="target_changed", stage="safety")
    response = client.data("POST", f"/data-filling/form/{form_id}/rowData/save", row_data)
    key = response.get("key") if isinstance(response, dict) else None
    rows = response.get("data") if isinstance(response, dict) else None
    row_id = rows[0].get(key) if key and isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
    result = {"formId": form_id, "key": key, "rowId": row_id, "affected": len(rows) if isinstance(rows, list) else 0}
    audit_id = audit.write(
        operation,
        status="success",
        risk="L2",
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=result,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id)


def _filling_row_delete(
    args: argparse.Namespace,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "filling.row-delete"
    if not args.apply:
        if not args.ack_no_rollback:
            raise DataEaseError(
                "填报行删除没有已验证的自动恢复流程；dry-run 需要 --ack-no-rollback",
                code="rollback_ack_required",
                stage="safety",
            )
        if not args.form_id or not args.row_id:
            raise DataEaseError("需要 --form-id 与 --row-id", code="invalid_input", stage="input")
        detail = client.data("GET", f"/data-filling/get/{args.form_id}")
        if not isinstance(detail, dict) or detail.get("nodeType") != "form":
            raise DataEaseError("目标不是有效的数据填报表单", code="resource_not_found", stage="data_filling")
        row = _filling_table_data(client, args.form_id, size=1, row_ids=[str(args.row_id)])
        if row.get("total") != 1 or not row.get("data"):
            raise DataEaseError("找不到目标填报行", code="resource_not_found", stage="data_filling")
        snapshot = _write_snapshot(settings, "data-filling-row", args.row_id, row)
        plan = plans.create(
            operation,
            target={"formId": str(args.form_id), "rowId": str(args.row_id), "name": detail.get("name")},
            changes=[{"action": "delete", "resource": "data-filling-row"}],
            risk="L3",
            spec={
                "formId": str(args.form_id),
                "rowId": str(args.row_id),
                "precondition": _filling_state(detail),
                "row_sha256": _content_digest(row.get("data")),
                "snapshot": snapshot,
            },
            rollback={"available": False, "reason": "未验证保留原主键的自动恢复", "snapshot": snapshot},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"], artifacts=[snapshot])

    if not args.plan_id:
        raise DataEaseError("执行行删除需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError("plan-id 不属于 filling.row-delete", code="invalid_plan", stage="safety")
    spec = plan["spec"]
    detail = client.data("GET", f"/data-filling/get/{spec['formId']}")
    if not isinstance(detail, dict) or _filling_state(detail) != spec.get("precondition"):
        raise DataEaseError("目标填报表单已变化，请重新 dry-run", code="target_changed", stage="safety")
    row = _filling_table_data(client, spec["formId"], size=1, row_ids=[str(spec["rowId"])])
    if _content_digest(row.get("data")) != spec.get("row_sha256"):
        raise DataEaseError("目标填报行已变化，请重新 dry-run", code="target_changed", stage="safety")
    response = client.data("GET", f"/data-filling/form/{spec['formId']}/delete/{spec['rowId']}")
    after = _filling_table_data(client, spec["formId"], size=1, row_ids=[str(spec["rowId"])])
    if after.get("total") != 0:
        raise DataEaseError("删除后填报行仍然存在", code="verification_failed", stage="verification")
    result = {"formId": spec["formId"], "rowId": spec["rowId"], "deleted": True, "response": response}
    audit_id = audit.write(
        operation,
        status="success",
        risk="L3",
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=result,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", artifacts=[spec["snapshot"]], audit_id=audit_id)


def _filling_truncate(
    args: argparse.Namespace,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "filling.truncate"
    if not args.apply:
        if not args.ack_no_rollback:
            raise DataEaseError(
                "清空填报表没有自动恢复流程；dry-run 需要 --ack-no-rollback",
                code="rollback_ack_required",
                stage="safety",
            )
        if not args.form_id or not args.name:
            raise DataEaseError("需要 --form-id 与 --name", code="invalid_input", stage="input")
        detail = client.data("GET", f"/data-filling/get/{args.form_id}")
        if not isinstance(detail, dict) or detail.get("nodeType") != "form" or detail.get("name") != args.name:
            raise DataEaseError("--name 与目标表单不一致", code="target_mismatch", stage="safety")
        current = _filling_table_data(client, args.form_id, size=1)
        plan = plans.create(
            operation,
            target={"id": str(args.form_id), "name": args.name, "type": "data-filling-form"},
            changes=[{"action": "truncate", "resource": "data-filling-row", "count": current.get("total", 0)}],
            risk="L3",
            spec={
                "formId": str(args.form_id),
                "name": args.name,
                "precondition": _filling_state(detail),
                "expected_total": current.get("total", 0),
            },
            rollback={"available": False, "reason": "DataEase 清空接口不可逆且不保留全量行快照"},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])

    if not args.plan_id:
        raise DataEaseError("执行清空需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError("plan-id 不属于 filling.truncate", code="invalid_plan", stage="safety")
    spec = plan["spec"]
    detail = client.data("GET", f"/data-filling/get/{spec['formId']}")
    current = _filling_table_data(client, spec["formId"], size=1)
    if (
        not isinstance(detail, dict)
        or _filling_state(detail) != spec.get("precondition")
        or current.get("total") != spec.get("expected_total")
    ):
        raise DataEaseError("表单或行数已变化，请重新 dry-run", code="target_changed", stage="safety")
    response = client.data("GET", f"/data-filling/form/{spec['formId']}/truncate")
    after = _filling_table_data(client, spec["formId"], size=1)
    if after.get("total") != 0:
        raise DataEaseError("清空后仍存在填报行", code="verification_failed", stage="verification")
    result = {"formId": spec["formId"], "name": spec["name"], "deletedRows": spec["expected_total"], "response": response}
    audit_id = audit.write(
        operation,
        status="success",
        risk="L3",
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=result,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id)


def _filling_delete(
    args: argparse.Namespace,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "filling.delete"
    if not args.apply:
        if not args.ack_no_rollback:
            raise DataEaseError(
                "数据填报删除没有已验证的自动恢复流程；dry-run 需要 --ack-no-rollback",
                code="rollback_ack_required",
                stage="safety",
            )
        if not args.id or not args.name:
            raise DataEaseError("需要 --id 与 --name", code="invalid_input", stage="input")
        detail = client.data("GET", f"/data-filling/get/{args.id}")
        if not isinstance(detail, dict) or detail.get("name") != args.name:
            raise DataEaseError("--name 与目标资源不一致", code="target_mismatch", stage="safety")
        children = [item for item in _filling_tree(client) if str(item.get("pid")) == str(args.id)]
        if children:
            raise DataEaseError("填报目录非空，拒绝删除", code="resource_not_empty", stage="safety")
        snapshot = _write_snapshot(settings, "data-filling", args.id, detail)
        plan = plans.create(
            operation,
            target={"id": args.id, "name": args.name, "type": detail.get("nodeType")},
            changes=[{"action": "delete", "resource": "data-filling"}],
            risk="L3",
            spec={"id": args.id, "name": args.name, "precondition": _filling_state(detail), "snapshot": snapshot},
            rollback={
                "available": False,
                "reason": "DataEase V2 未提供经过验证的数据填报反删除接口",
                "snapshot": snapshot,
            },
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"], artifacts=[snapshot])

    if not args.plan_id:
        raise DataEaseError("执行删除需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError("plan-id 不属于 filling.delete", code="invalid_plan", stage="safety")
    spec = plan["spec"]
    detail = client.data("GET", f"/data-filling/get/{spec['id']}")
    if not isinstance(detail, dict) or _filling_state(detail) != spec.get("precondition"):
        raise DataEaseError("目标填报资源已变化，请重新生成删除计划", code="target_changed", stage="safety")
    if any(str(item.get("pid")) == str(spec["id"]) for item in _filling_tree(client)):
        raise DataEaseError("填报目录非空，拒绝删除", code="resource_not_empty", stage="safety")
    response = client.data("GET", f"/data-filling/delete/{spec['id']}")
    if any(str(item.get("id")) == str(spec["id"]) for item in _filling_tree(client)):
        raise DataEaseError("删除后填报资源仍然可见", code="verification_failed", stage="verification")
    result = {"id": spec["id"], "name": spec["name"], "deleted": True, "response": response}
    audit_id = audit.write(
        operation,
        status="success",
        risk="L3",
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=result,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(
        operation,
        result,
        mode="apply",
        adapter="official-api",
        changes=plan.get("changes", []),
        artifacts=[spec["snapshot"]],
        audit_id=audit_id,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DataEase Skill 2.0 unified CLI")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--org-id", default="")
    parser.add_argument("--insecure", action="store_true", help="仅用于明确需要忽略 TLS 校验的测试环境")
    domains = parser.add_subparsers(dest="domain", required=True)

    system = domains.add_parser("system")
    system_actions = system.add_subparsers(dest="action", required=True)
    system_actions.add_parser("doctor")
    system_actions.add_parser("capabilities")

    inventory = domains.add_parser("inventory")
    inventory_actions = inventory.add_subparsers(dest="action", required=True)
    inventory_actions.add_parser("scan")

    dataset = domains.add_parser("dataset")
    dataset_actions = dataset.add_subparsers(dest="action", required=True)
    dataset_actions.add_parser("list")
    for action in ("fields", "profile"):
        command = dataset_actions.add_parser(action)
        command.add_argument("--dataset", required=True)
    plan = dataset_actions.add_parser("plan")
    plan.add_argument("--dataset", required=True)
    plan.add_argument("--title", required=True)
    plan.add_argument("--busi-type", choices=("dashboard", "dataV"), default="dashboard")
    for action in ("folder-create",):
        command = dataset_actions.add_parser(action)
        command.add_argument("--name", required=True)
        command.add_argument("--pid", default="0")
        command.add_argument("--apply", action="store_true")
        command.add_argument("--plan-id", default="")
        command.add_argument("--confirm-token", default="")
    dataset_rename = dataset_actions.add_parser("rename")
    dataset_rename.add_argument("--id", required=True)
    dataset_rename.add_argument("--current-name", required=True)
    dataset_rename.add_argument("--name", required=True)
    dataset_rename.add_argument("--apply", action="store_true")
    dataset_rename.add_argument("--plan-id", default="")
    dataset_rename.add_argument("--confirm-token", default="")
    for action in ("create", "update"):
        command = dataset_actions.add_parser(action)
        command.add_argument("--spec", default="-")
        command.add_argument("--ack-no-rollback", action="store_true")
        command.add_argument("--apply", action="store_true")
        command.add_argument("--plan-id", default="")
        command.add_argument("--confirm-token", default="")
    dataset_delete = dataset_actions.add_parser("delete")
    dataset_delete.add_argument("--id", required=True)
    dataset_delete.add_argument("--name", required=True)
    dataset_delete.add_argument("--ack-no-rollback", action="store_true")
    dataset_delete.add_argument("--apply", action="store_true")
    dataset_delete.add_argument("--plan-id", default="")
    dataset_delete.add_argument("--confirm-token", default="")

    datasource = domains.add_parser("datasource")
    datasource_actions = datasource.add_subparsers(dest="action", required=True)
    datasource_actions.add_parser("list")
    datasource_actions.add_parser("types")
    ds_validate = datasource_actions.add_parser("validate")
    ds_validate.add_argument("--id", required=True)
    ds_validate_spec = datasource_actions.add_parser("validate-spec")
    ds_validate_spec.add_argument("--spec", default="-")
    ds_folder_create = datasource_actions.add_parser("folder-create")
    ds_folder_create.add_argument("--name", required=True)
    ds_folder_create.add_argument("--pid", default="0")
    ds_folder_create.add_argument("--apply", action="store_true")
    ds_folder_create.add_argument("--plan-id", default="")
    ds_folder_create.add_argument("--confirm-token", default="")
    ds_rename = datasource_actions.add_parser("rename")
    ds_rename.add_argument("--id", required=True)
    ds_rename.add_argument("--current-name", required=True)
    ds_rename.add_argument("--name", required=True)
    ds_rename.add_argument("--apply", action="store_true")
    ds_rename.add_argument("--plan-id", default="")
    ds_rename.add_argument("--confirm-token", default="")
    for action in ("create", "update"):
        command = datasource_actions.add_parser(action)
        command.add_argument("--spec", default="-")
        command.add_argument("--ack-no-rollback", action="store_true")
        command.add_argument("--apply", action="store_true")
        command.add_argument("--plan-id", default="")
        command.add_argument("--confirm-token", default="")
    ds_delete = datasource_actions.add_parser("delete")
    ds_delete.add_argument("--id", required=True)
    ds_delete.add_argument("--name", required=True)
    ds_delete.add_argument("--ack-no-rollback", action="store_true")
    ds_delete.add_argument("--apply", action="store_true")
    ds_delete.add_argument("--plan-id", default="")
    ds_delete.add_argument("--confirm-token", default="")
    ds_sync = datasource_actions.add_parser("sync")
    ds_sync.add_argument("--id", required=True)
    ds_sync.add_argument("--name", required=True)
    ds_sync.add_argument("--apply", action="store_true")
    ds_sync.add_argument("--plan-id", default="")
    ds_sync.add_argument("--confirm-token", default="")
    ds_sync_logs = datasource_actions.add_parser("sync-logs")
    ds_sync_logs.add_argument("--id", required=True)
    ds_sync_logs.add_argument("--page", type=int, default=1)
    ds_sync_logs.add_argument("--size", type=int, default=20)

    visual = domains.add_parser("visual")
    visual_actions = visual.add_subparsers(dest="action", required=True)
    visual_list = visual_actions.add_parser("list")
    visual_list.add_argument("--busi-type", choices=("dashboard", "dataV"), default="dashboard")
    visual_capture = visual_actions.add_parser("capture")
    visual_capture.add_argument("--id", required=True)
    visual_capture.add_argument("--busi-type", choices=("dashboard", "dataV"), default="dashboard")
    visual_capture.add_argument("--pixel", default="1920*1080")
    visual_create = visual_actions.add_parser("create")
    visual_create.add_argument("--spec", default="-")
    visual_create.add_argument("--apply", action="store_true")
    visual_create.add_argument("--plan-id", default="")
    visual_create.add_argument("--confirm-token", default="")
    visual_create.add_argument("--no-capture", action="store_true")
    visual_create.add_argument("--pixel", default="1920*1080")
    visual_publish = visual_actions.add_parser("publish")
    visual_publish.add_argument("--resource-id", default="")
    visual_publish.add_argument("--name", default="")
    visual_publish.add_argument("--busi-type", choices=("dashboard", "dataV"), default="dashboard")
    visual_publish.add_argument("--status", type=int, choices=(0, 1), default=1)
    visual_publish.add_argument("--apply", action="store_true")
    visual_publish.add_argument("--plan-id", default="")
    visual_publish.add_argument("--confirm-token", default="")
    visual_delete = visual_actions.add_parser("delete")
    visual_delete.add_argument("--resource-id", default="")
    visual_delete.add_argument("--name", default="")
    visual_delete.add_argument("--busi-type", choices=("dashboard", "dataV"), default="dashboard")
    visual_delete.add_argument("--ack-no-rollback", action="store_true")
    visual_delete.add_argument("--apply", action="store_true")
    visual_delete.add_argument("--plan-id", default="")
    visual_delete.add_argument("--confirm-token", default="")

    filling = domains.add_parser("filling")
    filling_actions = filling.add_subparsers(dest="action", required=True)
    filling_actions.add_parser("list")
    filling_get = filling_actions.add_parser("get")
    filling_get.add_argument("--id", required=True)
    filling_tasks = filling_actions.add_parser("tasks")
    filling_tasks.add_argument("--form-id", required=True)
    filling_tasks.add_argument("--page", type=int, default=1)
    filling_tasks.add_argument("--size", type=int, default=20)
    filling_rows = filling_actions.add_parser("rows")
    filling_rows.add_argument("--form-id", required=True)
    filling_rows.add_argument("--page", type=int, default=1)
    filling_rows.add_argument("--size", type=int, default=20)
    filling_rows.add_argument("--with-logs", action="store_true")
    filling_row_save = filling_actions.add_parser("row-save")
    filling_row_save.add_argument("--spec", default="-")
    filling_row_save.add_argument("--apply", action="store_true")
    filling_row_save.add_argument("--plan-id", default="")
    filling_row_save.add_argument("--confirm-token", default="")
    filling_row_delete = filling_actions.add_parser("row-delete")
    filling_row_delete.add_argument("--form-id", default="")
    filling_row_delete.add_argument("--row-id", default="")
    filling_row_delete.add_argument("--ack-no-rollback", action="store_true")
    filling_row_delete.add_argument("--apply", action="store_true")
    filling_row_delete.add_argument("--plan-id", default="")
    filling_row_delete.add_argument("--confirm-token", default="")
    filling_truncate = filling_actions.add_parser("truncate")
    filling_truncate.add_argument("--form-id", default="")
    filling_truncate.add_argument("--name", default="")
    filling_truncate.add_argument("--ack-no-rollback", action="store_true")
    filling_truncate.add_argument("--apply", action="store_true")
    filling_truncate.add_argument("--plan-id", default="")
    filling_truncate.add_argument("--confirm-token", default="")
    for action in ("create", "task-create"):
        filling_create = filling_actions.add_parser(action)
        filling_create.add_argument("--spec", default="-")
        filling_create.add_argument("--apply", action="store_true")
        filling_create.add_argument("--plan-id", default="")
        filling_create.add_argument("--confirm-token", default="")
    filling_delete = filling_actions.add_parser("delete")
    filling_delete.add_argument("--id", default="")
    filling_delete.add_argument("--name", default="")
    filling_delete.add_argument("--ack-no-rollback", action="store_true")
    filling_delete.add_argument("--apply", action="store_true")
    filling_delete.add_argument("--plan-id", default="")
    filling_delete.add_argument("--confirm-token", default="")

    admin = domains.add_parser("admin")
    admin_actions = admin.add_subparsers(dest="action", required=True)
    admin_actions.add_parser("organizations")
    users = admin_actions.add_parser("users")
    users.add_argument("--page", type=int, default=1)
    users.add_argument("--size", type=int, default=100)
    roles = admin_actions.add_parser("roles")
    roles.add_argument("--keyword", default="")
    admin_actions.add_parser("settings")
    admin_actions.add_parser("authentication")
    admin_actions.add_parser("integrations")
    for action in (
        "organization-create",
        "organization-edit",
        "role-create",
        "role-edit",
        "user-create",
        "user-edit",
    ):
        command = admin_actions.add_parser(action)
        command.add_argument("--spec", default="-")
        command.add_argument("--apply", action="store_true")
        command.add_argument("--plan-id", default="")
        command.add_argument("--confirm-token", default="")
    for action in ("organization-delete", "role-delete", "user-delete"):
        command = admin_actions.add_parser(action)
        command.add_argument("--id", default="")
        if action == "user-delete":
            command.add_argument("--account", dest="identity", default="")
        else:
            command.add_argument("--name", dest="identity", default="")
        command.add_argument("--ack-no-rollback", action="store_true")
        command.add_argument("--apply", action="store_true")
        command.add_argument("--plan-id", default="")
        command.add_argument("--confirm-token", default="")
    user_enable = admin_actions.add_parser("user-enable")
    user_enable.add_argument("--id", default="")
    user_enable.add_argument("--account", default="")
    user_enable.add_argument("--enable", choices=("true", "false"), default=None)
    user_enable.add_argument("--apply", action="store_true")
    user_enable.add_argument("--plan-id", default="")
    user_enable.add_argument("--confirm-token", default="")
    user_reset = admin_actions.add_parser("user-reset-password")
    user_reset.add_argument("--id", default="")
    user_reset.add_argument("--account", default="")
    user_reset.add_argument("--ack-no-rollback", action="store_true")
    user_reset.add_argument("--apply", action="store_true")
    user_reset.add_argument("--plan-id", default="")
    user_reset.add_argument("--confirm-token", default="")

    setting_read = admin_actions.add_parser("setting-read")
    setting_read.add_argument(
        "--scope",
        required=True,
        choices=("system-basic", "auth-basic", "auth-mfa", "auth-hmac", "email"),
    )
    setting_save = admin_actions.add_parser("setting-save")
    setting_save.add_argument(
        "--scope",
        required=True,
        choices=("system-basic", "auth-basic", "auth-mfa", "auth-hmac", "email"),
    )
    setting_save.add_argument("--spec", default="-")
    setting_save.add_argument("--ack-no-rollback", action="store_true")
    setting_save.add_argument("--apply", action="store_true")
    setting_save.add_argument("--plan-id", default="")
    setting_save.add_argument("--confirm-token", default="")
    setting_validate = admin_actions.add_parser("setting-validate")
    setting_validate.add_argument("--scope", required=True, choices=("email",))
    setting_validate.add_argument("--spec", default="-")
    for action in ("integration-validate", "integration-save"):
        command = admin_actions.add_parser(action)
        command.add_argument("--provider", required=True, choices=("wecom", "dingtalk", "lark", "larksuite"))
        command.add_argument("--spec", default="-")
        if action == "integration-save":
            command.add_argument("--ack-no-rollback", action="store_true")
            command.add_argument("--apply", action="store_true")
            command.add_argument("--plan-id", default="")
            command.add_argument("--confirm-token", default="")
    integration_enable = admin_actions.add_parser("integration-enable")
    integration_enable.add_argument("--provider", required=True, choices=("wecom", "dingtalk", "lark", "larksuite"))
    integration_enable.add_argument("--enable", required=True, choices=("true", "false"))
    integration_enable.add_argument("--apply", action="store_true")
    integration_enable.add_argument("--plan-id", default="")
    integration_enable.add_argument("--confirm-token", default="")
    admin_actions.add_parser("sso-list")
    admin_actions.add_parser("sso-status")
    sso_info = admin_actions.add_parser("sso-info")
    sso_info.add_argument("--provider", required=True, choices=("ldap", "oidc", "cas", "oauth2", "saml2"))
    for action in ("sso-validate", "sso-save"):
        command = admin_actions.add_parser(action)
        command.add_argument("--provider", required=True, choices=("ldap", "oidc", "cas", "oauth2", "saml2"))
        command.add_argument("--spec", default="-")
        if action == "sso-save":
            command.add_argument("--ack-no-rollback", action="store_true")
            command.add_argument("--apply", action="store_true")
            command.add_argument("--plan-id", default="")
            command.add_argument("--confirm-token", default="")
    sso_enable = admin_actions.add_parser("sso-enable")
    sso_enable.add_argument("--id", required=True)
    sso_enable.add_argument("--name", required=True)
    sso_enable.add_argument("--enable", required=True, choices=("true", "false"))
    sso_enable.add_argument("--apply", action="store_true")
    sso_enable.add_argument("--plan-id", default="")
    sso_enable.add_argument("--confirm-token", default="")

    report = domains.add_parser("report")
    report_actions = report.add_subparsers(dest="action", required=True)
    report_list = report_actions.add_parser("list")
    report_list.add_argument("--page", type=int, default=1)
    report_list.add_argument("--size", type=int, default=100)
    report_list.add_argument("--keyword", default="")
    report_info = report_actions.add_parser("info")
    report_info.add_argument("--id", required=True)
    report_logs = report_actions.add_parser("logs")
    report_logs.add_argument("--id", required=True)
    report_logs.add_argument("--page", type=int, default=1)
    report_logs.add_argument("--size", type=int, default=20)
    for action in ("create", "update"):
        command = report_actions.add_parser(action)
        command.add_argument("--spec", default="-")
        command.add_argument("--ack-no-rollback", action="store_true")
        command.add_argument("--apply", action="store_true")
        command.add_argument("--plan-id", default="")
        command.add_argument("--confirm-token", default="")
    for action in ("fire-now", "start", "stop"):
        command = report_actions.add_parser(action)
        command.add_argument("--id", required=True)
        command.add_argument("--name", required=True)
        command.add_argument("--apply", action="store_true")
        command.add_argument("--plan-id", default="")
        command.add_argument("--confirm-token", default="")
    report_delete = report_actions.add_parser("delete")
    report_delete.add_argument("--id", required=True)
    report_delete.add_argument("--name", required=True)
    report_delete.add_argument("--ack-no-rollback", action="store_true")
    report_delete.add_argument("--apply", action="store_true")
    report_delete.add_argument("--plan-id", default="")
    report_delete.add_argument("--confirm-token", default="")

    webhook = domains.add_parser("webhook")
    webhook_actions = webhook.add_subparsers(dest="action", required=True)
    webhook_list = webhook_actions.add_parser("list")
    webhook_list.add_argument("--page", type=int, default=1)
    webhook_list.add_argument("--size", type=int, default=100)
    webhook_list.add_argument("--keyword", default="")
    webhook_get = webhook_actions.add_parser("get")
    webhook_get.add_argument("--id", required=True)
    webhook_actions.add_parser("options")
    webhook_save = webhook_actions.add_parser("save")
    webhook_save.add_argument("--spec", default="-")
    webhook_save.add_argument("--ack-no-rollback", action="store_true")
    webhook_save.add_argument("--apply", action="store_true")
    webhook_save.add_argument("--plan-id", default="")
    webhook_save.add_argument("--confirm-token", default="")
    webhook_ssl = webhook_actions.add_parser("ssl")
    webhook_ssl.add_argument("--id", required=True)
    webhook_ssl.add_argument("--name", required=True)
    webhook_ssl.add_argument("--ssl", required=True, choices=("true", "false"))
    webhook_ssl.add_argument("--apply", action="store_true")
    webhook_ssl.add_argument("--plan-id", default="")
    webhook_ssl.add_argument("--confirm-token", default="")
    webhook_delete = webhook_actions.add_parser("delete")
    webhook_delete.add_argument("--id", required=True)
    webhook_delete.add_argument("--name", required=True)
    webhook_delete.add_argument("--ack-no-rollback", action="store_true")
    webhook_delete.add_argument("--apply", action="store_true")
    webhook_delete.add_argument("--plan-id", default="")
    webhook_delete.add_argument("--confirm-token", default="")
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = _settings(args)
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        plans = PlanStore(settings.output_dir)
        audit = AuditLog(settings.output_dir)
        with DataEaseClient(settings) as client:
            if settings.org_id:
                client.ensure_organization(settings.org_id)
            datasets = DatasetService(client)
            platform = PlatformService(client)

            key = f"{args.domain}.{args.action}"
            if key == "system.doctor":
                capabilities = CapabilityService(client).scan()
                result = _envelope(key, {"connection": "ok", "diagnostics": client.public_diagnostics(), **capabilities})
            elif key == "system.capabilities":
                result = _envelope(key, CapabilityService(client).scan())
            elif key == "inventory.scan":
                result = _envelope(key, platform.inventory())
            elif key == "dataset.list":
                result = _envelope(key, datasets.list())
            elif key == "dataset.fields":
                dataset, fields = datasets.fields(args.dataset)
                result = _envelope(key, {"dataset": dataset, "fields": fields})
            elif key == "dataset.profile":
                result = _envelope(key, datasets.profile(args.dataset))
            elif key == "dataset.plan":
                result = _envelope(key, build_visual_plan(datasets.profile(args.dataset), args.title, args.busi_type))
            elif key == "datasource.list":
                result = _envelope(key, platform.datasources())
            elif key == "datasource.types":
                result = _envelope(key, client.data("GET", "/datasource/types"))
            elif key == "datasource.validate":
                result = _envelope(key, client.data("GET", f"/datasource/validate/{args.id}"))
            elif args.domain in {"datasource", "dataset"} and args.action in {
                "folder-create",
                "rename",
                "create",
                "update",
                "delete",
                "validate-spec",
                "sync",
                "sync-logs",
            }:
                result = handle_data_mutation(args, settings, client, plans, audit)
            elif key == "visual.list":
                result = _envelope(key, platform.resources(args.busi_type))
            elif key == "visual.capture":
                capture = _capture(settings, args.id, args.busi_type, args.pixel)
                result = _envelope(key, capture, artifacts=[capture.get("saved_file")] if capture.get("saved_file") else [])
            elif key == "visual.create":
                result = _visual_create(args, settings, client, plans, audit)
            elif key == "visual.publish":
                result = _visual_publish(args, client, plans, audit)
            elif key == "visual.delete":
                result = _visual_delete(args, settings, client, plans, audit)
            elif key == "filling.list":
                result = _envelope(key, platform.filling_forms())
            elif key == "filling.get":
                result = _envelope(key, client.data("GET", f"/data-filling/get/{args.id}"))
            elif key == "filling.tasks":
                result = _envelope(
                    key,
                    client.data("POST", f"/data-filling/form/{args.form_id}/task/page/{args.page}/{args.size}", {}),
                )
            elif key == "filling.rows":
                result = _envelope(
                    key,
                    _filling_table_data(
                        client,
                        args.form_id,
                        page=args.page,
                        size=args.size,
                        without_logs=not args.with_logs,
                    ),
                )
            elif key == "filling.row-save":
                result = _filling_row_save(args, client, plans, audit)
            elif key == "filling.row-delete":
                result = _filling_row_delete(args, settings, client, plans, audit)
            elif key == "filling.truncate":
                result = _filling_truncate(args, client, plans, audit)
            elif key in {"filling.create", "filling.task-create"}:
                result = _filling_create(args, client, plans, audit)
            elif key == "filling.delete":
                result = _filling_delete(args, settings, client, plans, audit)
            elif key == "admin.organizations":
                result = _envelope(key, platform.organizations())
            elif key == "admin.users":
                result = _envelope(key, platform.users(args.page, args.size))
            elif key == "admin.roles":
                result = _envelope(key, platform.roles(args.keyword))
            elif key == "admin.settings":
                result = _envelope(key, platform.system_settings())
            elif key == "admin.authentication":
                result = _envelope(key, platform.authentication_settings())
            elif key == "admin.integrations":
                result = _envelope(key, platform.integration_status())
            elif args.domain == "admin" and args.action in {
                "setting-read",
                "setting-save",
                "setting-validate",
                "integration-validate",
                "integration-save",
                "integration-enable",
                "sso-list",
                "sso-status",
                "sso-info",
                "sso-validate",
                "sso-save",
                "sso-enable",
            }:
                result = handle_settings_operation(args, settings, client, plans, audit)
            elif args.domain == "admin":
                result = handle_admin_mutation(args, settings, client, plans, audit)
            elif args.domain in {"report", "webhook"}:
                result = handle_automation_operation(args, settings, client, plans, audit)
            else:
                raise DataEaseError(f"未实现命令: {key}", code="unsupported_operation", stage="routing")
        return _json(result)
    except DataEaseError as exc:
        return _json({"schema_version": 1, "ok": False, "error": exc.to_dict()}, 1)
    except Exception as exc:
        error = DataEaseError(str(exc), code="unexpected_error", stage="runtime")
        return _json({"schema_version": 1, "ok": False, "error": error.to_dict()}, 1)


def main() -> None:
    raise SystemExit(run())
