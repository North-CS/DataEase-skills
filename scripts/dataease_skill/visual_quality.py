from __future__ import annotations

from typing import Any

from .theme_engine import resolve_theme
from .layout_planner import plan_smart_layouts
from .design_inspiration import design_dimensions


COMPLEXITY_LIMITS = {"compact": 6, "standard": 10, "rich": 16}


def _selection_role(chart: dict[str, Any]) -> str:
    intent = str(chart.get("intent") or "").lower()
    if intent in {"kpi", "metric", "gauge"}:
        return "kpi"
    if intent in {"detail", "summary", "table"}:
        return "detail"
    if intent in {"ohlc", "waterfall"}:
        return "trend"
    if intent in {"profile", "correlation"}:
        return "comparison"
    if intent in {"hierarchy", "distribution", "funnel"}:
        return "composition"
    return intent or "comparison"


def _select_balanced(charts: list[dict[str, Any]], limit: int, level: str) -> list[dict[str, Any]]:
    detail = next((item for item in reversed(charts) if _selection_role(item) == "detail"), None)
    budget = limit - (1 if detail else 0)
    selected: list[dict[str, Any]] = []
    kpi_cap = {"compact": 2, "standard": 3, "rich": 4}[level]
    selected.extend([item for item in charts if _selection_role(item) == "kpi"][:min(kpi_cap, budget)])

    represented = {_selection_role(item) for item in selected}
    selected_ids = {id(item) for item in selected}
    for item in charts:
        role = _selection_role(item)
        if item is detail or id(item) in selected_ids or role in represented:
            continue
        selected.append(item)
        selected_ids.add(id(item))
        represented.add(role)
        if len(selected) == budget:
            break
    for item in charts:
        if len(selected) == budget:
            break
        if item is not detail and id(item) not in selected_ids:
            selected.append(item)
            selected_ids.add(id(item))
    if detail:
        selected.append(detail)
    return selected[:limit]


def apply_complexity_profile(spec: dict[str, Any], level: str) -> dict[str, Any]:
    """Bound planner output without asking a model to choose/delete individual charts."""
    if level not in COMPLEXITY_LIMITS:
        raise ValueError(f"unknown visual complexity: {level}")
    charts = list(spec.get("charts") or [])
    limit = COMPLEXITY_LIMITS[level]
    if len(charts) > limit:
        charts = _select_balanced(charts, limit, level)
    filters = ((spec.get("interactions") or {}).get("filters") or [])
    layouts = plan_smart_layouts(charts, reserved_top_rows=4 if filters else 0)
    for chart, layout in zip(charts, layouts):
        chart["layout"] = layout
    spec["charts"] = charts
    spec["complexity"] = {
        "profile": level,
        "component_limit": limit,
        "component_count": len(charts),
        "model_selection_required": False,
    }
    inspiration = spec.get("design_inspiration")
    strategy = spec.get("layout_strategy")
    if isinstance(inspiration, dict) and isinstance(strategy, dict):
        inspiration["design_dimensions"] = design_dimensions(
            charts,
            str(spec.get("kind") or "dashboard"),
            str(strategy.get("variant") or "balanced"),
        )
    return spec


def score_visual_spec(spec: dict[str, Any], *, skill_root) -> dict[str, Any]:
    """Return deterministic, text-only readiness checks; no image understanding is required."""
    charts = spec.get("charts") if isinstance(spec.get("charts"), list) else []
    chart_types = [str(item.get("type") or "") for item in charts if isinstance(item, dict)]
    datasets = {
        str(item.get("dataset_name"))
        for item in charts if isinstance(item, dict) and item.get("dataset_name")
    }
    interactions = spec.get("interactions") if isinstance(spec.get("interactions"), dict) else {}
    filters = interactions.get("filters") if isinstance(interactions.get("filters"), list) else []
    theme = resolve_theme(
        spec.get("theme") or ("neon-dark" if spec.get("kind") == "dataV" else "business-light"),
        skill_root=skill_root,
    )
    checks = [
        {
            "id": "title",
            "ok": bool(str(spec.get("title") or "").strip()),
            "weight": 10,
            "message": "标题已设置" if spec.get("title") else "缺少标题",
        },
        {
            "id": "chart_count",
            "ok": 3 <= len(charts) <= 16,
            "weight": 20,
            "message": f"组件数量 {len(charts)}（建议 3–16）",
        },
        {
            "id": "chart_diversity",
            "ok": len(set(chart_types)) >= min(3, len(charts)),
            "weight": 15,
            "message": f"图表类型 {len(set(chart_types))} 种",
        },
        {
            "id": "dataset_binding",
            "ok": bool(datasets) and all(
                isinstance(item, dict) and item.get("dataset_name") for item in charts
            ),
            "weight": 20,
            "message": f"绑定 {len(datasets)} 个数据集",
        },
        {
            "id": "field_binding",
            "ok": all(
                isinstance(item, dict)
                and isinstance(item.get("x_axis"), list)
                and isinstance(item.get("y_axis"), list)
                for item in charts
            ),
            "weight": 15,
            "message": "所有图表均声明轴字段",
        },
        {
            "id": "theme_accessibility",
            "ok": bool(theme["accessibility"]["wcag_aa_normal_text"]),
            "weight": 10,
            "message": f"文字对比度 {theme['contrast_ratio']}:1",
        },
        {
            "id": "interaction",
            "ok": bool(filters) or len(charts) < 3,
            "weight": 10,
            "message": f"查询条件 {len(filters)} 个",
        },
    ]
    score = sum(item["weight"] for item in checks if item["ok"])
    failures = [item["id"] for item in checks if not item["ok"]]
    return {
        "score": score,
        "grade": "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D",
        "ready": score >= 80 and not {"title", "dataset_binding", "field_binding"} & set(failures),
        "checks": checks,
        "failed_checks": failures,
        "requires_multimodal_model": False,
        "visual_review": "optional_enhancement",
        "resolved_theme": {
            key: theme[key] for key in (
                "name", "background", "accent", "text", "colors",
                "contrast_ratio", "accessibility",
            )
        },
    }
