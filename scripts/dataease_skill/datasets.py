from __future__ import annotations

import re
from typing import Any

from .client import DataEaseClient
from .errors import DataEaseError
from .trees import flatten_tree


DATE_TYPES = {"DATE", "DATETIME", "TIMESTAMP", "TIME", "YEAR"}
NUMBER_TYPES = {"INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "NUMBER"}
SENSITIVE_PATTERN = re.compile(r"(身份证|手机|电话|邮箱|住址|银行卡|密码|secret|token|password|phone|mobile|email|address|id_card)", re.I)
IDENTIFIER_PATTERN = re.compile(
    r"(^id$|(?<![A-Za-z])id$|_id$|Id$|ID$|编号$|编码$|序号$|流水号$|主键$|(?:^|_)[Cc][Oo][Dd][Ee]$|Code$)",
)
AVERAGE_PATTERN = re.compile(
    r"(%|百分比|比例|比率|占比|率$|均值|平均|评分|得分|指数|单价|客单价|均价|avg|average|rate|ratio|percent)",
    re.I,
)


class DatasetService:
    def __init__(self, client: DataEaseClient):
        self.client = client

    def list(self) -> list[dict[str, Any]]:
        data = self.client.data("POST", "/datasetTree/tree", {"busiFlag": "dataset"})
        return flatten_tree(data if isinstance(data, list) else [], leaves_only=True)

    def resolve(self, name_or_id: str) -> dict[str, Any]:
        matches = [item for item in self.list() if str(item.get("id")) == str(name_or_id)]
        if not matches:
            exact = [item for item in self.list() if item.get("name") == name_or_id]
            matches = exact
        if not matches:
            fuzzy = [item for item in self.list() if name_or_id.lower() in str(item.get("name", "")).lower()]
            if len(fuzzy) == 1:
                matches = fuzzy
            elif fuzzy:
                raise DataEaseError(
                    f"数据集名称不唯一: {name_or_id}",
                    code="ambiguous_dataset",
                    stage="dataset",
                    details={"candidates": [{"id": item.get("id"), "name": item.get("name")} for item in fuzzy[:20]]},
                )
        if not matches:
            raise DataEaseError(f"找不到数据集: {name_or_id}", code="dataset_not_found", stage="dataset")
        return matches[0]

    def fields(self, name_or_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        dataset = self.resolve(name_or_id)
        dataset_id = str(dataset.get("id"))
        fields: list[dict[str, Any]] = []
        try:
            details = self.client.data("GET", f"/datasetTree/details/{dataset_id}")
            if isinstance(details, dict):
                fields = details.get("allFields") or []
        except DataEaseError:
            details = self.client.data("POST", f"/datasetTree/details/{dataset_id}")
            if isinstance(details, dict):
                fields = details.get("allFields") or []
        if not fields:
            result = self.client.data("POST", f"/datasetField/listByDatasetGroup/{dataset_id}")
            if isinstance(result, list):
                fields = result
        if not fields:
            raise DataEaseError(f"数据集没有可用字段: {dataset.get('name')}", code="empty_dataset", stage="dataset")
        return dataset, fields

    def profile(self, name_or_id: str) -> dict[str, Any]:
        dataset, fields = self.fields(name_or_id)
        profiled = [profile_field(field) for field in fields]
        return {
            "dataset": {"id": str(dataset.get("id")), "name": dataset.get("name"), "path": dataset.get("path")},
            "field_count": len(profiled),
            "dimensions": [item for item in profiled if item["semantic_role"] == "dimension"],
            "measures": [item for item in profiled if item["semantic_role"] == "measure"],
            "dates": [item for item in profiled if item["semantic_role"] == "date"],
            "identifiers": [item for item in profiled if item["semantic_role"] == "identifier"],
            "sensitive_fields": [item for item in profiled if item["sensitive"]],
            "fields": profiled,
            "limitations": ["当前画像基于字段元数据；值域、空值率和基数需要数据预览权限后进一步计算。"],
        }


def profile_field(field: dict[str, Any]) -> dict[str, Any]:
    name = str(field.get("name") or field.get("originName") or "")
    db_type = str(field.get("type") or "").upper()
    de_type = field.get("deType")
    group_type = str(field.get("groupType") or "").lower()
    lowered = name.lower()
    if db_type in DATE_TYPES or de_type == 1 or any(marker in lowered for marker in ("date", "time", "日期", "时间", "年月", "月份")):
        semantic_role = "date"
    elif IDENTIFIER_PATTERN.search(name):
        semantic_role = "identifier"
    elif db_type in NUMBER_TYPES or de_type == 2 or group_type == "q":
        semantic_role = "measure"
    else:
        semantic_role = "dimension"
    aggregation = None
    if semantic_role == "measure":
        aggregation = "avg" if AVERAGE_PATTERN.search(name) else "sum"
    return {
        "id": str(field.get("id") or ""),
        "name": name,
        "origin_name": field.get("originName"),
        "dataease_name": field.get("dataeaseName"),
        "database_type": db_type or None,
        "de_type": de_type,
        "semantic_role": semantic_role,
        "recommended_aggregation": aggregation,
        "sensitive": bool(SENSITIVE_PATTERN.search(name)),
        "desensitized": bool(field.get("desensitized")),
    }
