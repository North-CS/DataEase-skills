from __future__ import annotations

import copy
from urllib.parse import urlsplit
import re
from typing import Any


_CASCADE_HIERARCHIES = {
    "geography": (
        ("国家", "country"),
        ("大区", "区域", "region", "salesregion"),
        ("省级行政区", "省份", "省", "province", "state"),
        ("地级市", "城市", "市", "city"),
        ("区县", "县", "区", "district", "county"),
    ),
    "product": (
        ("商品大类", "产品大类", "一级品类", "category"),
        ("商品中类", "产品中类", "二级品类", "subcategory"),
        ("商品小类", "产品小类", "三级品类"),
        ("商品", "产品", "sku", "product"),
    ),
    "organization": (
        ("集团", "company", "group"),
        ("事业部", "businessunit", "division"),
        ("部门", "department"),
        ("团队", "小组", "team"),
        ("员工", "人员", "employee"),
    ),
}


def _semantic_key(value: Any) -> str:
    return re.sub(r"[\s_\-/]+", "", str(value or "")).lower()


def query_style_for_background(background: str, accent: str = "#3370FF") -> dict[str, Any]:
    """Return a complete native VQuery style with WCAG-aware foreground contrast."""
    match = re.search(
        r"#([0-9a-fA-F]{6})|rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)",
        str(background or ""),
    )
    if match and match.group(1):
        red, green, blue = (
            int(match.group(1)[position:position + 2], 16) for position in (0, 2, 4)
        )
    elif match:
        red, green, blue = (int(match.group(position)) for position in (2, 3, 4))
    else:
        red, green, blue = (255, 255, 255)
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    dark = luminance < 0.46
    text = "#EAF7FF" if dark else "#1F2329"
    muted = "#B8D5E6" if dark else "#646A73"
    input_background = "rgba(7,26,61,0.82)" if dark else "#FFFFFF"
    border = "rgba(120,210,255,0.55)" if dark else "#D9DCDF"
    return {
        "borderColor": border,
        "btnList": ["sure"],
        "titleLayout": "left",
        "labelColor": text,
        "text": muted,
        "bgColor": input_background,
        "layout": "horizontal",
        "titleShow": False,
        "titleColor": text,
        "title": "",
        "fontSize": "14",
        "fontWeight": "",
        "fontStyle": "",
        "fontSizeBtn": "14",
        "fontWeightBtn": "",
        "fontStyleBtn": "",
        "queryConditionWidth": 272,
        "nameboxSpacing": 8,
        "queryConditionSpacing": 16,
        "queryConditionHeight": 32,
        "labelColorBtn": "#FFFFFF",
        "btnColor": accent,
        "placeholderSize": 14,
        "placeholderShow": True,
        "labelShow": True,
        "color": text,
    }


def infer_filter_cascades(filters: list[str]) -> list[list[str]]:
    """Infer unambiguous hierarchy chains without depending on source-field order."""
    positions: list[tuple[str, str, int] | None] = []
    for field in filters:
        key = _semantic_key(field)
        matches: list[tuple[str, int]] = []
        for family, levels in _CASCADE_HIERARCHIES.items():
            for rank, aliases in enumerate(levels):
                if key in {_semantic_key(alias) for alias in aliases}:
                    matches.append((family, rank))
        positions.append((field, *matches[0]) if len(matches) == 1 else None)

    by_family: dict[str, list[tuple[int, str]]] = {}
    for position in positions:
        if position is None:
            continue
        field, family, rank = position
        by_family.setdefault(family, []).append((rank, field))

    cascades: list[list[str]] = []
    for matched in by_family.values():
        ranks = [rank for rank, _ in matched]
        if len(matched) < 2 or len(set(ranks)) != len(ranks):
            continue
        cascades.append([field for _, field in sorted(matched)])
    return cascades


def build_native_cascades(
    conditions: list[dict[str, Any]],
    cascade_chains: list[list[str]] | str | None,
) -> list[list[dict[str, Any]]]:
    """Build DataEase VQuery cascade DTOs from the component's current conditions."""
    if cascade_chains in (None, "auto"):
        cascade_chains = infer_filter_cascades([
            str(item.get("name") or "") for item in conditions
        ])
    if not isinstance(cascade_chains, list):
        raise ValueError("cascade chains must be a list or 'auto'")

    by_name: dict[str, list[dict[str, Any]]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for condition in conditions:
        by_name.setdefault(str(condition.get("name") or ""), []).append(condition)
        by_id[str(condition.get("id") or "")] = condition

    cascades: list[list[dict[str, Any]]] = []
    for chain_index, chain in enumerate(cascade_chains):
        if not isinstance(chain, list) or len(chain) < 2:
            raise ValueError("each cascade chain must contain at least two conditions")
        resolved: list[dict[str, Any]] = []
        for selector in chain:
            selector_text = str(selector)
            condition = by_id.get(selector_text)
            if condition is None:
                matches = by_name.get(selector_text, [])
                if len(matches) != 1:
                    raise ValueError(f"cascade condition is missing or ambiguous: {selector_text}")
                condition = matches[0]
            resolved.append(condition)
        if len({str(item.get("id")) for item in resolved}) != len(resolved):
            raise ValueError("cascade chain contains duplicate conditions")

        dataset_ids = {
            str((item.get("dataset") or {}).get("id") or "") for item in resolved
        }
        if "" in dataset_ids or len(dataset_ids) != 1:
            raise ValueError("automatic cascades require all conditions to use one dataset")
        dataset_id = next(iter(dataset_ids))
        native_chain: list[dict[str, Any]] = []
        for position, condition in enumerate(resolved):
            field = condition.get("field") if isinstance(condition.get("field"), dict) else {}
            field_id = str(field.get("id") or condition.get("displayId") or "")
            condition_id = str(condition.get("id") or "")
            if not field_id or not condition_id:
                raise ValueError("cascade condition lacks an authoritative condition or field id")
            native_chain.append({
                "datasetId": f"{dataset_id}--{condition_id}--{field_id}",
                "fieldId": "",
                "placeholder": "第一个条件" if position == 0 else "需上一个使用同一数据集的条件",
                "id": f"{condition_id}-cascade-{chain_index + 1}-{position + 1}",
                "selectValue": [],
                "defaultValueFirstItem": False,
                "currentSelectValue": [],
            })
        cascades.append(native_chain)
    return cascades


def normalize_interactions(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "filters": [], "filter_cascades": [], "auto_linkage": False,
            "drill_hierarchies": [], "jumps": [],
        }
    filters = value.get("filters") or []
    normalized_filters = [
        str(item) for item in filters
        if isinstance(item, (str, int)) and str(item).strip()
    ][:4]
    cascade_value = value.get("filter_cascades", value.get("cascades", "auto"))
    if cascade_value in (None, True, "auto"):
        filter_cascades = infer_filter_cascades(normalized_filters)
    elif cascade_value is False:
        filter_cascades = []
    else:
        filter_cascades = []
        if isinstance(cascade_value, list):
            for chain in cascade_value:
                if not isinstance(chain, list):
                    continue
                normalized_chain = [str(item) for item in chain if str(item) in normalized_filters]
                if len(normalized_chain) >= 2 and len(set(normalized_chain)) == len(normalized_chain):
                    filter_cascades.append(normalized_chain)
    drill_rules = value.get("drill_hierarchies") if isinstance(value.get("drill_hierarchies"), list) else []
    raw_jump_rules = value.get("jumps") if isinstance(value.get("jumps"), list) else []
    jump_rules = []
    seen_jump_sources: set[str] = set()
    for rule in raw_jump_rules:
        normalized = normalize_jump_rule(rule, require_source=True)
        source = normalized["source"]
        if source in seen_jump_sources:
            raise ValueError(f"duplicate jump rule for chart: {source}")
        seen_jump_sources.add(source)
        jump_rules.append(normalized)
    normalized_drills = []
    for rule in drill_rules:
        if isinstance(rule, dict):
            normalized = dict(rule)
            if not normalized.get("source") and normalized.get("chart"):
                normalized["source"] = normalized["chart"]
            normalized_drills.append(normalized)
    return {
        "filters": normalized_filters,
        "filter_cascades": filter_cascades,
        "auto_linkage": bool(value.get("auto_linkage", value.get("linkage", False))),
        "drill_hierarchies": normalized_drills,
        "jumps": jump_rules,
    }


def normalize_jump_rule(value: Any, *, require_source: bool = False) -> dict[str, str]:
    """Validate the native URL-event contract before a canvas is saved."""
    if not isinstance(value, dict):
        raise ValueError("jump rule must be an object")
    source = str(value.get("source") or value.get("chart") or "").strip()
    if require_source and not source:
        raise ValueError("jump rule requires source (or chart)")
    url = str(value.get("url") or "").strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("jump url must be an absolute http(s) URL")
    target = str(value.get("target") or "_blank").strip()
    if target not in {"_blank", "_self"}:
        raise ValueError("jump target must be _blank or _self")
    return {"source": source, "url": url, "target": target}


def apply_jump_event(component: dict[str, Any], view: dict[str, Any], jump: dict[str, Any]) -> None:
    """Write a complete, version-stable event envelope for a chart URL jump."""
    normalized = normalize_jump_rule(jump)
    events = component.setdefault("events", {})
    events.setdefault("showTips", False)
    events["checked"] = True
    events["type"] = "jump"
    events.setdefault("typeList", [
        {"key": key, "label": key}
        for key in ("jump", "download", "share", "fullScreen", "showHidden", "refreshDataV", "refreshView")
    ])
    events["jump"] = {"value": normalized["url"], "type": normalized["target"]}
    view["jumpActive"] = True


def build_query_component(
    component_id: str,
    dataset_id: str,
    filter_fields: list[dict[str, Any]],
    target_view_ids: list[str],
    *,
    canvas_width: int,
    canvas_height: int,
    dataset_fields: list[dict[str, Any]] | None = None,
    cascade_chains: list[list[str]] | None = None,
    background_color: str = "#FFFFFF",
    accent_color: str = "#3370FF",
) -> tuple[dict[str, Any], dict[str, Any]]:
    available_fields = copy.deepcopy(dataset_fields or filter_fields)
    conditions: list[dict[str, Any]] = []
    for index, field in enumerate(filter_fields):
        field_id = str(field["id"])
        checked_map = {view_id: field_id for view_id in target_view_ids}
        conditions.append({
            "id": f"{component_id}{index + 1}",
            "name": str(field.get("name") or field.get("originName") or field_id),
            "showError": False,
            "field": {"id": field_id, "type": field.get("type"), "name": field.get("name"), "deType": field.get("deType")},
            "displayId": field_id,
            "sortId": field_id,
            "sort": "asc",
            "conditionType": 0,
            "conditionValueOperatorF": "eq",
            "conditionValueF": "",
            "conditionValueOperatorS": "like",
            "conditionValueS": "",
            "defaultMapValue": [],
            "mapValue": [],
            "defaultValue": None,
            "selectValue": None,
            "optionValueSource": 1,
            "valueSource": [],
            "dataset": {"id": dataset_id, "name": "", "fields": copy.deepcopy(available_fields)},
            "visible": True,
            "multiple": False,
            "displayType": "7" if int(field.get("deType") or 0) == 1 else "0",
            "checkedFields": target_view_ids,
            "checkedFieldsMap": checked_map,
            "parameters": [],
            "parametersCheck": False,
            "required": False,
            "auto": False,
            "cascade": None,
        })
    cascades = build_native_cascades(conditions, cascade_chains or [])

    query_style = query_style_for_background(background_color, accent_color)
    dark_query = str(query_style["labelColor"]).upper() == "#EAF7FF"
    component = {
        "component": "VQuery", "name": "智能查询", "label": "智能查询",
        "propValue": conditions, "icon": "icon_search", "innerType": "VQuery",
        "category": "base", "isShow": True, "dashboardHidden": False,
        "dragging": False, "resizing": False,
        "isHang": False, "freeze": False, "x": 1, "y": 1, "sizeX": 72, "sizeY": 4,
        "style": {"rotate": 0, "opacity": 1, "borderActive": False, "borderWidth": 1,
                  "borderRadius": 5, "borderStyle": "solid", "borderColor": "#cccccc",
                  "adaptation": "adaptation",
                  "width": canvas_width, "height": round(canvas_height * 4 / 36),
                  "left": 0, "top": 0},
        "matrixStyle": {},
        "commonBackground": {
            "backgroundColorSelect": True,
            "backdropFilterEnable": False,
            "backgroundImageEnable": False,
            "backgroundType": "innerImage",
            "innerImage": "board/board_1.svg",
            "outerImage": None,
            "innerPadding": {"mode": "uniform", "top": 12},
            "borderRadius": {"mode": "uniform", "topLeft": 0},
            "backdropFilter": 4,
            "backgroundColor": "rgba(3,12,29,0.62)" if dark_query else "rgba(255,255,255,0.92)",
            "innerImageColor": accent_color,
        },
        "events": {
            "checked": False,
            "showTips": False,
            "type": "jump",
            "typeList": [
                {"key": key, "label": key}
                for key in (
                    "jump", "download", "share", "fullScreen",
                    "showHidden", "refreshDataV", "refreshView",
                )
            ],
            "jump": {"value": "https://", "type": "_blank"},
            "download": {"value": True},
            "share": {"value": True},
            "showHidden": {"value": True},
            "refreshDataV": {"value": True},
            "refreshView": {"value": True, "target": "all"},
        },
        "state": "prepare", "id": component_id, "canvasActive": False, "editing": False,
        "show": True, "cascade": cascades, "linkageFilters": None,
    }
    view = {
        "id": component_id, "title": "智能查询", "sceneId": "0", "tableId": dataset_id,
        "type": "VQuery", "render": "antv", "resultCount": 1000, "resultMode": "all",
        "xAxis": [], "xAxisExt": [], "yAxis": [], "yAxisExt": [], "extStack": [],
        "extBubble": [], "extLabel": [], "extTooltip": [], "drillFields": [],
        "customFilter": {"filter": []}, "linkageActive": False, "jumpActive": False,
        "drill": False, "drillFilters": None,
        "customStyle": {"component": query_style},
    }
    return component, view


def shared_linkages(charts: list[dict[str, Any]], view_ids: list[str], views: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source_index, source in enumerate(charts):
        source_fields = {str(item.get("name")): str(item.get("id")) for item in views[view_ids[source_index]].get("xAxis", [])}
        targets = []
        for target_index, target in enumerate(charts):
            if source_index == target_index or str(source.get("dataset_name")) != str(target.get("dataset_name")):
                continue
            target_fields = {str(item.get("name")): str(item.get("id")) for item in views[view_ids[target_index]].get("xAxis", [])}
            common = sorted(set(source_fields) & set(target_fields))
            if common:
                targets.append({
                    "targetViewId": view_ids[target_index], "linkageActive": True,
                    "linkageFields": [{"sourceField": source_fields[name], "targetField": target_fields[name]} for name in common],
                })
        if targets:
            result.append({"sourceViewId": view_ids[source_index], "linkageInfo": targets})
    return result
