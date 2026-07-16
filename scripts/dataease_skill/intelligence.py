from __future__ import annotations

from typing import Any


def build_visual_plan(profile: dict[str, Any], title: str, busi_type: str = "dashboard") -> dict[str, Any]:
    dataset = profile["dataset"]
    dimensions = [item["name"] for item in profile.get("dimensions", []) if item.get("name")]
    measures = [item["name"] for item in profile.get("measures", []) if item.get("name")]
    dates = [item["name"] for item in profile.get("dates", []) if item.get("name")]
    identifiers = [item["name"] for item in profile.get("identifiers", []) if item.get("name")]
    if not measures:
        raise ValueError("数据集中没有可识别的指标字段，无法自动规划图表")

    primary_dimension = dimensions[0] if dimensions else dates[0] if dates else identifiers[0] if identifiers else None
    primary_measure = measures[0]
    charts: list[dict[str, Any]] = []

    if dates:
        charts.append({
            "type": "line",
            "title": f"{primary_measure}趋势",
            "dataset_name": dataset["id"],
            "x_axis": [dates[0]],
            "y_axis": measures[:2],
            "intent": "trend",
        })
    if primary_dimension:
        charts.append({
            "type": "bar",
            "title": f"按{primary_dimension}分析{primary_measure}",
            "dataset_name": dataset["id"],
            "x_axis": [primary_dimension],
            "y_axis": measures[:2],
            "intent": "comparison",
        })
        charts.append({
            "type": "pie",
            "title": f"{primary_dimension}构成",
            "dataset_name": dataset["id"],
            "x_axis": [primary_dimension],
            "y_axis": [primary_measure],
            "intent": "composition",
        })
    table_dimensions = [*dates[:1], *dimensions[:2], *identifiers[:1]]
    if table_dimensions or measures:
        charts.append({
            "type": "table_info",
            "title": "业务明细",
            "dataset_name": dataset["id"],
            "x_axis": table_dimensions[:2],
            "y_axis": measures[:2],
            "intent": "detail",
        })

    recommendations = []
    if profile.get("sensitive_fields"):
        recommendations.append("发布前检查敏感字段的列权限与脱敏规则。")
    if not dates:
        recommendations.append("未识别到日期字段，无法自动生成时间趋势图。")
    return {
        "schema_version": 1,
        "kind": busi_type,
        "title": title,
        "dataset": dataset,
        "theme": "neon-dark" if busi_type == "dataV" else "business-light",
        "charts": charts,
        "interactions": {"filters": dates[:1] + dimensions[:2], "linkage": True},
        "recommendations": recommendations,
    }
