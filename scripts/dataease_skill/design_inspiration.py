from __future__ import annotations

import hashlib
import re
from typing import Any

from .layout_planner import describe_layout_strategy, plan_smart_layouts


# These are design grammars, not copies of marketplace templates.  Each grammar
# describes a decision pattern that can be applied to the caller's own data.
DESIGN_GRAMMARS: dict[str, dict[str, Any]] = {
    "executive-overview": {
        "keywords": ("经营", "管理", "领导", "总览", "年度", "executive", "overview"),
        "theme": {"dashboard": "business-light", "dataV": "dark-gold"},
        "layout": "kpi-led-balanced",
        "priority": ("kpi", "trend", "comparison", "composition", "ranking", "detail"),
        "principles": ("先结论后证据", "KPI 一眼可读", "趋势与结构相邻", "明细用于追溯"),
    },
    "retail-operations": {
        "keywords": ("零售", "电商", "门店", "商品", "销售", "库存", "供应链"),
        "theme": {"dashboard": "retail-vibrant", "dataV": "deep-ocean"},
        "layout": "conversion-and-ranking",
        "priority": ("kpi", "trend", "ranking", "geospatial", "composition", "detail"),
        "principles": ("销售与目标优先", "排行驱动行动", "时间与区域均可筛选", "控制装饰色数量"),
    },
    "financial-control": {
        "keywords": ("财务", "预算", "成本", "利润", "现金流", "资金", "损益", "finance", "budget"),
        "theme": {"dashboard": "business-light", "dataV": "dark-gold"},
        "layout": "variance-control",
        "priority": ("kpi", "trend", "comparison", "ranking", "composition", "detail"),
        "principles": ("实际与预算并置", "突出差异而非装饰", "金额单位保持一致", "明细支持审计追溯"),
    },
    "marketing-growth": {
        "keywords": ("营销", "广告", "活动", "获客", "转化", "渠道", "用户增长", "campaign", "marketing"),
        "theme": {"dashboard": "retail-vibrant", "dataV": "tech-blue"},
        "layout": "funnel-and-cohort",
        "priority": ("kpi", "trend", "composition", "ranking", "comparison", "detail"),
        "principles": ("从触达走向转化", "渠道对比可行动", "趋势与漏斗互证", "避免用虚荣指标占据主视觉"),
    },
    "project-delivery": {
        "keywords": ("项目", "任务", "里程碑", "工期", "交付", "研发", "缺陷", "project", "delivery"),
        "theme": {"dashboard": "minimal-light", "dataV": "tech-blue"},
        "layout": "progress-and-risk",
        "priority": ("kpi", "trend", "comparison", "ranking", "detail", "composition"),
        "principles": ("进度与风险并重", "按负责人或阶段追踪", "异常可下钻", "状态颜色保持一致"),
    },
    "operations-command": {
        "keywords": ("运维", "安全", "监控", "告警", "网络", "设备", "审计", "工厂"),
        "theme": {"dashboard": "tech-blue", "dataV": "neon-dark"},
        "layout": "status-command-center",
        "priority": ("kpi", "trend", "comparison", "ranking", "detail", "composition"),
        "principles": ("状态和异常优先", "趋势占据主视觉", "明细保留处置线索", "高亮色只用于告警"),
    },
    "geo-command": {
        "keywords": ("城市", "区域", "全国", "省", "地理", "生态", "环保", "交通", "社区"),
        "theme": {"dashboard": "government-blue", "dataV": "tech-blue"},
        "layout": "map-focal",
        "priority": ("kpi", "geospatial", "trend", "ranking", "comparison", "detail"),
        "principles": ("地图只在地域字段可靠时作为焦点", "地图旁配置趋势或排行", "保留区域筛选", "避免地图与装饰争夺注意力"),
    },
    "public-service": {
        "keywords": ("政务", "政府", "民生", "医疗", "医院", "健康", "公积金"),
        "theme": {"dashboard": "government-blue", "dataV": "deep-ocean"},
        "layout": "service-outcome",
        "priority": ("kpi", "trend", "comparison", "geospatial", "detail", "composition"),
        "principles": ("服务结果优先", "用语克制清晰", "保证文字对比度", "表格支持责任追溯"),
    },
    "analytical-workbench": {
        "keywords": (),
        "theme": {"dashboard": "minimal-light", "dataV": "deep-ocean"},
        "layout": "analysis-balanced",
        "priority": ("kpi", "trend", "comparison", "ranking", "composition", "geospatial", "detail"),
        "principles": ("按数据语义选择图表", "保持清晰阅读路径", "颜色承载含义而非装饰", "复杂分析提供筛选和明细"),
    },
}

_ROLE_ALIASES = {
    "gauge": "kpi", "metric": "kpi", "ohlc": "trend", "waterfall": "trend",
    "correlation": "comparison", "profile": "comparison", "hierarchy": "composition",
    "distribution": "composition", "funnel": "composition", "summary": "detail",
}


def _chart_role(chart: dict[str, Any]) -> str:
    role = str(chart.get("intent") or "").lower()
    return _ROLE_ALIASES.get(role, role or "comparison")


def _choose_grammar(title: str, charts: list[dict[str, Any]]) -> tuple[str, list[str]]:
    text = str(title or "").casefold()
    scores: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}
    for name, grammar in DESIGN_GRAMMARS.items():
        matches = [word for word in grammar["keywords"] if word.casefold() in text]
        scores[name] = len(matches) * 3
        evidence[name] = [f"标题命中“{word}”" for word in matches]
    roles = {_chart_role(chart) for chart in charts}
    if "geospatial" in roles:
        scores["geo-command"] += 2
        evidence["geo-command"].append("存在可靠地域图表")
    if "ranking" in roles:
        scores["retail-operations"] += 1
        evidence["retail-operations"].append("存在排行分析")
    winner = max(scores, key=lambda item: scores[item])
    if scores[winner] == 0:
        winner = "analytical-workbench"
        evidence[winner] = ["未命中特定行业，采用通用分析工作台"]
    return winner, evidence[winner]


def _stable_variant(title: str, grammar: str) -> str:
    variants = ("balanced", "focus-left", "focus-center")
    digest = hashlib.sha256(f"{title}|{grammar}".encode("utf-8")).digest()
    return variants[digest[0] % len(variants)]


def design_dimensions(
    charts: list[dict[str, Any]], busi_type: str, variant: str,
) -> dict[str, Any]:
    roles: dict[str, int] = {}
    for chart in charts:
        role = _chart_role(chart)
        roles[role] = roles.get(role, 0) + 1
    return {
        "audience_mode": "glanceable-command" if busi_type == "dataV" else "interactive-analysis",
        "viewing_distance": "far" if busi_type == "dataV" else "near",
        "density": "compact" if len(charts) <= 6 else "balanced" if len(charts) <= 10 else "rich",
        "reading_path": variant,
        "chart_mix": roles,
        "color_strategy": {
            "categorical": "high-separation-limited-series",
            "sequential": "single-hue-for-magnitude",
            "status": "red-warning-green-success-with-text-or-icon",
        },
        "interaction_strategy": (
            "filters-linkage-drill-details-on-demand"
            if busi_type == "dashboard"
            else "low-interaction-visible-context-kiosk-safe"
        ),
    }


def apply_design_inspiration(
    spec: dict[str, Any],
    *,
    title: str,
    busi_type: str,
    preserve_explicit_theme: bool = False,
) -> dict[str, Any]:
    """Apply an original, data-aware design grammar derived from public exemplars."""
    charts = list(spec.get("charts") or [])
    grammar_name, evidence = _choose_grammar(title, charts)
    grammar = DESIGN_GRAMMARS[grammar_name]
    priority = {role: index for index, role in enumerate(grammar["priority"])}
    indexed = list(enumerate(charts))
    indexed.sort(key=lambda item: (priority.get(_chart_role(item[1]), 99), item[0]))
    charts = [chart for _, chart in indexed]

    filters = ((spec.get("interactions") or {}).get("filters") or [])
    layouts = plan_smart_layouts(
        charts,
        reserved_top_rows=4 if filters else 0,
        archetype=str(grammar["layout"]),
    )
    for chart, layout in zip(charts, layouts):
        chart["layout"] = layout
    spec["charts"] = charts
    if not preserve_explicit_theme:
        spec["theme"] = grammar["theme"][busi_type]
    strategy = describe_layout_strategy(charts)
    variant = _stable_variant(title, grammar_name)
    strategy.update({
        "grammar": grammar_name,
        "archetype": grammar["layout"],
        "variant": variant,
    })
    spec["layout_strategy"] = strategy
    spec["design_inspiration"] = {
        "mode": "principle-derived-original",
        "grammar": grammar_name,
        "selection_evidence": evidence,
        "principles": list(grammar["principles"]),
        "design_dimensions": design_dimensions(charts, busi_type, variant),
        "template_copying": False,
        "external_assets_embedded": False,
        "reference_catalog": "references/design-inspiration.md",
    }
    return spec
