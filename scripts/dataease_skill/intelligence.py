from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .layout_planner import describe_layout_strategy, plan_smart_layouts
from .chart_catalog import SUPPORTED_CHART_TYPES
from .design_inspiration import apply_design_inspiration


OHLC_PATTERN = re.compile(
    r"(open|开盘|close|收盘|high|最高|low|最低|volume|成交量|成交额|amount|turnover)",
    re.I,
)

DRILL_HIERARCHIES = (
    ("大区", "省级行政区", "省", "城市", "区县", "门店"),
    ("region", "province", "city", "district", "store"),
    ("品类", "子品类", "商品"),
    ("category", "subcategory", "product"),
    ("部门", "团队", "员工"),
)


def _detect_drill_hierarchy(fields: list[str]) -> list[str]:
    normalized = {str(item).strip().lower(): str(item) for item in fields}
    for hierarchy in DRILL_HIERARCHIES:
        matched = [normalized[name.lower()] for name in hierarchy if name.lower() in normalized]
        if len(matched) >= 2:
            return matched
    return []
GAUGE_PATTERN = re.compile(
    r"(current|当前|value|数值|score|得分|rate|比率|progress|进度)",
    re.I,
)
WATERFALL_PATTERN = re.compile(
    r"(金额|收入|支出|利润|成本|费用|亏损|盈利|amount|revenue|income|expense|cost|profit|loss)",
    re.I,
)
GEO_PATTERN = re.compile(r"(国家|大区|区域|省|市|区县|地区|地域|region|province|city|district|country)", re.I)
STAGE_PATTERN = re.compile(r"(阶段|状态|流程|漏斗|stage|status|phase|funnel)", re.I)
TEXT_PATTERN = re.compile(r"(关键词|标签|主题|搜索词|词语|keyword|tag|topic|word)", re.I)
AUTO_PLANNABLE_TYPES = frozenset({
    "indicator", "gauge", "line", "area-stack", "bar", "bar-horizontal", "waterfall",
    "pie-donut", "radar", "treemap", "word-cloud", "table_info", "table-pivot",
    "map", "bubble-map", "scatter", "funnel", "candle",
})
MAX_AUTO_CHARTS_PER_DATASET = 12


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


def _detect_ohlc_pattern(profile: dict[str, Any]) -> dict[str, Any] | None:
    """Detect OHLC four-price structure for candlestick charts."""
    measures = profile.get("measures", [])
    dates = profile.get("dates", [])
    if not dates:
        return None
    ohlc_keys = {"open", "close", "high", "low", "开盘价", "收盘价", "最高价", "最低价", "开盘", "收盘", "最高", "最低"}
    matched = [m for m in measures if m.get("name", "") in ohlc_keys or OHLC_PATTERN.search(m.get("name", ""))]
    if len(matched) >= 4:
        return {
            "type": "candle",
            "pattern": "ohlc",
            "confidence": "high",
            "fields": [m["name"] for m in matched[:4]],
            "date_field": dates[0]["name"] if dates else None,
        }
    return None


def _detect_gauge_pattern(profile: dict[str, Any]) -> dict[str, Any] | None:
    """Detect current-value + max-value pair for gauge charts."""
    measures = profile.get("measures", [])
    dims = profile.get("dimensions", [])
    identifiers = profile.get("identifiers", [])
    if not measures:
        return None
    gauge_measures = [m for m in measures if GAUGE_PATTERN.search(m.get("name", ""))]
    if len(gauge_measures) >= 1:
        label = dims[0]["name"] if dims else identifiers[0]["name"] if identifiers else None
        return {
            "type": "gauge",
            "pattern": "current_value",
            "confidence": "medium",
            "fields": [m["name"] for m in gauge_measures[:2]],
            "label_field": label,
        }
    return None


def _detect_waterfall_pattern(profile: dict[str, Any]) -> dict[str, Any] | None:
    """Detect positive/negative amount structure for waterfall charts."""
    measures = profile.get("measures", [])
    dims = profile.get("dimensions", [])
    identifiers = profile.get("identifiers", [])
    category = dims[0]["name"] if dims else identifiers[0]["name"] if identifiers else None
    if not measures or not category:
        return None
    waterfall_measures = [m for m in measures if WATERFALL_PATTERN.search(m.get("name", ""))]
    if waterfall_measures:
        return {
            "type": "waterfall",
            "pattern": "pnl_amount",
            "confidence": "medium",
            "fields": [m["name"] for m in waterfall_measures[:2]],
            "category_field": category,
        }
    return None


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
        profile_chart_start = len(charts)
        if not measures:
            recommendations.append(f"数据集“{dataset_name}”没有可识别的指标字段，未为其自动生成图表。")
            continue
        usable_profiles.append((current, measure_items))
        primary_dimension = dimensions[0] if dimensions else dates[0] if dates else identifiers[0] if identifiers else None
        geo_dimension = next((name for name in dimensions if GEO_PATTERN.search(name)), None)
        stage_dimension = next((name for name in dimensions if STAGE_PATTERN.search(name)), None)
        text_dimension = next((name for name in dimensions if TEXT_PATTERN.search(name)), None)
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
            charts.append(
                {
                    "type": "indicator",
                    "title": _qualified_title(dataset_name, str(measure["display_name"]), multi),
                    "dataset_name": str(dataset["id"]),
                    "x_axis": [primary_dimension] if primary_dimension else identifiers[:1],
                    "y_axis": [str(measure["name"])],
                    "y_aggregations": [str(measure["aggregation"])],
                    "intent": "kpi",
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
            if len(measures) > 1:
                charts.append(
                    {
                        "type": "area-stack",
                        "title": _qualified_title(dataset_name, f"{primary_measure}累计趋势", multi),
                        "dataset_name": str(dataset["id"]),
                        "x_axis": [dates[0]],
                        "y_axis": measures[:3],
                        "y_aggregations": measure_aggregations[:3],
                        "intent": "trend",
                    }
                )
        if primary_dimension:
            comparison_chart = {
                    "type": "bar",
                    "title": _qualified_title(dataset_name, f"按{primary_dimension}分析{primary_measure}", multi),
                    "dataset_name": str(dataset["id"]),
                    "x_axis": [primary_dimension],
                    "y_axis": measures[:2],
                    "y_aggregations": measure_aggregations[:2],
                    "intent": "comparison",
                }
            drill_hierarchy = _detect_drill_hierarchy(dimensions)
            if drill_hierarchy:
                comparison_chart["x_axis"] = [drill_hierarchy[0]]
                comparison_chart["drill_fields"] = drill_hierarchy[1:]
                recommendations.append(f"数据集“{dataset_name}”识别到高置信度钻取层级：{' → '.join(drill_hierarchy)}。")
            charts.append(comparison_chart)
            charts.append({
                "type": "bar-horizontal", "title": _qualified_title(dataset_name, f"{primary_measure}排行", multi),
                "dataset_name": str(dataset["id"]), "x_axis": [primary_dimension],
                "y_axis": measures[:1], "y_aggregations": measure_aggregations[:1], "intent": "ranking",
            })
            if geo_dimension:
                charts.append(
                    {
                        "type": "map",
                        "title": _qualified_title(dataset_name, f"{geo_dimension}空间分布", multi),
                        "dataset_name": str(dataset["id"]),
                        "x_axis": [geo_dimension],
                        "y_axis": measures[:1],
                        "y_aggregations": measure_aggregations[:1],
                        "intent": "geospatial",
                    }
                )
                if len(measures) > 1:
                    charts.append({
                        "type": "bubble-map", "title": _qualified_title(dataset_name, f"{geo_dimension}规模分布", multi),
                        "dataset_name": str(dataset["id"]), "x_axis": [geo_dimension],
                        "y_axis": measures[:2], "y_aggregations": measure_aggregations[:2], "intent": "geospatial",
                    })
            if stage_dimension:
                charts.append({
                    "type": "funnel", "title": _qualified_title(dataset_name, f"{stage_dimension}转化漏斗", multi),
                    "dataset_name": str(dataset["id"]), "x_axis": [stage_dimension],
                    "y_axis": measures[:1], "y_aggregations": measure_aggregations[:1], "intent": "funnel",
                })
            if text_dimension:
                charts.append({
                    "type": "word-cloud", "title": _qualified_title(dataset_name, f"{text_dimension}热词", multi),
                    "dataset_name": str(dataset["id"]), "x_axis": [text_dimension],
                    "y_axis": measures[:1], "y_aggregations": measure_aggregations[:1], "intent": "distribution",
                })
            if len(measures) >= 2:
                charts.append({
                    "type": "scatter", "title": _qualified_title(dataset_name, f"{measures[0]}与{measures[1]}关系", multi),
                    "dataset_name": str(dataset["id"]), "x_axis": [primary_dimension],
                    "y_axis": measures[:2], "y_aggregations": measure_aggregations[:2], "intent": "correlation",
                })
            if len(measures) >= 3:
                charts.append({
                    "type": "radar", "title": _qualified_title(dataset_name, f"{primary_dimension}多指标画像", multi),
                    "dataset_name": str(dataset["id"]), "x_axis": [primary_dimension],
                    "y_axis": measures[:5], "y_aggregations": measure_aggregations[:5], "intent": "profile",
                })
            if len(dimensions) >= 2:
                charts.append({
                    "type": "treemap", "title": _qualified_title(dataset_name, f"{dimensions[0]}层级构成", multi),
                    "dataset_name": str(dataset["id"]), "x_axis": dimensions[:2],
                    "y_axis": measures[:1], "y_aggregations": measure_aggregations[:1], "intent": "hierarchy",
                })
        if current.get("sensitive_fields"):
            recommendations.append(f"发布前检查数据集“{dataset_name}”敏感字段的列权限与脱敏规则。")
        if not dates:
            recommendations.append(f"数据集“{dataset_name}”未识别到日期字段，无法自动生成时间趋势图。")

        ohlc = _detect_ohlc_pattern(current)
        if ohlc:
            charts.append({
                "type": "candle",
                "title": _qualified_title(dataset_name, f"{ohlc['fields'][0] if ohlc['fields'] else '价格'}走势 (K线)", multi),
                "dataset_name": str(dataset["id"]),
                "x_axis": [ohlc["date_field"]] if ohlc["date_field"] else dates[:1],
                "y_axis": ohlc["fields"],
                "y_aggregations": ["none" for _ in ohlc["fields"]],
                "intent": "ohlc",
            })
            recommendations.append(f"数据集“{dataset_name}”识别到 OHLC 四价结构，已推荐 K 线图。")

        gauge = _detect_gauge_pattern(current)
        if gauge:
            charts.append({
                "type": "gauge",
                "title": _qualified_title(dataset_name, f"{gauge['fields'][0]}进度", multi),
                "dataset_name": str(dataset["id"]),
                "x_axis": [gauge["label_field"]] if gauge["label_field"] else identifiers[:1],
                "y_axis": gauge["fields"][:1],
                "y_aggregations": ["max"],
                "intent": "gauge",
            })
            recommendations.append(f"数据集“{dataset_name}”识别到当前值+最大值结构，已推荐仪表盘。")

        waterfall = _detect_waterfall_pattern(current)
        if waterfall:
            charts.append({
                "type": "waterfall",
                "title": _qualified_title(dataset_name, f"{waterfall['fields'][0]}瀑布分析", multi),
                "dataset_name": str(dataset["id"]),
                "x_axis": [waterfall["category_field"]],
                "y_axis": waterfall["fields"][:1],
                "y_aggregations": ["sum"],
                "intent": "waterfall",
            })
            recommendations.append(f"数据集“{dataset_name}”识别到盈亏金额结构，已推荐瀑布图。")

        profile_charts = charts[profile_chart_start:]
        if len(profile_charts) > MAX_AUTO_CHARTS_PER_DATASET:
            del charts[profile_chart_start:]
            charts.extend(profile_charts[:MAX_AUTO_CHARTS_PER_DATASET])
            recommendations.append(f"数据集“{dataset_name}”命中较多规则，已限制为 {MAX_AUTO_CHARTS_PER_DATASET} 个组件。")

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
                "type": "pie-donut",
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
    if len(primary_dimensions) >= 2 and len(primary_measures) >= 2:
        charts.append({
            "type": "table-pivot", "title": "多维汇总分析",
            "dataset_name": str(primary_dataset["id"]), "x_axis": primary_dimensions[:2],
            "y_axis": primary_measures[:3], "y_aggregations": primary_measure_aggregations[:3],
            "intent": "summary",
        })

    relationships = _relationship_candidates(profiles)
    if multi:
        if relationships:
            recommendations.append("跨数据集关联仅依据规范化后的同名字段推测；创建计算字段或联动前必须确认业务主键与粒度。")
        else:
            recommendations.append("未发现可靠的跨数据集同名关联字段；当前方案仅在同一画布并列展示多个数据集。")

    filters = primary_dates[:1] + primary_dimensions[:2]
    planned_layouts = plan_smart_layouts(charts, reserved_top_rows=4 if filters else 0)
    for chart, layout in zip(charts, planned_layouts):
        chart["layout"] = layout
    spec = {
        "schema_version": 2,
        "kind": busi_type,
        "title": title,
        "dataset": primary_dataset,
        "datasets": [item["dataset"] for item in profiles],
        "theme": "neon-dark" if busi_type == "dataV" else "business-light",
        "charts": charts,
        "layout_strategy": describe_layout_strategy(charts),
        "supported_chart_types": sorted(SUPPORTED_CHART_TYPES),
        "auto_plannable_chart_types": sorted(AUTO_PLANNABLE_TYPES),
        "planning_policy": {
            "max_profile_charts_per_dataset": MAX_AUTO_CHARTS_PER_DATASET,
            "specialized_charts_require_semantic_match": True,
            "explicit_only_types": sorted(SUPPORTED_CHART_TYPES - AUTO_PLANNABLE_TYPES),
        },
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
    return apply_design_inspiration(spec, title=title, busi_type=busi_type)
