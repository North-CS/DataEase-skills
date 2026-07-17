from __future__ import annotations

import base64
import copy
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
from .versioning import adapter_for_client


PERMISSION_ENDPOINTS = {
    "row": "/dataset/rowPermissions",
    "column": "/dataset/columnPermissions",
}


def _envelope(operation: str, result: Any, **extra: Any) -> dict[str, Any]:
    return {"schema_version": 1, "ok": True, "operation": operation, "result": result,
            "warnings": extra.pop("warnings", []), **extra}


def _load(path: str) -> dict[str, Any]:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8-sig")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataEaseError(f"JSON 配置无效: {exc}", code="invalid_spec", stage="input") from exc
    if not isinstance(value, dict):
        raise DataEaseError("配置根节点必须是对象", code="invalid_spec", stage="input")
    return value


def _digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _context(client: DataEaseClient) -> dict[str, Any]:
    version = client.data("GET", "/license/version")
    return {"base_url": client.settings.base_url, "api_prefix": client.settings.api_prefix,
            "org_id": client.settings.org_id or None, "version": version}


def _require(client: DataEaseClient, feature: str, *, mutation: bool = False) -> None:
    version, adapter = adapter_for_client(client)
    adapter.require(feature, version, mutation=mutation, client=client)


def _detail(client: DataEaseClient, dataset_id: str) -> dict[str, Any]:
    value = client.data("POST", f"/datasetTree/details/{dataset_id}", {})
    if not isinstance(value, dict) or str(value.get("id")) != str(dataset_id):
        raise DataEaseError(f"找不到数据集: {dataset_id}", code="resource_not_found", stage="dataset")
    return value


def _snapshot(settings: Settings, kind: str, resource_id: str, value: Any) -> str:
    directory = settings.output_dir / "snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{kind}-{resource_id}-{int(time.time())}.json"
    path.write_text(json.dumps(redact_configuration(value), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def validate_model_spec(spec: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in ("name", "pid", "nodeType", "mode") if spec.get(key) in (None, "")]
    if missing:
        raise DataEaseError("数据集模型缺少必填字段", code="invalid_spec", stage="input", details={"fields": missing})
    if spec.get("nodeType") != "dataset":
        raise DataEaseError("nodeType 必须为 dataset", code="invalid_spec", stage="input")
    explicit_type = spec.get("type")
    if explicit_type not in (None, "", "db", "sql", "union"):
        raise DataEaseError("不支持的数据集模型 type", code="invalid_spec", stage="input")
    unions = spec.get("union")
    direct_sql = str(spec.get("sql") or "").strip()
    if explicit_type == "sql" and not direct_sql and not unions:
        raise DataEaseError("SQL 数据集必须提供 sql 或 SQL union 节点", code="invalid_spec", stage="input")
    if not direct_sql and (not isinstance(unions, list) or not unions):
        raise DataEaseError("物理表/多表/SQL 数据集必须提供非空 union", code="invalid_spec", stage="input")
    table_types: list[str] = []

    def visit(nodes: list[Any], prefix: str = "union") -> int:
        count = 0
        for index, union in enumerate(nodes):
            if not isinstance(union, dict) or not isinstance(union.get("currentDs"), dict):
                raise DataEaseError(f"{prefix}[{index}] 缺少 currentDs", code="invalid_spec", stage="input")
            current_type = str(union["currentDs"].get("type") or "db")
            if current_type not in {"db", "sql"}:
                raise DataEaseError(f"{prefix}[{index}].currentDs.type 不受支持", code="invalid_spec", stage="input")
            table_types.append(current_type)
            count += 1
            children = union.get("childrenDs") or []
            if not isinstance(children, list):
                raise DataEaseError(f"{prefix}[{index}].childrenDs 必须为数组", code="invalid_spec", stage="input")
            count += visit(children, f"{prefix}[{index}].childrenDs")
        return count

    table_count = visit(unions) if isinstance(unions, list) else 0
    if direct_sql and not table_count:
        model_type = "sql"
    elif explicit_type == "union" or table_count > 1:
        model_type = "union"
    elif table_types == ["sql"]:
        model_type = "sql"
    else:
        model_type = "physical"
    fields = spec.get("allFields", [])
    if fields is not None and not isinstance(fields, list):
        raise DataEaseError("allFields 必须为数组", code="invalid_spec", stage="input")
    features = [
        "sql-dataset" if model_type == "sql" else
        "multi-table-join" if model_type == "union" else
        "physical-table"
    ]
    if fields:
        features.append("field-model")
    if spec.get("parameters") or spec.get("sqlParams"):
        features.append("parameters")
    if spec.get("syncStrategy") or spec.get("syncSetting"):
        features.append("scheduled-sync")
    return {"valid": True, "model_type": model_type, "features": features,
            "table_count": table_count, "field_count": len(fields or [])}


def _stable_model_id(seed: str) -> str:
    # DataEase's web client supplies Long-compatible temporary IDs before create.
    # Keep generated values deterministic so dry-run and apply normalize identically.
    value = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16) % 900_000_000_000_000_000
    return str(7_000_000_000_000_000_000 + value)


def prepare_new_model_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Fill client-side identities required by DataEase when creating a model."""
    prepared = copy.deepcopy(spec)
    if prepared.get("id") not in (None, ""):
        return prepared
    validate_model_spec(prepared)
    unions = prepared.get("union") or []
    if not unions:
        return prepared
    model_name = str(prepared.get("name"))
    flattened_fields: list[dict[str, Any]] = []

    def field_name(field: dict[str, Any]) -> str:
        return str(field.get("originName") or field.get("name") or "")

    def prepare_node(node: dict[str, Any], path: str,
                     parent_fields: list[dict[str, Any]] | None = None) -> None:
        current = node["currentDs"]
        table_name = str(current.get("tableName") or current.get("name") or path)
        datasource_id = str(current.get("datasourceId") or "")
        table_seed = f"{model_name}|{path}|{datasource_id}|{table_name}"
        current["id"] = str(current.get("id") or _stable_model_id(f"table|{table_seed}"))
        current["name"] = current.get("name") or table_name
        current["type"] = current.get("type") or "db"
        if current.get("isCross") is None:
            current["isCross"] = bool(prepared.get("isCross", False))
        if not current.get("info") and current["type"] == "db":
            current["info"] = json.dumps({"table": table_name}, ensure_ascii=False, separators=(",", ":"))
        fields = node.get("currentDsFields") or []
        if not isinstance(fields, list) or not fields:
            raise DataEaseError(f"{path}.currentDsFields 不能为空", code="invalid_spec", stage="input")
        names: set[str] = set()
        for index, field in enumerate(fields):
            if not isinstance(field, dict) or not field_name(field):
                raise DataEaseError(f"{path}.currentDsFields[{index}] 缺少字段名",
                                    code="invalid_spec", stage="input")
            origin = field_name(field)
            if origin in names:
                raise DataEaseError(f"{path} 包含重复字段: {origin}", code="invalid_spec", stage="input")
            names.add(origin)
            seed = f"{table_seed}|{origin}|{index}"
            field["id"] = str(field.get("id") or _stable_model_id(f"field|{seed}"))
            field["datasourceId"] = field.get("datasourceId") or current.get("datasourceId")
            field["datasetTableId"] = str(field.get("datasetTableId") or current["id"])
            alias = str(field.get("dataeaseName") or f"f_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}")
            field["dataeaseName"] = alias
            field["fieldShortName"] = field.get("fieldShortName") or alias
            field["description"] = field.get("description") or field.get("name") or origin
            flattened_fields.append(copy.deepcopy(field))

        linkage = node.get("unionToParent") or {"unionType": "left", "unionFields": []}
        node["unionToParent"] = linkage
        links = linkage.get("unionFields") or []
        if not isinstance(links, list):
            raise DataEaseError(f"{path}.unionToParent.unionFields 必须为数组",
                                code="invalid_spec", stage="input")
        if parent_fields is not None:
            parent_by_name = {field_name(field): field for field in parent_fields}
            current_by_name = {field_name(field): field for field in fields}
            for index, link in enumerate(links):
                if not isinstance(link, dict):
                    raise DataEaseError(f"{path} 关联键格式无效", code="invalid_spec", stage="input")
                parent_name = field_name(link.get("parentField") or {})
                current_name = field_name(link.get("currentField") or {})
                if parent_name not in parent_by_name or current_name not in current_by_name:
                    raise DataEaseError(f"{path}.unionFields[{index}] 无法解析关联字段",
                                        code="invalid_spec", stage="input")
                link["parentField"] = copy.deepcopy(parent_by_name[parent_name])
                link["currentField"] = copy.deepcopy(current_by_name[current_name])

        children = node.get("childrenDs") or []
        for index, child in enumerate(children):
            prepare_node(child, f"{path}.childrenDs[{index}]", fields)

    for index, union in enumerate(unions):
        prepare_node(union, f"union[{index}]")
    prepared["allFields"] = flattened_fields
    return prepared


def inspect_model(client: DataEaseClient, dataset_id: str) -> dict[str, Any]:
    _require(client, "dataset_modeling")
    detail = _detail(client, dataset_id)
    params = client.data("POST", "/datasetTree/getSqlParams", [int(dataset_id)])
    permissions: dict[str, Any] = {}
    for kind, endpoint in PERMISSION_ENDPOINTS.items():
        try:
            permissions[kind] = client.data("GET", f"{endpoint}/pager/{dataset_id}/1/100")
        except DataEaseError as exc:
            permissions[kind] = {"available": False, "reason": exc.code}
    return {"dataset": detail, "parameters": params, "permissions": permissions}


def _plan_apply(args: Any, settings: Settings, client: DataEaseClient, plans: PlanStore,
                audit: AuditLog, *, operation: str, feature: str, endpoint: str, risk: str,
                target: dict[str, Any], current: Any = None, verify: Any = None) -> dict[str, Any]:
    spec = getattr(args, "_model_spec", None) or _load(args.spec)
    _require(client, feature, mutation=True)
    if operation == "model.save":
        validation = validate_model_spec(spec)
    else:
        validation = {"valid": True}
    if not args.apply:
        snapshot = (
            _snapshot(settings, operation.replace(".", "-"), str(target.get("id") or "new"), current)
            if current is not None else None
        )
        plan = plans.create(operation, target=target,
                            changes=[{"action": operation.split(".")[-1], "validation": validation}], risk=risk,
                            spec={"payload_sha256": _digest(spec), "precondition_sha256": _digest(current)},
                            rollback={"strategy": "restore-snapshot" if snapshot else "delete-created-resource",
                                      "snapshot": snapshot, "automatic": False}, context=_context(client))
        return _envelope(operation, plan, mode="dry-run", artifacts=[snapshot] if snapshot else [])
    if not args.plan_id:
        raise DataEaseError("执行变更需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_context(client))
    if plan.get("operation") != operation or plan.get("spec", {}).get("payload_sha256") != _digest(spec):
        raise DataEaseError("apply 配置与 dry-run 不一致", code="spec_changed", stage="safety")
    if plan.get("spec", {}).get("precondition_sha256") != _digest(current):
        raise DataEaseError("目标模型已变化，请重新 dry-run", code="target_changed", stage="safety")
    response = client.data("POST", endpoint, spec)
    result = verify(response, spec) if callable(verify) else response
    audit_id = audit.write(operation, status="success", risk=risk, target=plan.get("target"),
                           changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    artifacts = [plan.get("rollback", {}).get("snapshot")] if plan.get("rollback", {}).get("snapshot") else []
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id, artifacts=artifacts)


def handle_model_operation(args: Any, settings: Settings, client: DataEaseClient,
                           plans: PlanStore, audit: AuditLog) -> dict[str, Any]:
    key = f"model.{args.action}"
    if args.action == "inspect":
        return _envelope(key, inspect_model(client, args.dataset_id))
    if args.action == "params":
        _require(client, "dataset_parameters")
        ids = [int(item) for item in args.dataset_id]
        return _envelope(key, client.data("POST", "/datasetTree/getSqlParams", ids))
    if args.action == "validate":
        _require(client, "dataset_modeling")
        return _envelope(key, validate_model_spec(_load(args.spec)))
    if args.action == "preview":
        spec = _load(args.spec)
        if args.preview_type == "dataset" and not spec.get("id"):
            spec = prepare_new_model_spec(spec)
        feature = "sql_dataset" if args.preview_type == "sql" else "dataset_modeling"
        _require(client, feature)
        endpoint = "/datasetData/previewSql" if args.preview_type == "sql" else "/datasetData/previewData"
        return _envelope(key, client.data("POST", endpoint, spec))
    if args.action == "save":
        candidate = _load(args.spec)
        if not candidate.get("id"):
            candidate = prepare_new_model_spec(candidate)
        args._model_spec = candidate
        dataset_id = str(candidate.get("id") or "")
        current = _detail(client, dataset_id) if dataset_id else None

        def verify_model(response: Any, spec: dict[str, Any]) -> Any:
            resource_id = str(response.get("id") if isinstance(response, dict) else response)
            if not resource_id:
                raise DataEaseError("保存接口未返回数据集 ID", code="invalid_response", stage="verification")
            after = _detail(client, resource_id)
            if str(after.get("name")) != str(spec.get("name")) or str(after.get("type")) != str(spec.get("type")):
                raise DataEaseError("模型保存后回读不一致", code="verification_failed", stage="verification")
            return after

        endpoint = "/datasetTree/save" if dataset_id else "/datasetTree/create"
        return _plan_apply(args, settings, client, plans, audit, operation=key, feature="dataset_modeling",
                           endpoint=endpoint, risk="L2", target={"id": dataset_id or None,
                           "name": candidate.get("name"), "type": candidate.get("type")}, current=current,
                           verify=verify_model)
    if args.action == "calculated-save":
        candidate = _load(args.spec)
        requested_field_id = str(candidate.get("id") or "")
        dataset_id = str(candidate.get("datasetGroupId") or "")
        if not dataset_id:
            raise DataEaseError("计算字段必须包含 datasetGroupId", code="invalid_spec", stage="input")
        before_dataset = _detail(client, dataset_id)
        is_create = not requested_field_id
        if is_create:
            existing = [
                item for item in (before_dataset.get("allFields") or [])
                if isinstance(item, dict) and int(item.get("extField") or 0) == 2
                and str(item.get("name")) == str(candidate.get("name"))
            ]
            if existing:
                raise DataEaseError("同名计算字段已存在", code="resource_exists", stage="dataset")
            seed = f"calculated|{dataset_id}|{candidate.get('name')}|{candidate.get('originName')}"
            field_id = _stable_model_id(seed)
            alias = str(candidate.get("dataeaseName") or
                        f"f_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}")
            candidate["id"] = field_id
            candidate["dataeaseName"] = alias
            candidate["fieldShortName"] = candidate.get("fieldShortName") or alias
            current = before_dataset
        else:
            field_id = requested_field_id
            current = client.data("POST", f"/datasetField/get/{field_id}", {})
            if not isinstance(current, dict) or str(current.get("id")) != field_id:
                raise DataEaseError("找不到待更新的计算字段", code="resource_not_found", stage="dataset")
        args._model_spec = candidate

        def verify_field(response: Any, spec: dict[str, Any]) -> Any:
            field = response if isinstance(response, dict) else {}
            resource_id = str(field.get("id") or spec.get("id") or
                              (response if isinstance(response, (str, int)) else ""))
            if resource_id:
                after = client.data("POST", f"/datasetField/get/{resource_id}", {})
            else:
                dataset_after = _detail(client, dataset_id)
                matches = [
                    item for item in (dataset_after.get("allFields") or [])
                    if isinstance(item, dict) and int(item.get("extField") or 0) == 2
                    and str(item.get("name")) == str(spec.get("name"))
                    and str(item.get("originName")) == str(spec.get("originName"))
                ]
                if len(matches) != 1:
                    raise DataEaseError("计算字段保存后无法唯一回读", code="verification_failed",
                                        stage="verification", details={"matches": len(matches)})
                after = matches[0]
            if not isinstance(after, dict) or str(after.get("name")) != str(spec.get("name")):
                raise DataEaseError("计算字段保存后回读不一致", code="verification_failed", stage="verification")
            return after

        return _plan_apply(args, settings, client, plans, audit, operation=key, feature="calculated_fields",
                           endpoint="/datasetField/save", risk="L2", target={"id": None if is_create else field_id,
                           "name": candidate.get("name"), "dataset_id": dataset_id},
                           current=current, verify=verify_field)
    if args.action == "permission-list":
        _require(client, "row_column_permissions")
        endpoint = PERMISSION_ENDPOINTS[args.kind]
        return _envelope(key, client.data("GET", f"{endpoint}/pager/{args.dataset_id}/{args.page}/{args.size}"))
    if args.action in {"permission-save", "permission-delete"}:
        candidate = _load(args.spec)
        args._model_spec = candidate
        dataset_id = str(candidate.get("datasetId") or candidate.get("datasetGroupId") or "")
        if not dataset_id:
            raise DataEaseError("权限配置必须包含 datasetId", code="invalid_spec", stage="input")
        endpoint = PERMISSION_ENDPOINTS[args.kind]
        current = client.data("GET", f"{endpoint}/pager/{dataset_id}/1/1000")
        action = "save" if args.action.endswith("save") else "delete"
        before_records = current.get("records", []) if isinstance(current, dict) else current if isinstance(current, list) else []
        before_records = [item for item in before_records if isinstance(item, dict)]
        before_ids = {str(item.get("id")) for item in before_records if item.get("id") is not None}
        permission_id = candidate.get("id")
        if action == "delete" and permission_id in (None, ""):
            raise DataEaseError("删除行列权限必须提供 id", code="invalid_spec", stage="input")
        if action == "save" and permission_id not in (None, "") and str(permission_id) not in before_ids:
            raise DataEaseError("找不到待更新的行列权限", code="resource_not_found", stage="dataset")
        target_type = str(candidate.get("authTargetType") or "")
        target_ids = candidate.get("authTargetIds")
        if not isinstance(target_ids, list):
            target_ids = [candidate.get("authTargetId")] if candidate.get("authTargetId") not in (None, "") else []
        normalized_target_ids = {str(item) for item in target_ids if item not in (None, "")}
        if action == "save" and permission_id in (None, "") and (not target_type or not normalized_target_ids):
            raise DataEaseError("新建行列权限必须提供 authTargetType 和 authTargetId/authTargetIds",
                                code="invalid_spec", stage="input")

        def verify_permission(response: Any, request: dict[str, Any]) -> Any:
            after = client.data("GET", f"{endpoint}/pager/{dataset_id}/1/1000")
            before_digest = _digest(current)
            after_digest = _digest(after)
            records = after.get("records", []) if isinstance(after, dict) else after if isinstance(after, list) else []
            records = [item for item in records if isinstance(item, dict)]
            ids = {str(item.get("id")) for item in records if item.get("id") is not None}
            if action == "delete" and str(permission_id) in ids:
                raise DataEaseError("权限删除后仍可回读", code="verification_failed", stage="verification")
            if action == "save" and permission_id not in (None, "") and str(permission_id) not in ids:
                raise DataEaseError("权限保存后无法回读", code="verification_failed", stage="verification")
            changed: list[dict[str, Any]] = []
            if action == "save" and permission_id in (None, ""):
                changed = [item for item in records if str(item.get("id")) not in before_ids]
                matching = [
                    item for item in changed
                    if str(item.get("authTargetType") or "") == target_type
                    and str(item.get("authTargetId")) in normalized_target_ids
                ]
                if not matching:
                    raise DataEaseError("权限新建后未发现匹配的新增记录", code="verification_failed",
                                        stage="verification", details={"created_records": len(changed)})
                changed = matching
            if before_digest == after_digest:
                raise DataEaseError("权限操作后状态未变化", code="verification_failed", stage="verification")
            return {"response": response, "before_sha256": before_digest, "after_sha256": after_digest,
                    "changed_records": changed}

        return _plan_apply(args, settings, client, plans, audit, operation=key,
                           feature="row_column_permissions", endpoint=f"{endpoint}/{action}", risk="L3",
                           target={"dataset_id": dataset_id, "permission_kind": args.kind}, current=current,
                           verify=verify_permission)
    if args.action == "cron-preview":
        spec = _load(args.spec)
        return _envelope(key, client.data("POST", "/datasource/cronNextTimes", spec))
    if args.action == "sync-policy":
        spec = _load(args.spec)
        missing = [field for field in ("id", "name", "type", "configuration", "syncSetting")
                   if spec.get(field) in (None, "")]
        if missing:
            raise DataEaseError("同步策略必须提交完整数据源 DTO", code="invalid_spec", stage="input",
                                details={"missing": missing})
        if not args.ack_no_rollback:
            raise DataEaseError("数据源旧凭据无法从 hidePw 恢复；需要 --ack-no-rollback",
                                code="rollback_ack_required", stage="safety")
        _require(client, "dataset_modeling", mutation=True)
        datasource_id = str(spec["id"])
        current = client.data("GET", f"/datasource/hidePw/{datasource_id}")
        if not isinstance(current, dict) or str(current.get("name")) != str(spec["name"]):
            raise DataEaseError("name 与目标数据源不一致", code="target_mismatch", stage="safety")
        next_times: Any = []
        if isinstance(spec.get("syncSetting"), dict) and spec["syncSetting"].get("cron"):
            next_times = client.data("POST", "/datasource/cronNextTimes", spec["syncSetting"])
        if not args.apply:
            snapshot = _snapshot(settings, "datasource-sync-policy", datasource_id, current)
            plan = plans.create(key, target={"id": datasource_id, "name": spec["name"], "type": spec["type"]},
                                changes=[{"action": "replace-sync-policy", "next_times": next_times}], risk="L3",
                                spec={"payload_sha256": _digest(spec), "precondition_sha256": _digest(current),
                                      "snapshot": snapshot},
                                rollback={"available": False, "reason": "旧数据源凭据不可恢复", "snapshot": snapshot},
                                context=_context(client))
            return _envelope(key, plan, mode="dry-run", artifacts=[snapshot])
        if not args.plan_id:
            raise DataEaseError("执行同步策略变更需要 --plan-id", code="plan_required", stage="safety")
        plan = plans.load(args.plan_id, args.confirm_token, expected_context=_context(client))
        stored = plan.get("spec", {})
        if plan.get("operation") != key or stored.get("payload_sha256") != _digest(spec):
            raise DataEaseError("apply 配置与 dry-run 不一致", code="spec_changed", stage="safety")
        if stored.get("precondition_sha256") != _digest(current):
            raise DataEaseError("目标数据源已变化，请重新 dry-run", code="target_changed", stage="safety")
        request = dict(spec)
        if isinstance(request.get("configuration"), (dict, list)):
            raw = json.dumps(request["configuration"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            request["configuration"] = base64.b64encode(raw).decode("ascii")
        response = client.data("POST", "/datasource/update", request)
        after = client.data("GET", f"/datasource/hidePw/{datasource_id}")
        if not isinstance(after, dict) or str(after.get("name")) != str(spec["name"]):
            raise DataEaseError("同步策略保存后数据源回读不一致", code="verification_failed", stage="verification")
        if after.get("syncSetting") is None:
            raise DataEaseError("同步策略保存后无法从数据源详情回读", code="verification_failed",
                                stage="verification")
        if _digest(after.get("syncSetting")) != _digest(spec.get("syncSetting")):
            raise DataEaseError("同步策略回读不一致", code="verification_failed", stage="verification")
        result = {"id": datasource_id, "name": after.get("name"), "syncSetting": after.get("syncSetting"),
                  "next_times": next_times, "response": response}
        audit_id = audit.write(key, status="success", risk="L3", target=plan.get("target"),
                               changes=plan.get("changes"), result=result)
        plans.mark_applied(args.plan_id, audit_id)
        return _envelope(key, result, mode="apply", adapter="official-api", audit_id=audit_id,
                         artifacts=[stored.get("snapshot")])
    raise DataEaseError(f"不支持的模型操作: {args.action}", code="unsupported_operation", stage="dispatch")
