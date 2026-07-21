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
SNAPSHOT_PATTERN = re.compile(
    r"(开盘|收盘|open|close|结算价|市价|最新价|现价|current_price|latest)",
    re.I,
)
PEAK_PATTERN = re.compile(
    r"(最高|最大|峰值|上限|max|maximum|peak|high_water|limit|high_price|最高价)",
    re.I,
)
MIN_PATTERN = re.compile(
    r"(最低|最小|谷值|下限|min|minimum|trough|low_water|floor|low_price|最低价)",
    re.I,
)


class DatasetService:
    def __init__(self, client: DataEaseClient):
        self.client = client

    def list(self, *, summary: bool = False) -> dict[str, Any]:
        data = self.client.data("POST", "/datasetTree/tree", {"busiFlag": "dataset"})
        items = flatten_tree(data if isinstance(data, list) else [], leaves_only=True)
        result: dict[str, Any] = {
            "total_count": len(items),
            "items": items,
        }
        if summary:
            by_type: dict[str, int] = {}
            by_path: dict[str, int] = {}
            for item in items:
                t = str(item.get("nodeType") or item.get("type") or "unknown")
                by_type[t] = by_type.get(t, 0) + 1
                path = str(item.get("path") or "/")
                top = path.lstrip("/").split("/")[0] if path.strip("/") else "/"
                by_path[top] = by_path.get(top, 0) + 1
            result["summary"] = {"by_type": by_type, "by_top_path": by_path}
        return result

    def resolve(self, name_or_id: str) -> dict[str, Any]:
        items = self.list()["items"]
        matches = [item for item in items if str(item.get("id")) == str(name_or_id)]
        if not matches:
            exact = [item for item in items if item.get("name") == name_or_id]
            matches = exact
        if not matches:
            fuzzy = [item for item in items if name_or_id.lower() in str(item.get("name", "")).lower()]
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

    def preview(self, name_or_id: str, *, limit: int = 50) -> dict[str, Any]:
        """Fetch dataset data preview with graceful degradation across multiple API paths.

        Strategy:
          1. Try /datasetData/previewData (direct-connect datasets — mode=0)
          2. Try /datasetField/listByDatasetGroup (fallback: field metadata)
          3. Try /datasetTree/details (last-resort: table schema info)
          4. Return clear degradation message so Agent can guide user to Web UI

        Direct-connect datasets (mode=0) often throw server-side NPE when
        getAllFields() returns null in the Java backend.  This method captures
        that and degrades gracefully instead of crashing.
        """
        dataset = self.resolve(name_or_id)
        dataset_id = str(dataset.get("id"))
        dataset_name = str(dataset.get("name", dataset_id))
        mode = dataset.get("mode", 0)
        attempts: list[dict[str, Any]] = []

        # Attempt 1: /datasetData/previewData
        try:
            payload = {
                "id": dataset_id,
                "current": 1,
                "size": limit,
                "sort": {},
                "searchCount": True,
                "filter": [],
            }
            result = self.client.data("POST", "/datasetData/previewData", payload)
            if isinstance(result, dict) and result.get("data"):
                rows = result["data"]
                if isinstance(rows, list) and rows:
                    return {
                        "dataset": {"id": dataset_id, "name": dataset_name, "mode": mode},
                        "source": "/datasetData/previewData",
                        "total": result.get("total", len(rows)),
                        "rows": rows[:limit],
                        "row_count": len(rows[:limit]),
                        "truncated": result.get("total", len(rows)) > limit,
                    }
            attempts.append({"endpoint": "/datasetData/previewData", "status": "empty_or_no_data"})
        except DataEaseError as exc:
            if "NullPointerException" in str(exc) or "NPE" in str(exc) or "getAllFields" in str(exc):
                attempts.append({
                    "endpoint": "/datasetData/previewData",
                    "status": "server_npe",
                    "note": "直连数据集 mode=0 时服务端 getAllFields() 返回 null，属于已知 DataEase 服务端问题",
                })
            else:
                attempts.append({"endpoint": "/datasetData/previewData", "status": "error", "detail": str(exc)[:200]})

        # Attempt 2: /datasetField/listByDatasetGroup
        try:
            fields = self.client.data("POST", f"/datasetField/listByDatasetGroup/{dataset_id}")
            if isinstance(fields, list) and fields:
                return {
                    "dataset": {"id": dataset_id, "name": dataset_name, "mode": mode},
                    "source": "/datasetField/listByDatasetGroup",
                    "degraded": True,
                    "degradation_reason": "只能获取字段结构，无法获取实际数据行。直连数据集请使用 Web UI 或数据库直连预览。",
                    "field_count": len(fields),
                    "field_names": [f.get("name") or f.get("dataeaseName") or f"field_{f.get('id')}" for f in fields[:50]],
                    "rows": [],
                    "row_count": 0,
                }
            attempts.append({"endpoint": "/datasetField/listByDatasetGroup", "status": "empty"})
        except DataEaseError as exc:
            attempts.append({"endpoint": "/datasetField/listByDatasetGroup", "status": "error", "detail": str(exc)[:200]})

        # Attempt 3: /datasetTree/details
        try:
            details = self.client.data("GET", f"/datasetTree/details/{dataset_id}")
            if not isinstance(details, dict):
                details = self.client.data("POST", f"/datasetTree/details/{dataset_id}")
            if isinstance(details, dict):
                table_name = details.get("tableName") or details.get("name") or "unknown"
                return {
                    "dataset": {"id": dataset_id, "name": dataset_name, "mode": mode, "table": table_name},
                    "source": "/datasetTree/details",
                    "degraded": True,
                    "degradation_reason": f"只能获取物理表名 ({table_name})，无法获取数据预览。直连数据集 (mode={mode}) 的数据预览在服务端存在已知限制。",
                    "rows": [],
                    "row_count": 0,
                    "workaround": "请通过 DataEase Web UI 或直连数据库查看数据。",
                }
            attempts.append({"endpoint": "/datasetTree/details", "status": "empty"})
        except DataEaseError as exc:
            attempts.append({"endpoint": "/datasetTree/details", "status": "error", "detail": str(exc)[:200]})

        # All attempts failed
        return {
            "dataset": {"id": dataset_id, "name": dataset_name, "mode": mode},
            "source": "none",
            "degraded": True,
            "degradation_reason": "所有数据预览路径均失败。直连数据集 (mode=0) 在当前 DataEase 版本不支持通过 API 预览数据。",
            "attempts": attempts,
            "rows": [],
            "row_count": 0,
            "workaround": "请通过 DataEase Web UI (数据准备 → 数据集 → 预览) 或直连数据库查看数据。",
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
        if SNAPSHOT_PATTERN.search(name):
            aggregation = "last"
        elif PEAK_PATTERN.search(name):
            aggregation = "max"
        elif MIN_PATTERN.search(name):
            aggregation = "min"
        elif AVERAGE_PATTERN.search(name):
            aggregation = "avg"
        else:
            aggregation = "sum"
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
