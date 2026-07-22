from __future__ import annotations

import copy
from typing import Any


def normalize_interactions(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"filters": [], "auto_linkage": False, "drill_hierarchies": [], "jumps": []}
    filters = value.get("filters") or []
    return {
        "filters": [str(item) for item in filters if isinstance(item, (str, int)) and str(item).strip()][:4],
        "auto_linkage": bool(value.get("auto_linkage", value.get("linkage", False))),
        "drill_hierarchies": value.get("drill_hierarchies") if isinstance(value.get("drill_hierarchies"), list) else [],
        "jumps": value.get("jumps") if isinstance(value.get("jumps"), list) else [],
    }


def build_query_component(
    component_id: str,
    dataset_id: str,
    filter_fields: list[dict[str, Any]],
    target_view_ids: list[str],
    *,
    canvas_width: int,
    canvas_height: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
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
            "defaultValue": [],
            "selectValue": [],
            "optionValueSource": 1,
            "valueSource": [],
            "dataset": {"id": dataset_id, "name": "", "fields": [copy.deepcopy(field)]},
            "visible": True,
            "multiple": False,
            "displayType": "7" if int(field.get("deType") or 0) == 1 else "0",
            "checkedFields": target_view_ids,
            "checkedFieldsMap": checked_map,
            "parameters": [],
            "parametersCheck": False,
            "required": False,
            "auto": False,
            "cascade": [],
        })
    component = {
        "component": "VQuery", "name": "智能查询", "label": "智能查询",
        "propValue": conditions, "icon": "icon_search", "innerType": "VQuery",
        "isHang": False, "freeze": False, "x": 1, "y": 1, "sizeX": 72, "sizeY": 4,
        "style": {"rotate": 0, "opacity": 1, "borderActive": False, "borderWidth": 1,
                  "borderRadius": 5, "width": canvas_width, "height": round(canvas_height * 4 / 36),
                  "left": 0, "top": 0},
        "state": "prepare", "id": component_id, "canvasActive": False, "editing": False,
        "show": True, "cascade": [], "linkageFilters": [],
    }
    view = {
        "id": component_id, "title": "智能查询", "sceneId": "0", "tableId": dataset_id,
        "type": "VQuery", "render": "antv", "resultCount": 1000, "resultMode": "all",
        "xAxis": [], "xAxisExt": [], "yAxis": [], "yAxisExt": [], "extStack": [],
        "extBubble": [], "extLabel": [], "extTooltip": [], "drillFields": [],
        "customFilter": {"filter": []}, "linkageActive": False, "jumpActive": False,
        "drill": False, "drillFilters": None,
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
