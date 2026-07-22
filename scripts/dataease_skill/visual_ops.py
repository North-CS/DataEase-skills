from __future__ import annotations

import copy
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .audit import AuditLog
from .client import DataEaseClient
from .config import Settings
from .errors import DataEaseError
from .field_binding import FIELD_METADATA_KEYS
from .redact import redact_configuration
from .safety import PlanStore
from .versioning import adapter_for_client


COMPONENT_PATCH_KEYS = {
    "x", "y", "sizeX", "sizeY", "name", "label", "style", "matrixStyle",
    "commonBackground", "isShow", "dashboardHidden", "linkage", "linkageFilters",
    "events", "actionSelection", "carousel", "propValue",
}
VIEW_PATCH_KEYS = {
    "title", "tableId", "type", "render", "resultMode", "resultCount", "customAttr",
    "customStyle", "customFilter", "filters", "filter", "linkage", "drillFields",
    "chartExtRequest", "xAxis", "xAxisExt", "yAxis", "yAxisExt", "extBubble",
    "extLabel", "extStack", "extTooltip", "extColor", "misc",
}
AXES = {"xAxis", "xAxisExt", "yAxis", "yAxisExt", "extBubble", "extLabel", "extStack", "extTooltip", "extColor"}


def _envelope(operation: str, result: Any, **extra: Any) -> dict[str, Any]:
    return {"schema_version": 1, "ok": True, "operation": operation, "result": result,
            "warnings": extra.pop("warnings", []), **extra}


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
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _context(client: DataEaseClient) -> dict[str, Any]:
    version = client.data("GET", "/license/version")
    return {"base_url": client.settings.base_url, "api_prefix": client.settings.api_prefix,
            "org_id": client.settings.org_id or None, "version": version}


def _detail(client: DataEaseClient, resource_id: str, busi_type: str, *, mutation: bool = False) -> dict[str, Any]:
    version, adapter = adapter_for_client(client)
    adapter.require("visual_component_edit", version, mutation=mutation, client=client)
    return adapter.visual_detail(client, str(resource_id), busi_type, version)


def _decode_json(value: Any, field: str, fallback: Any) -> Any:
    if value in (None, ""):
        return copy.deepcopy(fallback)
    if not isinstance(value, str):
        return copy.deepcopy(value)
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise DataEaseError(f"{field} 不是有效 JSON", code="invalid_visual_payload", stage="visualization") from exc


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _select(items: list[dict[str, Any]], resource_id: Any, kind: str) -> dict[str, Any]:
    matches = [item for item in items if str(item.get("id")) == str(resource_id)]
    if len(matches) != 1:
        raise DataEaseError(f"找不到唯一的{kind}: {resource_id}", code="resource_not_found", stage="visualization")
    return matches[0]


def _dataset_fields(client: DataEaseClient, dataset_id: str) -> list[dict[str, Any]]:
    value: Any = None
    try:
        value = client.data("GET", f"/datasetTree/details/{dataset_id}")
    except DataEaseError:
        value = client.data("POST", f"/datasetTree/details/{dataset_id}", {})
    fields = value.get("allFields") if isinstance(value, dict) else None
    if not isinstance(fields, list) or not fields:
        fields = client.data("POST", f"/datasetField/listByDatasetGroup/{dataset_id}", {})
    if not isinstance(fields, list):
        raise DataEaseError("目标数据集没有可用字段", code="empty_dataset", stage="dataset")
    return fields


def _replace_field(client: DataEaseClient, views: dict[str, Any], operation: dict[str, Any]) -> None:
    view_id = str(operation.get("view_id") or "")
    axis = str(operation.get("axis") or "")
    index = operation.get("index", 0)
    dataset_id = str(operation.get("dataset_id") or "")
    field_selector = str(operation.get("field_id") or operation.get("field_name") or "")
    if not view_id or axis not in AXES or not isinstance(index, int) or index < 0 or not dataset_id or not field_selector:
        raise DataEaseError("field_replacements 需要 view_id、合法 axis/index、dataset_id 和 field_id/field_name",
                            code="invalid_spec", stage="input")
    view = views.get(view_id)
    if not isinstance(view, dict):
        raise DataEaseError(f"找不到图表视图: {view_id}", code="resource_not_found", stage="visualization")
    axis_fields = view.get(axis)
    if not isinstance(axis_fields, list) or index >= len(axis_fields):
        raise DataEaseError(f"视图 {view_id} 的 {axis}[{index}] 不存在", code="invalid_spec", stage="input")
    current_dataset = view.get("tableId")
    if current_dataset is not None and str(current_dataset) != dataset_id:
        raise DataEaseError(
            "field_replacements 只允许同数据集换字段；跨数据集重绑必须通过 view_updates 一次提交完整 tableId 和所有轴字段",
            code="cross_dataset_view_binding",
            stage="visualization",
            details={"view_id": view_id, "current_dataset_id": str(current_dataset),
                     "target_dataset_id": dataset_id},
        )
    fields = _dataset_fields(client, dataset_id)
    matches = [item for item in fields if str(item.get("id")) == field_selector]
    if not matches:
        matches = [item for item in fields if str(item.get("name") or item.get("originName")) == field_selector]
    if len(matches) != 1:
        raise DataEaseError(f"字段选择不唯一或不存在: {field_selector}", code="field_not_found", stage="dataset")
    old = axis_fields[index]
    replacement = copy.deepcopy(old if isinstance(old, dict) else {})
    field = matches[0]
    for key in FIELD_METADATA_KEYS:
        if key in field:
            replacement[key] = copy.deepcopy(field[key])
    replacement["datasetGroupId"] = str(dataset_id)
    if replacement.get("dataeaseName"):
        replacement["fieldShortName"] = replacement["dataeaseName"]
    if "seriesId" in replacement:
        replacement["seriesId"] = f"{replacement.get('id')}-{axis}"
    if operation.get("aggregation"):
        replacement["summary"] = str(operation["aggregation"])
    axis_fields[index] = replacement
    view["tableId"] = str(dataset_id)


def patch_visual_payload(client: DataEaseClient, detail: dict[str, Any], spec: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = copy.deepcopy(detail)
    components = _decode_json(payload.get("componentData"), "componentData", [])
    canvas_style = _decode_json(payload.get("canvasStyleData"), "canvasStyleData", {})
    views = copy.deepcopy(payload.get("canvasViewInfo") or {})
    if not isinstance(components, list) or not isinstance(canvas_style, dict) or not isinstance(views, dict):
        raise DataEaseError("可视化资源结构不受支持", code="invalid_visual_payload", stage="visualization")
    changes: list[dict[str, Any]] = []

    for item in spec.get("component_updates", []):
        if not isinstance(item, dict) or not item.get("id") or not isinstance(item.get("patch"), dict):
            raise DataEaseError("component_updates 每项需要 id 和 patch", code="invalid_spec", stage="input")
        unknown = sorted(set(item["patch"]) - COMPONENT_PATCH_KEYS)
        if unknown:
            raise DataEaseError("组件补丁包含未允许字段", code="unsafe_patch", stage="safety", details={"fields": unknown})
        component = _select(components, item["id"], "组件")
        _deep_merge(component, item["patch"])
        changes.append({"action": "patch-component", "id": str(item["id"]), "fields": sorted(item["patch"])})

    for item in spec.get("view_updates", []):
        if not isinstance(item, dict) or not item.get("id") or not isinstance(item.get("patch"), dict):
            raise DataEaseError("view_updates 每项需要 id 和 patch", code="invalid_spec", stage="input")
        unknown = sorted(set(item["patch"]) - VIEW_PATCH_KEYS)
        if unknown:
            raise DataEaseError("视图补丁包含未允许字段", code="unsafe_patch", stage="safety", details={"fields": unknown})
        view = views.get(str(item["id"]))
        if not isinstance(view, dict):
            raise DataEaseError(f"找不到图表视图: {item['id']}", code="resource_not_found", stage="visualization")
        _deep_merge(view, item["patch"])
        changes.append({"action": "patch-view", "id": str(item["id"]), "fields": sorted(item["patch"])})

    for item in spec.get("field_replacements", []):
        if not isinstance(item, dict):
            raise DataEaseError("field_replacements 每项必须是对象", code="invalid_spec", stage="input")
        _replace_field(client, views, item)
        changes.append({"action": "replace-field", "view_id": str(item.get("view_id")),
                        "axis": item.get("axis"), "index": item.get("index", 0),
                        "dataset_id": str(item.get("dataset_id")), "field": item.get("field_id") or item.get("field_name")})

    theme = spec.get("theme")
    if theme is not None:
        if not isinstance(theme, dict):
            raise DataEaseError("theme 必须是 CanvasStyleData 合并补丁对象", code="invalid_spec", stage="input")
        _deep_merge(canvas_style, theme)
        changes.append({"action": "patch-theme", "fields": sorted(theme)})

    if not changes:
        raise DataEaseError("配置没有可执行的组件、视图、字段或主题变更", code="empty_change", stage="input")
    payload["componentData"] = json.dumps(components, ensure_ascii=False, separators=(",", ":"))
    payload["canvasStyleData"] = json.dumps(canvas_style, ensure_ascii=False, separators=(",", ":"))
    payload["canvasViewInfo"] = views
    payload["contentId"] = str(uuid.uuid4())
    payload["watermarkInfo"] = None
    return payload, changes


def _empty_patch_value(value: Any) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, list):
        return not value
    if isinstance(value, dict):
        return not value or all(_empty_patch_value(item) for item in value.values())
    return False


def _patch_matches(actual: Any, patch: Any, path: str, errors: list[str]) -> None:
    if isinstance(patch, dict):
        if not isinstance(actual, dict):
            errors.append(path)
            return
        for key, value in patch.items():
            child = f"{path}.{key}" if path else key
            if value is None:
                if key in actual:
                    errors.append(child)
            elif key not in actual:
                if not _empty_patch_value(value):
                    errors.append(child)
            else:
                _patch_matches(actual[key], value, child, errors)
        return
    if _empty_patch_value(patch) and _empty_patch_value(actual):
        return
    if actual != patch:
        errors.append(path)


def verify_visual_patch(after: dict[str, Any], expected: dict[str, Any], spec: dict[str, Any],
                        before_digest: str) -> dict[str, Any]:
    """Verify requested effects while tolerating DataEase's server-side DTO normalization."""
    components = _decode_json(after.get("componentData"), "componentData", [])
    canvas_style = _decode_json(after.get("canvasStyleData"), "canvasStyleData", {})
    views = after.get("canvasViewInfo") or {}
    expected_views = expected.get("canvasViewInfo") or {}
    if not isinstance(components, list) or not isinstance(canvas_style, dict) or not isinstance(views, dict):
        raise DataEaseError("组件修改后画布结构无效", code="verification_failed", stage="verification")
    errors: list[str] = []
    for item in spec.get("component_updates", []):
        component = _select(components, item["id"], "组件")
        _patch_matches(component, item["patch"], f"component[{item['id']}]", errors)
    for item in spec.get("view_updates", []):
        view = views.get(str(item["id"]))
        if not isinstance(view, dict):
            errors.append(f"view[{item['id']}]")
            continue
        _patch_matches(view, item["patch"], f"view[{item['id']}]", errors)
    for item in spec.get("field_replacements", []):
        view_id = str(item["view_id"])
        axis = str(item["axis"])
        index = int(item.get("index", 0))
        view = views.get(view_id)
        expected_view = expected_views.get(view_id)
        if not isinstance(view, dict) or not isinstance(expected_view, dict):
            errors.append(f"view[{view_id}]")
            continue
        actual_axis = view.get(axis)
        expected_axis = expected_view.get(axis)
        if not isinstance(actual_axis, list) or not isinstance(expected_axis, list) \
                or index >= len(actual_axis) or index >= len(expected_axis):
            errors.append(f"view[{view_id}].{axis}[{index}]")
            continue
        actual_field, expected_field = actual_axis[index], expected_axis[index]
        if not isinstance(actual_field, dict) or not isinstance(expected_field, dict):
            errors.append(f"view[{view_id}].{axis}[{index}]")
            continue
        for key in ("id", "name", "originName", "dataeaseName", "summary"):
            if key in expected_field and str(actual_field.get(key)) != str(expected_field.get(key)):
                errors.append(f"view[{view_id}].{axis}[{index}].{key}")
        if str(view.get("tableId")) != str(item["dataset_id"]):
            errors.append(f"view[{view_id}].tableId")
    if spec.get("theme") is not None:
        _patch_matches(canvas_style, spec["theme"], "theme", errors)
    actual_canvas = {key: after.get(key) for key in ("componentData", "canvasStyleData", "canvasViewInfo")}
    actual_digest = _digest(actual_canvas)
    if actual_digest == before_digest:
        errors.append("canvas.unchanged")
    if errors:
        raise DataEaseError(
            "组件修改后请求的效果未完整回读",
            code="verification_failed",
            stage="verification",
            details={"mismatches": errors[:20]},
        )
    expected_digest = _digest({key: expected.get(key) for key in (
        "componentData", "canvasStyleData", "canvasViewInfo"
    )})
    return {"canvas_sha256": actual_digest, "server_normalized": actual_digest != expected_digest}


def inspect_visual(client: DataEaseClient, resource_id: str, busi_type: str) -> dict[str, Any]:
    detail = _detail(client, resource_id, busi_type)
    components = _decode_json(detail.get("componentData"), "componentData", [])
    views = detail.get("canvasViewInfo") or {}
    version, adapter = adapter_for_client(client)
    linkages: Any = []
    try:
        linkages = client.data("GET", adapter.linkage_all_path(resource_id, "snapshot"))
    except DataEaseError:
        linkages = {"available": False, "reason": "当前账号或版本无法读取联动配置"}
    component_summary = []
    for item in components if isinstance(components, list) else []:
        if not isinstance(item, dict):
            continue
        style = item.get("style") if isinstance(item.get("style"), dict) else {}
        component_summary.append({key: value for key, value in {
            "id": str(item.get("id")), "component": item.get("component"), "name": item.get("name"),
            "x": item.get("x"), "y": item.get("y"), "sizeX": item.get("sizeX"), "sizeY": item.get("sizeY"),
            "left": style.get("left"), "top": style.get("top"), "width": style.get("width"),
            "height": style.get("height"), "visible": item.get("isShow", not item.get("dashboardHidden", False)),
        }.items() if value is not None})
    view_summary = []
    for view_id, view in views.items() if isinstance(views, dict) else []:
        if not isinstance(view, dict):
            continue
        view_summary.append({"id": str(view_id), "title": view.get("title"), "type": view.get("type"),
                             "dataset_id": str(view.get("tableId")) if view.get("tableId") is not None else None,
                             "fields": {axis: [{"id": str(field.get("id")), "name": field.get("name"),
                                                "summary": field.get("summary")} for field in view.get(axis, [])
                                                if isinstance(field, dict)] for axis in AXES if isinstance(view.get(axis), list)}})
    return {"resource": {key: detail.get(key) for key in ("id", "name", "type", "status", "pid")},
            "adapter": adapter.public_info(version), "components": component_summary,
            "views": view_summary, "linkages": linkages}


def _snapshot(settings: Settings, resource_id: str, detail: dict[str, Any]) -> str:
    directory = settings.output_dir / "snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"visual-{resource_id}-{int(time.time())}.json"
    path.write_text(json.dumps(redact_configuration(detail), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def _handle_linkage(args: Any, settings: Settings, client: DataEaseClient,
                    plans: PlanStore, audit: AuditLog) -> dict[str, Any]:
    operation = "visual.linkage"
    spec = _load_spec(args.spec)
    resource_id = str(spec.get("resource_id") or args.resource_id or "")
    busi_type = str(spec.get("busi_type") or args.busi_type or "dashboard")
    linkage_action = str(spec.get("action") or "")
    payload = spec.get("payload")
    endpoints = {
        "save": "/linkage/saveLinkage",
        "remove": "/linkage/removeLinkage",
        "update-active": "/linkage/updateLinkageActive",
    }
    if not resource_id or busi_type not in {"dashboard", "dataV"} or linkage_action not in endpoints \
            or not isinstance(payload, dict):
        raise DataEaseError("联动配置需要 resource_id、busi_type、action(save/remove/update-active) 和 payload",
                            code="invalid_spec", stage="input")
    detail = _detail(client, resource_id, busi_type, mutation=True)
    if spec.get("name") and str(detail.get("name")) != str(spec["name"]):
        raise DataEaseError("name 与目标资源不一致", code="target_mismatch", stage="safety")
    version, adapter = adapter_for_client(client)
    current = client.data("GET", adapter.linkage_all_path(resource_id, "snapshot"))
    if not args.apply:
        snapshot = _snapshot(settings, f"{resource_id}-linkage", {"detail": detail, "linkages": current})
        plan = plans.create(operation, target={"id": resource_id, "name": detail.get("name"), "type": busi_type},
                            changes=[{"action": f"linkage-{linkage_action}"}], risk="L2",
                            spec={"payload_sha256": _digest(spec), "precondition_sha256": _digest(current),
                                  "snapshot": snapshot},
                            rollback={"available": False,
                                      "reason": "联动摘要接口不返回完整 DTO，快照仅供人工恢复", "snapshot": snapshot},
                            context=_context(client))
        return _envelope(operation, plan, mode="dry-run", artifacts=[snapshot])
    if not args.plan_id:
        raise DataEaseError("执行联动修改需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_context(client))
    stored = plan.get("spec", {})
    if plan.get("operation") != operation or stored.get("payload_sha256") != _digest(spec):
        raise DataEaseError("apply 配置与 dry-run 不一致", code="spec_changed", stage="safety")
    if stored.get("precondition_sha256") != _digest(current):
        raise DataEaseError("联动配置已变化，请重新 dry-run", code="target_changed", stage="safety")
    response = client.data("POST", endpoints[linkage_action], payload)
    after = client.data("GET", adapter.linkage_all_path(resource_id, "snapshot"))
    result = {"id": resource_id, "action": linkage_action, "before_sha256": _digest(current),
              "after_sha256": _digest(after), "response": response}
    audit_id = audit.write(operation, status="success", risk="L2", target=plan.get("target"),
                           changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter=adapter.name, audit_id=audit_id,
                     artifacts=[stored.get("snapshot")],
                     warnings=[] if current != after else ["接口已成功返回，但联动摘要没有变化；可能是幂等操作，请通过 visual inspect 复核。"])


def handle_visual_operation(args: Any, settings: Settings, client: DataEaseClient,
                            plans: PlanStore, audit: AuditLog) -> dict[str, Any]:
    if args.action == "inspect":
        return _envelope("visual.inspect", inspect_visual(client, args.resource_id, args.busi_type))
    if args.action == "linkage":
        return _handle_linkage(args, settings, client, plans, audit)
    operation = "visual.patch"
    spec = _load_spec(args.spec)
    resource_id = str(spec.get("resource_id") or args.resource_id or "")
    busi_type = str(spec.get("busi_type") or args.busi_type or "dashboard")
    if not resource_id or busi_type not in {"dashboard", "dataV"}:
        raise DataEaseError("需要 resource_id 且 busi_type 必须为 dashboard/dataV", code="invalid_spec", stage="input")
    detail = _detail(client, resource_id, busi_type, mutation=True)
    if spec.get("name") and str(detail.get("name")) != str(spec["name"]):
        raise DataEaseError("name 与目标资源不一致", code="target_mismatch", stage="safety")
    patched, changes = patch_visual_payload(client, detail, spec)
    before_digest = _digest(detail)
    after_digest = _digest({key: patched.get(key) for key in ("componentData", "canvasStyleData", "canvasViewInfo")})
    if not args.apply:
        snapshot = _snapshot(settings, resource_id, detail)
        plan = plans.create(operation, target={"id": resource_id, "name": detail.get("name"), "type": busi_type},
                            changes=changes, risk="L2",
                            spec={"payload_sha256": _digest(spec), "precondition_sha256": before_digest,
                                  "expected_canvas_sha256": after_digest, "snapshot": snapshot},
                            rollback={"strategy": "restore-updateCanvas", "snapshot": snapshot, "automatic": False},
                            context=_context(client))
        return _envelope(operation, plan, mode="dry-run", changes=changes, artifacts=[snapshot])
    if not args.plan_id:
        raise DataEaseError("执行组件修改需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_context(client))
    stored = plan.get("spec", {})
    if plan.get("operation") != operation or stored.get("payload_sha256") != _digest(spec):
        raise DataEaseError("apply 配置与 dry-run 不一致", code="spec_changed", stage="safety")
    if stored.get("precondition_sha256") != before_digest:
        raise DataEaseError("目标大屏已变化，请重新 dry-run", code="target_changed", stage="safety")
    client.data("POST", "/dataVisualization/updateCanvas", patched)
    after = _detail(client, resource_id, busi_type)
    verification = verify_visual_patch(after, patched, spec, before_digest)
    result = {"id": resource_id, "name": after.get("name"), "type": busi_type,
              **verification, "snapshot": stored.get("snapshot")}
    audit_id = audit.write(operation, status="success", risk="L2", target=plan.get("target"),
                           changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id,
                     artifacts=[stored.get("snapshot")])
