from __future__ import annotations

import copy
from typing import Any


FIELD_METADATA_KEYS = {
    "id", "datasourceId", "datasetTableId", "datasetGroupId", "originName", "name",
    "dbFieldName", "description", "dataeaseName", "groupType", "type", "precision",
    "scale", "deType", "deExtractType", "extField", "columnIndex", "dateFormat",
    "dateFormatType", "fieldShortName", "desensitized", "params",
}


def normalized_field_metadata(field: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    result = {key: copy.deepcopy(value) for key, value in field.items() if key in FIELD_METADATA_KEYS}
    result["datasetGroupId"] = str(field.get("datasetGroupId") or dataset_id)
    if not result.get("groupType") and result.get("deType") is not None:
        result["groupType"] = "q" if int(result["deType"]) in {2, 3} else "d"
    if result.get("dataeaseName"):
        result["fieldShortName"] = result["dataeaseName"]
    return result


def bind_field_metadata(obj: Any, target_id: str, field: dict[str, Any]) -> None:
    """Replace rendered template fields with authoritative dataset metadata."""
    if isinstance(obj, dict):
        if str(obj.get("id")) == str(target_id):
            for key, value in field.items():
                if key in FIELD_METADATA_KEYS:
                    obj[key] = copy.deepcopy(value)
            if str(field.get("groupType") or "").lower() == "d":
                obj["summary"] = "none"
            name = str(field.get("name") or field.get("originName") or "")
            for key in ("optionLabel", "optionShowName"):
                if key in obj and isinstance(obj[key], str):
                    suffix = obj[key][obj[key].find("(") :] if "(" in obj[key] else ""
                    obj[key] = name + suffix
            if "seriesId" in obj:
                suffix = str(obj["seriesId"]).split("-", 1)[1] if "-" in str(obj["seriesId"]) else "yAxis"
                obj["seriesId"] = f"{field.get('id')}-{suffix}"
        for value in obj.values():
            bind_field_metadata(value, target_id, field)
    elif isinstance(obj, list):
        for item in obj:
            bind_field_metadata(item, target_id, field)
