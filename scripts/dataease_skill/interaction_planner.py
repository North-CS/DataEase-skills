from __future__ import annotations

import copy
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
    """Infer only adjacent, unambiguous hierarchy runs from the requested filter order."""
    positions: list[tuple[str, int] | None] = []
    for field in filters:
        key = _semantic_key(field)
        matches: list[tuple[str, int]] = []
        for family, levels in _CASCADE_HIERARCHIES.items():
            for rank, aliases in enumerate(levels):
                if key in {_semantic_key(alias) for alias in aliases}:
                    matches.append((family, rank))
        positions.append(matches[0] if len(matches) == 1 else None)

    cascades: list[list[str]] = []
    current: list[str] = []
    previous: tuple[str, int] | None = None
    for index, (field, position) in enumerate(zip(filters, positions)):
        if position and previous and position[0] == previous[0] and position[1] > previous[1]:
            if not current:
                current = [filters[index - 1]]
            current.append(field)
        else:
            if len(current) >= 2:
                cascades.append(current)
            current = []
        previous = position
    if len(current) >= 2:
        cascades.append(current)
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
    jump_rules = value.get("jumps") if isinstance(value.get("jumps"), list) else []
    for rule in [*drill_rules, *jump_rules]:
        if isinstance(rule, dict) and not rule.get("source") and rule.get("chart"):
            rule["source"] = rule["chart"]
    return {
        "filters": normalized_filters,
        "filter_cascades": filter_cascades,
        "auto_linkage": bool(value.get("auto_linkage", value.get("linkage", False))),
        "drill_hierarchies": drill_rules,
        "jumps": jump_rules,
    }


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
    condition_by_name = {str(item["name"]): item for item in conditions}
    cascades: list[list[dict[str, Any]]] = []
    for chain_index, chain in enumerate(cascade_chains or []):
        chain_conditions = [condition_by_name.get(str(name)) for name in chain]
        if len(chain_conditions) < 2 or any(item is None for item in chain_conditions):
            continue
        cascades.append([
            {
                "datasetId": f"{dataset_id}--{condition['id']}--{condition['field']['id']}",
                "fieldId": "",
                "placeholder": "第一个条件" if position == 0 else "需上一个使用同一数据集的条件",
                "id": f"{component_id}9{chain_index + 1}{position + 1}",
                "selectValue": [],
                "defaultValueFirstItem": False,
                "currentSelectValue": [],
            }
            for position, condition in enumerate(chain_conditions)
        ])

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
