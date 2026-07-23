from __future__ import annotations

import math
from typing import Any, Iterable

from .visual_typography import text_units


_KPI_WORDS = ("kpi", "指标", "评分", "达成率", "完成率", "增长率", "利润率", "客单价")
_RANK_WORDS = ("排行", "排名", "top", "前十", "前20")

_NO_AXIS_TYPES = {
    "indicator", "gauge", "pie", "pie-donut", "donut", "funnel", "treemap",
    "word-cloud", "map", "bubble-map", "flow-map", "heat-map", "symbolic-map",
}
_TABLE_TYPES = {"table", "table_info", "table-info", "table-pivot", "pivot"}
_MAP_TYPES = {"map", "bubble-map", "flow-map", "heat-map", "symbolic-map"}
_COMPACT_TYPES = {"indicator", "gauge"}
_COMPOSITION_TYPES = {"pie", "pie-donut", "donut", "funnel", "treemap", "word-cloud"}


def _role(chart: dict[str, Any]) -> str:
    intent = str(chart.get("intent") or "").lower()
    chart_type = str(chart.get("type") or "").lower().replace("-", "_")
    title = str(chart.get("title") or "").lower()
    if intent in {"detail", "table"} or chart_type in {"table", "table_info"}:
        return "detail"
    if intent in {"kpi", "metric", "gauge"} or chart_type in {"gauge", "indicator"}:
        return "kpi"
    if any(word in title for word in _KPI_WORDS) and len(chart.get("y_axis") or []) <= 1:
        return "kpi"
    if intent in {"trend", "ohlc", "waterfall"} or chart_type in {"line", "area", "candle", "waterfall"}:
        return "trend"
    if intent in {"composition", "distribution"} or chart_type in {"pie", "donut", "funnel"}:
        return "composition"
    if intent in {"geospatial", "map"} or chart_type in {
        "map", "bubble_map", "flow_map", "heat_map", "symbolic_map",
    }:
        return "geospatial"
    if intent == "ranking" or any(word in title for word in _RANK_WORDS):
        return "ranking"
    return "comparison"


def _layout(x: int, y: int, width: int, height: int, canvas_width: int, canvas_height: int) -> dict[str, int]:
    return {
        "x": x,
        "y": y,
        "sizeX": width,
        "sizeY": height,
        "left": round((x - 1) * canvas_width / 72),
        "top": round((y - 1) * canvas_height / 36),
        "width": round(width * canvas_width / 72),
        "height": round(height * canvas_height / 36),
    }


def _split_height(total: int, rows: int) -> list[int]:
    base, remainder = divmod(max(total, rows), rows)
    return [base + (1 if index < remainder else 0) for index in range(rows)]


def chart_space_requirements(chart: dict[str, Any]) -> dict[str, Any]:
    """Estimate one chart's geometry from content, rendering traits and optional preview stats."""
    chart_type = str(chart.get("type") or "").lower().replace("_", "-")
    dimensions = len(chart.get("x_axis") or []) + len(chart.get("x_axis_ext") or [])
    measures = len(chart.get("y_axis") or []) + len(chart.get("y_axis_ext") or [])
    density = chart.get("data_density") if isinstance(chart.get("data_density"), dict) else {}
    category_count = max(0, int(density.get("category_count") or chart.get("category_count") or 0))
    series_count = max(0, int(density.get("series_count") or chart.get("series_count") or measures))
    legend_items = max(0, int(density.get("legend_items") or chart.get("legend_items") or series_count))
    row_count = max(0, int(density.get("row_count") or chart.get("row_count") or 0))
    title_width = text_units(chart.get("title"))
    has_axes = chart_type not in _NO_AXIS_TYPES and chart_type not in _TABLE_TYPES
    has_legend = chart_type not in _COMPACT_TYPES and chart_type not in _TABLE_TYPES

    min_width = 18
    preferred_width = 24
    max_width = 72
    preferred_height = 180
    if chart_type in _TABLE_TYPES:
        min_width, preferred_width, preferred_height = 48, 72, 300
    elif chart_type in _MAP_TYPES:
        min_width, preferred_width, preferred_height = 36, 48, 300
    elif chart_type in _COMPACT_TYPES:
        min_width, preferred_width, preferred_height = 16, 18, 180
    elif chart_type in _COMPOSITION_TYPES:
        min_width, preferred_width, preferred_height = 22, 28, 240
    elif has_axes:
        min_width, preferred_width, preferred_height = 28, 36, 260

    if title_width > 32:
        min_width += 4
        preferred_width += 6
        preferred_height += 24
    if category_count > 12:
        preferred_width += min(18, (category_count - 12 + 5) // 6 * 3)
        preferred_height += min(100, (category_count - 12) * 3)
    if series_count > 3:
        preferred_width += min(12, (series_count - 3) * 2)
        preferred_height += min(72, (series_count - 3) * 12)
    if legend_items > 6 and has_legend:
        preferred_height += min(72, ((legend_items + 5) // 6 - 1) * 24)
    if dimensions + measures > 4:
        preferred_width += min(12, (dimensions + measures - 4) * 2)
    if chart_type in _TABLE_TYPES and row_count:
        preferred_height += min(180, max(0, min(row_count, 12) - 5) * 18)

    override = chart.get("layout_constraints")
    if isinstance(override, dict):
        min_width = int(override.get("min_width") or min_width)
        preferred_width = int(override.get("preferred_width") or preferred_width)
        max_width = int(override.get("max_width") or max_width)
        preferred_height = int(override.get("preferred_height") or preferred_height)
    min_width = max(12, min(72, min_width))
    preferred_width = max(min_width, min(72, preferred_width))
    max_width = max(preferred_width, min(72, max_width))
    return {
        "min_width": min_width,
        "preferred_width": preferred_width,
        "max_width": max_width,
        "min_height": max(120, min(220, round(preferred_height * 0.6))),
        "preferred_height": max(120, preferred_height),
        "has_axes": has_axes,
        "has_legend": has_legend,
        "density_source": "preview" if density else "metadata-estimate",
        "category_count": category_count,
        "series_count": series_count,
        "legend_items": legend_items,
    }


def _pack_rows(requirements: list[dict[str, Any]]) -> list[list[int]]:
    """Pack in reading order, using each component's minimum and preferred width."""
    rows: list[list[int]] = []
    current: list[int] = []
    min_used = 0
    preferred_used = 0
    for index, requirement in enumerate(requirements):
        next_min = min_used + requirement["min_width"]
        next_preferred = preferred_used + requirement["preferred_width"]
        should_wrap = bool(current) and (
            len(current) >= 4
            or next_min > 72
            or (preferred_used >= 48 and next_preferred > 84)
        )
        if should_wrap:
            rows.append(current)
            current, min_used, preferred_used = [], 0, 0
        current.append(index)
        min_used += requirement["min_width"]
        preferred_used += requirement["preferred_width"]
    if current:
        rows.append(current)
    return rows


def _allocate_widths(row: list[int], requirements: list[dict[str, Any]]) -> list[int]:
    widths = [requirements[index]["min_width"] for index in row]
    remaining = 72 - sum(widths)
    while remaining > 0:
        candidates = [
            position for position, index in enumerate(row)
            if widths[position] < requirements[index]["preferred_width"]
        ] or [
            position for position, index in enumerate(row)
            if widths[position] < requirements[index]["max_width"]
        ]
        if not candidates:
            break
        for position in candidates:
            if remaining <= 0:
                break
            widths[position] += 1
            remaining -= 1
    if remaining > 0:
        widths[-1] += remaining
    return widths


def _row_pixel_height(
    row: list[int], widths: list[int], requirements: list[dict[str, Any]],
) -> int:
    heights = []
    for index, width in zip(row, widths):
        requirement = requirements[index]
        compression = max(1.0, requirement["preferred_width"] / max(width, 1))
        heights.append(round(requirement["preferred_height"] * min(1.45, compression)))
    return max(heights)


def _grid_heights(
    pixel_heights: list[int],
    minimum_pixel_heights: list[int],
    available_rows: int,
    canvas_height: int,
) -> list[int]:
    if not pixel_heights:
        return []
    minimums = [
        max(1, math.ceil(height * 36 / max(canvas_height, 1)))
        for height in minimum_pixel_heights
    ]
    if available_rows < sum(minimums):
        # Preserve valid, collision-free geometry so the quality report can
        # explain the capacity shortfall. The apply gate rejects this layout.
        return _split_height(available_rows, len(pixel_heights))
    total = sum(pixel_heights)
    raw = [available_rows * height / total for height in pixel_heights]
    result = [max(minimums[index], int(value)) for index, value in enumerate(raw)]
    while sum(result) > available_rows:
        candidates = [
            index for index, value in enumerate(result)
            if value > minimums[index]
        ]
        if not candidates:
            break
        index = max(candidates, key=lambda item: result[item] - raw[item])
        result[index] -= 1
    while sum(result) < available_rows:
        index = max(
            range(len(result)),
            key=lambda item: raw[item] - result[item],
        )
        result[index] += 1
    return result


def validate_layouts(layouts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return deterministic bounds/collision issues for 72x36 DataEase grid layouts."""
    items = list(layouts)
    issues: list[dict[str, Any]] = []
    boxes: list[tuple[int, int, int, int]] = []
    for index, item in enumerate(items):
        try:
            x, y = int(item["x"]), int(item["y"])
            width, height = int(item["sizeX"]), int(item["sizeY"])
        except (KeyError, TypeError, ValueError):
            issues.append({"type": "invalid_geometry", "index": index})
            boxes.append((0, 0, 0, 0))
            continue
        box = (x, y, x + width - 1, y + height - 1)
        boxes.append(box)
        if x < 1 or y < 1 or width < 1 or height < 1 or box[2] > 72 or box[3] > 36:
            issues.append({"type": "out_of_bounds", "index": index, "box": box})
    for left in range(len(boxes)):
        for right in range(left + 1, len(boxes)):
            a, b = boxes[left], boxes[right]
            if a[2] < a[0] or b[2] < b[0]:
                continue
            if not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]):
                issues.append({"type": "collision", "indexes": [left, right]})
    return issues


def layout_readability_issues(
    charts: Iterable[dict[str, Any]],
    layouts: Iterable[dict[str, Any]],
    *,
    canvas_width: int = 1920,
    canvas_height: int = 1080,
) -> list[dict[str, Any]]:
    """Return components whose allocated pixels cannot satisfy their content-derived minimums."""
    issues: list[dict[str, Any]] = []
    for index, (chart, layout) in enumerate(zip(charts, layouts)):
        requirement = chart_space_requirements(chart)
        pixel_width = int(layout["sizeX"]) * canvas_width / 72
        pixel_height = int(layout["sizeY"]) * canvas_height / 36
        minimum_width = requirement["min_width"] * canvas_width / 72
        minimum_height = requirement["min_height"]
        if pixel_width + 1 < minimum_width or pixel_height < minimum_height:
            issues.append({
                "index": index,
                "type": chart.get("type"),
                "pixel_width": round(pixel_width),
                "pixel_height": round(pixel_height),
                "minimum_width": round(minimum_width),
                "minimum_height": round(minimum_height),
            })
    return issues


def recommended_dashboard_height(
    charts: Iterable[dict[str, Any]],
    *,
    reserved_top_rows: int = 0,
    base_height: int = 1080,
) -> int:
    """Recommend a scrollable dashboard height that keeps analytical charts readable."""
    items = list(charts)
    requirements = [chart_space_requirements(item) for item in items]
    rows = _pack_rows(requirements)
    content_height = sum(
        _row_pixel_height(row, _allocate_widths(row, requirements), requirements)
        for row in rows
    )
    available_rows = max(1, 36 - reserved_top_rows)
    required = round(content_height * 36 / available_rows)
    if required <= base_height:
        return base_height
    return min(4096, ((required + 119) // 120) * 120)


def plan_smart_layouts(
    charts: Iterable[dict[str, Any]],
    *,
    canvas_width: int = 1920,
    canvas_height: int = 1080,
    reserved_top_rows: int = 0,
    archetype: str | None = None,
) -> list[dict[str, int]]:
    """Plan semantic 72x36 layouts while preserving the caller's chart order."""
    items = list(charts)
    if not items:
        return []
    if reserved_top_rows < 0 or reserved_top_rows > 12:
        raise ValueError("reserved_top_rows must be between 0 and 12")
    requirements = [chart_space_requirements(item) for item in items]
    rows = _pack_rows(requirements)
    widths_by_row = [_allocate_widths(row, requirements) for row in rows]
    pixel_heights = [
        _row_pixel_height(row, widths, requirements)
        for row, widths in zip(rows, widths_by_row)
    ]
    minimum_pixel_heights = [
        max(requirements[index]["min_height"] for index in row)
        for row in rows
    ]
    heights = _grid_heights(
        pixel_heights,
        minimum_pixel_heights,
        36 - reserved_top_rows,
        canvas_height,
    )
    result: list[dict[str, int] | None] = [None] * len(items)
    cursor_y = 1 + reserved_top_rows
    for row, widths, height in zip(rows, widths_by_row, heights):
        cursor_x = 1
        for index, width in zip(row, widths):
            result[index] = _layout(
                cursor_x, cursor_y, width, height, canvas_width, canvas_height,
            )
            cursor_x += width
        cursor_y += height

    planned = [item for item in result if item is not None]
    issues = validate_layouts(planned)
    if issues:
        raise RuntimeError(f"layout solver produced invalid geometry: {issues[:3]}")
    return planned


def describe_layout_strategy(charts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(charts)
    roles = [_role(item) for item in items]
    requirements = [chart_space_requirements(item) for item in items]
    return {
        "engine": "constraint-v3",
        "roles": roles,
        "requirements": requirements,
        "rules": [
            "按标题、字段、类别、系列、图例和行数估算组件空间",
            "根据最小/理想/最大宽度进行全局行打包",
            "按内容高度比例分配画布并保证无碰撞",
            "缺少预览统计时降级使用字段元数据估算",
        ],
    }
