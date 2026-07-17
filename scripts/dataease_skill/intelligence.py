from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


def _profiles(value: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    profiles = value if isinstance(value, list) else [value]
    if not profiles or any(not isinstance(item, dict) or not isinstance(item.get("dataset"), dict) for item in profiles):
        raise ValueError("可视化规划需要至少一个有效的数据集画像")
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for profile in profiles:
        dataset_id = str(profile["dataset"].get("id") or "")
        if not dataset_id:
            raise ValueError("数据集画像缺少 dataset.id")
        if dataset_id not in seen:
            seen.add(dataset_id)
            unique.append(profile)
    return unique


def _field_names(profile: dict[str, Any], role: str) -> list[str]:
    return [str(item["name"]) for item in profile.get(role, []) if item.get("name")]


def _measure_candidates(profile: dict[str, Any]) -> list[dict[str, Any]]:
    measures = []
    for item in profile.get("measures", []):
        if not item.get("name"):
            continue
        measure = dict(item)
        measure["display_name"] = str(item["name"])
        measure["aggregation"] = str(item.get("recommended_aggregation") or "sum")
        measure["derived_from_identifier"] = False
        measures.append(measure)
    if measures:
        return measures
    identifiers = [item for item in profile.get("identifiers", []) if item.get("name")]
    if not identifiers:
        return []
    identifier = dict(identifiers[0])
    identifier.update(
        {
            "display_name": "记录数",
            "aggregation": "count_distinct",
            "derived_from_identifier": True,
        }
    )
    return [identifier]


def _qualified_title(dataset_name: str, title: str, multi: bool) -> str:
    return f"{dataset_name} · {title}" if multi else title


def _normalized_field_name(name: str) -> str:
    return re.sub(r"[\s_\-./（）()]+", "", name).casefold()


def _relationship_candidates(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    occurrences: dict[str, list[dict[str, str]]] = defaultdict(list)
    for profile in profiles:
        dataset = profile["dataset"]
        for role in ("dates", "dimensions", "identifiers"):
            for field in profile.get(role, []):
                name = str(field.get("name") or "").strip()
                if not name:
                    continue
                occurrences[_normalized_field_name(name)].append(
                    {
                        "dataset_id": str(dataset["id"]),
                        "dataset_name": str(dataset.get("name") or dataset["id"]),
                        "field": name,
                        "semantic_role": str(field.get("semantic_role") or role.rstrip("s")),
                    }
                )
    relationships: list[dict[str, Any]] = []
    for matches in occurrences.values():
        dataset_ids = {item["dataset_id"] for item in matches}
        if len(dataset_ids) < 2:
            continue
        relationships.append(
            {
                "field": matches[0]["field"],
                "matches": matches,
                "confidence": "exact-normalized-name",
                "requires_confirmation": True,
            }
        )
    return relationships


def build_visual_plan(
    profile: dict[str, Any] | list[dict[str, Any]],
    title: str,
    busi_type: str = "dashboard",
) -> dict[str, Any]:
    profiles = _profiles(profile)
    if busi_type not in {"dashboard", "dataV"}:
        raise ValueError("busi_type 必须是 dashboard 或 dataV")

    multi = len(profiles) > 1
    charts: list[dict[str, Any]] = []
    recommendations: list[str] = []
    kpi_candidates: list[dict[str, Any]] = []
    usable_profiles: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []

    for current in profiles:
        dataset = current["dataset"]
        dataset_name = str(dataset.get("name") or dataset["id"])
        dimensions = _field_names(current, "dimensions")
        measure_items = _measure_candidates(current)
        measures = [str(item["name"]) for item in measure_items]
        measure_aggregations = [str(item["aggregation"]) for item in measure_items]
        dates = _field_names(current, "dates")
        identifiers = _field_names(current, "identifiers")
        if not measures:
            recommendations.append(f"数据集“{dataset_name}”没有可识别的指标字段，未为其自动生成图表。")
            continue
        usable_profiles.append((current, measure_items))
        primary_dimension = dimensions[0] if dimensions else dates[0] if dates else identifiers[0] if identifiers else None
        primary_measure = str(measure_items[0]["display_name"])
        if measure_items[0].get("derived_from_identifier"):
            recommendations.append(
                f"数据集“{dataset_name}”没有数值指标，已用标识符“{measures[0]}”的去重计数作为记录数候选。"
            )
        for measure in measure_items[:3]:
            kpi_candidates.append(
                {
                    "dataset_id": str(dataset["id"]),
                    "dataset_name": dataset_name,
                    "field": str(measure["name"]),
                    "display_name": str(measure["display_name"]),
                    "aggregation": str(measure["aggregation"]),
                    "business_definition_confirmed": False,
                }
            )
        if dates:
            charts.append(
                {
                    "type": "line",
                    "title": _qualified_title(dataset_name, f"{primary_measure}趋势", multi),
                    "dataset_name": str(dataset["id"]),
                    "x_axis": [dates[0]],
                    "y_axis": measures[:2],
                    "y_aggregations": measure_aggregations[:2],
                    "intent": "trend",
                }
            )
        if primary_dimension:
            charts.append(
                {
                    "type": "bar",
                    "title": _qualified_title(dataset_name, f"按{primary_dimension}分析{primary_measure}", multi),
                    "dataset_name": str(dataset["id"]),
                    "x_axis": [primary_dimension],
                    "y_axis": measures[:2],
                    "y_aggregations": measure_aggregations[:2],
                    "intent": "comparison",
                }
            )
        if current.get("sensitive_fields"):
            recommendations.append(f"发布前检查数据集“{dataset_name}”敏感字段的列权限与脱敏规则。")
        if not dates:
            recommendations.append(f"数据集“{dataset_name}”未识别到日期字段，无法自动生成时间趋势图。")

    if not usable_profiles:
        raise ValueError("所选数据集中没有可识别的指标字段，无法自动规划图表")

    primary, primary_measure_items = usable_profiles[0]
    primary_dataset = primary["dataset"]
    primary_dimensions = _field_names(primary, "dimensions")
    primary_measures = [str(item["name"]) for item in primary_measure_items]
    primary_measure_aggregations = [str(item["aggregation"]) for item in primary_measure_items]
    primary_dates = _field_names(primary, "dates")
    primary_identifiers = _field_names(primary, "identifiers")
    primary_dimension = (
        primary_dimensions[0]
        if primary_dimensions
        else primary_dates[0]
        if primary_dates
        else primary_identifiers[0]
        if primary_identifiers
        else None
    )
    if primary_dimension:
        charts.append(
            {
                "type": "pie",
                "title": _qualified_title(
                    str(primary_dataset.get("name") or primary_dataset["id"]),
                    f"{primary_dimension}构成",
                    multi,
                ),
                "dataset_name": str(primary_dataset["id"]),
                "x_axis": [primary_dimension],
                "y_axis": [primary_measures[0]],
                "y_aggregations": [primary_measure_aggregations[0]],
                "intent": "composition",
            }
        )
    table_dimensions = [*primary_dates[:1], *primary_dimensions[:2], *primary_identifiers[:1]]
    charts.append(
        {
            "type": "table_info",
            "title": _qualified_title(
                str(primary_dataset.get("name") or primary_dataset["id"]),
                "业务明细",
                multi,
            ),
            "dataset_name": str(primary_dataset["id"]),
            "x_axis": table_dimensions[:2],
            "y_axis": primary_measures[:2],
            "y_aggregations": primary_measure_aggregations[:2],
            "intent": "detail",
        }
    )

    relationships = _relationship_candidates(profiles)
    if multi:
        if relationships:
            recommendations.append("跨数据集关联仅依据规范化后的同名字段推测；创建计算字段或联动前必须确认业务主键与粒度。")
        else:
            recommendations.append("未发现可靠的跨数据集同名关联字段；当前方案仅在同一画布并列展示多个数据集。")

    filters = primary_dates[:1] + primary_dimensions[:2]
    return {
        "schema_version": 2,
        "kind": busi_type,
        "title": title,
        "dataset": primary_dataset,
        "datasets": [item["dataset"] for item in profiles],
        "theme": "neon-dark" if busi_type == "dataV" else "business-light",
        "charts": charts,
        "interactions": {
            "filters": filters,
            "linkage": True,
            "cross_dataset_linkage_requires_confirmation": bool(multi),
        },
        "dataset_relationships": relationships,
        "kpi_candidates": kpi_candidates,
        "recommendations": recommendations,
        "limitations": ["当前规划基于字段元数据；业务指标口径、关联键、数据粒度和聚合方式必须在创建前确认。"],
    }
