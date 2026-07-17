from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

from .audit import AuditLog
from .client import DataEaseClient
from .config import Settings
from .errors import DataEaseError
from .redact import redact_configuration
from .safety import PlanStore
from .versioning import adapter_for_client, format_version


BUNDLE_SCHEMA = "dataease-portable-bundle/v1"
REFERENCE_KEYS = {"tableId", "datasetGroupId", "datasetTableId", "datasourceId", "sourceTableId", "targetTableId"}


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
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _context(client: DataEaseClient) -> dict[str, Any]:
    version = client.data("GET", "/license/version")
    return {"base_url": client.settings.base_url, "api_prefix": client.settings.api_prefix,
            "org_id": client.settings.org_id or None, "version": version}


def _visual_detail(client: DataEaseClient, resource_id: str, busi_type: str) -> tuple[dict[str, Any], Any, Any]:
    version, adapter = adapter_for_client(client)
    detail = adapter.visual_detail(client, resource_id, busi_type, version)
    return detail, version, adapter


def _dataset_detail(client: DataEaseClient, resource_id: str) -> dict[str, Any]:
    value = client.data("POST", f"/datasetTree/details/{resource_id}", {})
    if not isinstance(value, dict):
        raise DataEaseError("数据集详情接口未返回对象", code="invalid_response", stage="transfer")
    return value


def _permission_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("records", "list", "items"):
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
    return []


def _references(value: Any, result: dict[str, set[str]] | None = None) -> dict[str, list[str]]:
    collected = result or {key: set() for key in REFERENCE_KEYS}
    if isinstance(value, dict):
        for key, item in value.items():
            if key in REFERENCE_KEYS and item not in (None, "") and not isinstance(item, (dict, list)):
                collected[key].add(str(item))
            _references(item, collected)
    elif isinstance(value, list):
        for item in value:
            _references(item, collected)
    return {key: sorted(items) for key, items in collected.items() if items}


def build_bundle(client: DataEaseClient, resource_type: str, resource_id: str,
                 busi_type: str = "dashboard") -> dict[str, Any]:
    version, adapter = adapter_for_client(client)
    adapter.require("json_backup_restore", version)
    relations: dict[str, Any] = {}
    if resource_type == "visual":
        payload, _, adapter = _visual_detail(client, resource_id, busi_type)
        try:
            relations["linkages"] = client.data("GET", adapter.linkage_all_path(resource_id, "snapshot"))
        except DataEaseError:
            relations["linkages"] = {"available": False}
        resource = {"id": resource_id, "name": payload.get("name"), "kind": busi_type}
    elif resource_type == "dataset":
        payload = _dataset_detail(client, resource_id)
        relations["sql_parameters"] = client.data("POST", "/datasetTree/getSqlParams", [int(resource_id)])
        for kind in ("row", "column"):
            endpoint = f"/dataset/{kind}Permissions/pager/{resource_id}/1/1000"
            try:
                relations[f"{kind}_permissions"] = client.data("GET", endpoint)
            except DataEaseError:
                relations[f"{kind}_permissions"] = {"available": False}
        resource = {"id": resource_id, "name": payload.get("name"), "kind": payload.get("type")}
    elif resource_type == "datasource":
        payload = client.data("GET", f"/datasource/hidePw/{resource_id}")
        if not isinstance(payload, dict):
            raise DataEaseError("数据源详情接口未返回对象", code="invalid_response", stage="transfer")
        resource = {"id": resource_id, "name": payload.get("name"), "kind": payload.get("type")}
        relations["credentials_required_on_restore"] = True
    else:
        raise DataEaseError("resource-type 必须是 visual、dataset 或 datasource", code="invalid_input", stage="input")
    relations["references"] = _references(payload)
    return redact_configuration({
        "schema": BUNDLE_SCHEMA,
        "created_at": int(time.time()),
        "source": {"base_url": client.settings.base_url, "org_id": client.settings.org_id or None,
                   "version": format_version(version), "adapter": adapter.name},
        "resource_type": resource_type,
        "resource": resource,
        "payload": payload,
        "relations": relations,
        "restore_notes": [
            "凭据字段不会写入可移植包，数据源恢复必须通过 overrides 重新提供。",
            "跨环境恢复需要在 id_map 中映射数据源、数据表、数据集和图表引用。",
            "联动摘要用于核对；组件内联动配置随画布迁移，服务端联动记录需在目标端复核。",
            "目标端必须预先具备画布使用的插件、字体、数据库驱动和外部静态资源。",
        ],
    })


def _write_bundle(bundle: dict[str, Any], output: str, force: bool) -> Path:
    path = Path(output).expanduser().resolve()
    if path.exists() and not force:
        raise DataEaseError("输出文件已存在；如需覆盖请使用 --force", code="file_exists", stage="transfer")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _load_bundle(path: str) -> dict[str, Any]:
    bundle = _load(path)
    if bundle.get("schema") != BUNDLE_SCHEMA or bundle.get("resource_type") not in {"visual", "dataset", "datasource"}:
        raise DataEaseError("不是受支持的 DataEase 可移植包", code="invalid_bundle", stage="transfer")
    if not isinstance(bundle.get("payload"), dict):
        raise DataEaseError("可移植包缺少 payload", code="invalid_bundle", stage="transfer")
    return bundle


def _replace_ids(value: Any, mapping: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _replace_ids(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_ids(item, mapping) for item in value]
    replacement = mapping.get(str(value))
    return replacement if replacement is not None else value


def _fresh_long_id(used: set[str]) -> str:
    while True:
        candidate = str(1_000_000_000_000_000_000 + uuid.uuid4().int % 8_000_000_000_000_000_000)
        if candidate not in used:
            used.add(candidate)
            return candidate


def _replace_visual_ids(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            str(mapping.get(str(key), key)): _replace_visual_ids(item, mapping)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_visual_ids(item, mapping) for item in value]
    return mapping.get(str(value), value)


def _replace_internal_ids(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            str(mapping.get(str(key), key)): _replace_internal_ids(item, mapping)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_internal_ids(item, mapping) for item in value]
    exact = mapping.get(str(value))
    if exact is not None:
        return exact
    if isinstance(value, str):
        for old, new in sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True):
            value = value.replace(old, new)
    return value


def _prepare_dataset_restore_payload(payload: dict[str, Any], old_group_id: str) \
        -> tuple[dict[str, Any], dict[str, str]]:
    table_ids: set[str] = set()
    field_ids: set[str] = set()

    def visit(nodes: Any) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            current = node.get("currentDs") or {}
            if isinstance(current, dict) and current.get("id") not in (None, ""):
                table_ids.add(str(current["id"]))
            for field in node.get("currentDsFields") or []:
                if isinstance(field, dict) and field.get("id") not in (None, ""):
                    field_ids.add(str(field["id"]))
            visit(node.get("childrenDs"))

    visit(payload.get("union"))
    for field in payload.get("allFields") or []:
        if not isinstance(field, dict):
            continue
        if field.get("id") not in (None, ""):
            field_ids.add(str(field["id"]))
        if field.get("datasetTableId") not in (None, ""):
            table_ids.add(str(field["datasetTableId"]))
    used = table_ids | field_ids | {old_group_id}
    internal_id_map = {
        old_id: _fresh_long_id(used)
        for old_id in sorted(table_ids | field_ids)
    }
    prepared = _replace_internal_ids(payload, internal_id_map)

    def remove_old_group(value: Any) -> None:
        if isinstance(value, dict):
            if str(value.get("datasetGroupId")) == old_group_id:
                value.pop("datasetGroupId", None)
            for item in value.values():
                remove_old_group(item)
        elif isinstance(value, list):
            for item in value:
                remove_old_group(item)

    remove_old_group(prepared)
    return prepared, internal_id_map


def _prepare_visual_restore_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    views = payload.get("canvasViewInfo") or {}
    if not isinstance(views, dict) or not views:
        raise DataEaseError("可移植大屏不包含图表视图", code="invalid_bundle", stage="transfer")
    components = payload.get("componentData") or []
    if isinstance(components, str):
        try:
            components = json.loads(components)
        except json.JSONDecodeError as exc:
            raise DataEaseError("大屏 componentData 无效", code="invalid_bundle", stage="transfer") from exc
    if not isinstance(components, list):
        raise DataEaseError("大屏 componentData 必须是数组", code="invalid_bundle", stage="transfer")
    used = {str(item) for item in views}
    view_id_map = {str(old_id): _fresh_long_id(used) for old_id in views}
    payload["canvasViewInfo"] = _replace_visual_ids(views, view_id_map)
    payload["componentData"] = json.dumps(
        _replace_visual_ids(components, view_id_map), ensure_ascii=False, separators=(",", ":")
    )
    return payload, view_id_map


def _linkage_pairs(value: Any) -> set[tuple[str, str, str, str]]:
    pairs: set[tuple[str, str, str, str]] = set()
    if not isinstance(value, dict):
        return pairs
    for source, targets in value.items():
        source_parts = str(source).split("#", 1)
        if len(source_parts) != 2 or not isinstance(targets, list):
            continue
        for target in targets:
            target_parts = str(target).split("#", 1)
            if len(target_parts) == 2:
                pairs.add((source_parts[0], source_parts[1], target_parts[0], target_parts[1]))
    return pairs


def _restore_visual_linkages(target: DataEaseClient, resource_id: str, source_summary: Any,
                             view_id_map: dict[str, str], id_map: dict[str, Any],
                             views: dict[str, Any], adapter: Any) -> int:
    source_pairs = _linkage_pairs(source_summary)
    if not source_pairs:
        return 0
    expected: set[tuple[str, str, str, str]] = set()
    by_source: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for old_source, old_source_field, old_target, old_target_field in source_pairs:
        if old_source not in view_id_map or old_target not in view_id_map:
            raise DataEaseError("联动引用了可移植包中不存在的图表", code="invalid_bundle", stage="transfer")
        source_id = view_id_map[old_source]
        target_id = view_id_map[old_target]
        source_field = str(id_map.get(old_source_field, old_source_field))
        target_field = str(id_map.get(old_target_field, old_target_field))
        by_source.setdefault(source_id, {}).setdefault(target_id, []).append(
            {"sourceField": source_field, "targetField": target_field}
        )
        expected.add((source_id, source_field, target_id, target_field))
    for source_id, targets in by_source.items():
        linkage_info: list[dict[str, Any]] = []
        for target_id, fields in targets.items():
            view = views.get(str(target_id)) or {}
            linkage_info.append({
                "targetViewId": target_id,
                "targetViewName": view.get("title") or str(target_id),
                "targetViewType": view.get("type"),
                "tableId": view.get("tableId"),
                "linkageActive": True,
                "linkageFields": fields,
                "targetViewFields": [],
            })
        target.data("POST", "/linkage/saveLinkage", {
            "dvId": resource_id,
            "sourceViewId": source_id,
            "resourceTable": "snapshot",
            "linkageInfo": linkage_info,
        })
        target.data("POST", "/linkage/updateLinkageActive", {
            "dvId": resource_id,
            "sourceViewId": source_id,
            "activeStatus": True,
            "resourceTable": "snapshot",
        })
    after = target.data("GET", adapter.linkage_all_path(resource_id, "snapshot"))
    actual = _linkage_pairs(after)
    if actual != expected:
        raise DataEaseError(
            "恢复后的联动关系回读不一致",
            code="verification_failed",
            stage="verification",
            details={"expected_count": len(expected), "actual_count": len(actual)},
        )
    return len(expected)


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


@contextlib.contextmanager
def _target_client(args: Any, current: DataEaseClient) -> Iterator[DataEaseClient]:
    if not args.target_env_file:
        yield current
        return
    settings = Settings.load(args.target_env_file)
    with DataEaseClient(settings) as target:
        if settings.org_id:
            target.ensure_organization(settings.org_id)
        yield target


def _restore_payload(target: DataEaseClient, bundle: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    resource_type = bundle["resource_type"]
    mapping = {str(key): value for key, value in (spec.get("id_map") or {}).items()}
    payload = _replace_ids(bundle["payload"], mapping)
    if not isinstance(payload, dict):
        raise DataEaseError("映射后的 payload 无效", code="invalid_bundle", stage="transfer")
    overrides = spec.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise DataEaseError("overrides 必须是对象", code="invalid_spec", stage="input")
    _deep_merge(payload, overrides)
    if spec.get("name"):
        payload["name"] = str(spec["name"])
    old_id = str(bundle.get("resource", {}).get("id") or "")
    payload.pop("id", None)
    payload["pid"] = str(spec.get("pid") or payload.get("pid") or "0")
    restore_details: dict[str, Any] = {}

    if resource_type == "visual":
        payload, view_id_map = _prepare_visual_restore_payload(payload)
        busi_type = str(spec.get("busi_type") or bundle.get("resource", {}).get("kind") or "dashboard")
        payload["type"] = busi_type
        payload["busiFlag"] = busi_type
        payload["contentId"] = str(uuid.uuid4())
        payload.pop("checkVersion", None)
        payload["status"] = 0
        response = target.data("POST", "/dataVisualization/saveCanvas", payload)
        resource_id = str(response.get("id") if isinstance(response, dict) else response)
        if not resource_id:
            raise DataEaseError("大屏恢复接口未返回 ID", code="invalid_response", stage="transfer")
        after, _, visual_adapter = _visual_detail(target, resource_id, busi_type)
        linkage_count = _restore_visual_linkages(
            target,
            resource_id,
            bundle.get("relations", {}).get("linkages"),
            view_id_map,
            mapping,
            payload["canvasViewInfo"],
            visual_adapter,
        )
        restore_details = {"view_id_map": view_id_map, "restored_linkage_fields": linkage_count}
    elif resource_type == "dataset":
        payload, internal_id_map = _prepare_dataset_restore_payload(payload, old_id)
        response = target.data("POST", "/datasetTree/create", payload)
        resource_id = str(response.get("id") if isinstance(response, dict) else response)
        if not resource_id:
            raise DataEaseError("数据集恢复接口未返回 ID", code="invalid_response", stage="transfer")
        after = _dataset_detail(target, resource_id)
        restored_permission_counts: dict[str, int] = {}
        for kind in ("row", "column"):
            source = bundle.get("relations", {}).get(f"{kind}_permissions")
            permission_mapping = {**{str(key): str(value) for key, value in mapping.items()},
                                  **internal_id_map, old_id: resource_id}
            source_permissions = _permission_records(_replace_internal_ids(source, permission_mapping))
            for permission in source_permissions:
                permission = dict(permission)
                permission.pop("id", None)
                permission["datasetId"] = resource_id
                target.data("POST", f"/dataset/{kind}Permissions/save", permission)
            restored = target.data("GET", f"/dataset/{kind}Permissions/pager/{resource_id}/1/1000")
            restored_count = len(_permission_records(restored))
            if restored_count != len(source_permissions):
                raise DataEaseError(
                    f"恢复后的{kind}权限数量不一致",
                    code="verification_failed",
                    stage="verification",
                    details={"expected_count": len(source_permissions), "actual_count": restored_count},
                )
            restored_permission_counts[kind] = restored_count
        restore_details = {"internal_id_map": internal_id_map,
                           "restored_permission_counts": restored_permission_counts}
    else:
        if "configuration" not in overrides:
            raise DataEaseError("数据源恢复必须在 overrides 提供完整 configuration（含目标环境凭据）",
                                code="credentials_required", stage="transfer")
        if isinstance(payload.get("configuration"), (dict, list)):
            raw_configuration = json.dumps(payload["configuration"], ensure_ascii=False,
                                           separators=(",", ":")).encode("utf-8")
            payload["configuration"] = base64.b64encode(raw_configuration).decode("ascii")
        response = target.data("POST", "/datasource/save", payload)
        resource_id = str(response.get("id") if isinstance(response, dict) else response)
        if not resource_id:
            raise DataEaseError("数据源恢复接口未返回 ID", code="invalid_response", stage="transfer")
        after = target.data("GET", f"/datasource/hidePw/{resource_id}")
    if str(after.get("name")) != str(payload.get("name")):
        raise DataEaseError("恢复后名称回读不一致", code="verification_failed", stage="verification")
    return {"id": resource_id, "name": after.get("name"), "type": resource_type,
            "old_id": old_id, "suggested_id_map": {old_id: resource_id}, **restore_details}


def handle_transfer_operation(args: Any, settings: Settings, client: DataEaseClient,
                              plans: PlanStore, audit: AuditLog) -> dict[str, Any]:
    key = f"transfer.{args.action}"
    if args.action in {"backup", "export"}:
        bundle = build_bundle(client, args.resource_type, args.resource_id, args.busi_type)
        path = _write_bundle(bundle, args.output, args.force)
        return _envelope(key, {"bundle": str(path), "sha256": _digest(bundle),
                               "resource": bundle["resource"], "source": bundle["source"]}, artifacts=[str(path)])
    if args.action == "inspect":
        bundle = _load_bundle(args.bundle)
        return _envelope(key, {"schema": bundle["schema"], "resource_type": bundle["resource_type"],
                               "resource": bundle["resource"], "source": bundle["source"],
                               "sha256": _digest(bundle), "restore_notes": bundle.get("restore_notes", [])})
    if args.action == "native-export":
        if not args.ack_sensitive_export:
            raise DataEaseError("原生导出可能包含业务明细；需要 --ack-sensitive-export",
                                code="sensitive_export_ack_required", stage="safety")
        version, adapter = adapter_for_client(client)
        adapter.require("dataset_export", version)
        detail = _dataset_detail(client, args.resource_id)
        payload = {"id": args.resource_id, "name": detail.get("name"),
                   "filename": args.filename or detail.get("name"), "expressionTree": "{\"items\":[],\"logic\":\"or\"}",
                   "dataEaseBi": True}
        path = Path(args.output).expanduser().resolve()
        if path.exists() and not args.force:
            raise DataEaseError("输出文件已存在；如需覆盖请使用 --force", code="file_exists", stage="transfer")
        export_spec = {"resource_id": str(args.resource_id), "name": detail.get("name"),
                       "filename": payload["filename"], "output": str(path), "force": bool(args.force)}
        if not args.apply:
            plan = plans.create(key, target={"id": str(args.resource_id), "name": detail.get("name"),
                                             "type": "dataset-data-export", "output": str(path)},
                                changes=[{"action": "export-business-data", "format": "xlsx"}], risk="L2",
                                spec={"export_sha256": _digest(export_spec), "precondition_sha256": _digest(detail)},
                                rollback={"strategy": "delete-local-export-file", "automatic": False},
                                context=_context(client))
            return _envelope(key, plan, mode="dry-run")
        if not args.plan_id:
            raise DataEaseError("执行原生数据导出需要 --plan-id", code="plan_required", stage="safety")
        plan = plans.load(args.plan_id, args.confirm_token, expected_context=_context(client))
        if plan.get("operation") != key or plan.get("spec", {}).get("export_sha256") != _digest(export_spec):
            raise DataEaseError("导出目标与 dry-run 不一致", code="spec_changed", stage="safety")
        if plan.get("spec", {}).get("precondition_sha256") != _digest(detail):
            raise DataEaseError("数据集模型已变化，请重新 dry-run", code="target_changed", stage="safety")
        response = client.request("POST", "/datasetTree/exportDataset", payload=payload, raw=True,
                                  timeout=max(client.settings.timeout, 180))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        result = {"file": str(path), "bytes": len(response.content)}
        audit_id = audit.write(key, status="success", risk="L2", target=plan.get("target"),
                               changes=plan.get("changes"), result=result)
        plans.mark_applied(args.plan_id, audit_id)
        return _envelope(key, result, mode="apply", artifacts=[str(path)], audit_id=audit_id)
    if args.action not in {"import", "restore", "migrate"}:
        raise DataEaseError("不支持的迁移操作", code="unsupported_operation", stage="dispatch")
    operation = {"import": "transfer.import", "restore": "transfer.restore", "migrate": "transfer.migrate"}[args.action]
    spec = _load(args.spec)
    bundle_path = str(spec.get("bundle") or "")
    if not bundle_path:
        raise DataEaseError("恢复配置必须包含 bundle", code="invalid_spec", stage="input")
    bundle = _load_bundle(bundle_path)
    with _target_client(args, client) as target:
        version, adapter = adapter_for_client(target)
        adapter.require("json_backup_restore", version, mutation=True, client=target)
        context = _context(target)
        target_info = {"base_url": target.settings.base_url, "org_id": target.settings.org_id or None,
                       "resource_type": bundle["resource_type"], "source_id": bundle["resource"]["id"],
                       "name": spec.get("name") or bundle["resource"].get("name")}
        if not args.apply:
            plan = plans.create(operation, target=target_info,
                                changes=[{"action": "cross-instance-migrate" if args.action == "migrate" else "restore",
                                          "resource_type": bundle["resource_type"]}], risk="L3",
                                spec={"payload_sha256": _digest(spec), "bundle_sha256": _digest(bundle)},
                                rollback={"strategy": "delete-created-resource", "automatic": False}, context=context)
            return _envelope(operation, plan, mode="dry-run")
        if not args.plan_id:
            raise DataEaseError("执行恢复需要 --plan-id", code="plan_required", stage="safety")
        plan = plans.load(args.plan_id, args.confirm_token, expected_context=context)
        if plan.get("operation") != operation or plan.get("spec", {}).get("payload_sha256") != _digest(spec) \
                or plan.get("spec", {}).get("bundle_sha256") != _digest(bundle):
            raise DataEaseError("恢复配置或可移植包已变化", code="spec_changed", stage="safety")
        result = _restore_payload(target, bundle, spec)
        audit_id = audit.write(operation, status="success", risk="L3", target=plan.get("target"),
                               changes=plan.get("changes"), result=result)
        plans.mark_applied(args.plan_id, audit_id)
        return _envelope(operation, result, mode="apply", adapter=adapter.name, audit_id=audit_id)
