from __future__ import annotations

from typing import Any, Iterable


_KPI_WORDS = ("kpi", "指标", "评分", "达成率", "完成率", "增长率", "利润率", "客单价")
_RANK_WORDS = ("排行", "排名", "top", "前十", "前20")


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


def plan_smart_layouts(
    charts: Iterable[dict[str, Any]],
    *,
    canvas_width: int = 1920,
    canvas_height: int = 1080,
    reserved_top_rows: int = 0,
) -> list[dict[str, int]]:
    """Plan semantic 72x36 layouts while preserving the caller's chart order."""
    items = list(charts)
    if not items:
        return []
    roles = [_role(item) for item in items]
    result: list[dict[str, int] | None] = [None] * len(items)
    kpis = [index for index, role in enumerate(roles) if role == "kpi"]
    details = [index for index, role in enumerate(roles) if role == "detail"]
    analysis = [index for index, role in enumerate(roles) if role not in {"kpi", "detail"}]

    if reserved_top_rows < 0 or reserved_top_rows > 12:
        raise ValueError("reserved_top_rows must be between 0 and 12")
    cursor_y = 1 + reserved_top_rows
    if kpis:
        kpi_rows = (len(kpis) + 3) // 4
        heights = _split_height(min(12, max(5, kpi_rows * 5)), kpi_rows)
        for row in range(kpi_rows):
            row_items = kpis[row * 4 : (row + 1) * 4]
            widths = _split_height(72, len(row_items))
            cursor_x = 1
            for index, width in zip(row_items, widths):
                result[index] = _layout(cursor_x, cursor_y, width, heights[row], canvas_width, canvas_height)
                cursor_x += width
            cursor_y += heights[row]

    available_rows = 36 - reserved_top_rows
    detail_height = min(14, max(6, available_rows // max(2, len(details) + 1))) if details else 0
    detail_total = detail_height * len(details)
    remaining_height = max(1, 37 - cursor_y - detail_total)

    if analysis:
        rows: list[list[int]] = []
        pending = list(analysis)
        while pending:
            lead = pending.pop(0)
            row = [lead]
            lead_role = roles[lead]
            if pending:
                if lead_role == "trend":
                    companion = next((item for item in pending if roles[item] in {"composition", "ranking"}), None)
                    if companion is not None:
                        pending.remove(companion)
                        row.append(companion)
                elif len(pending) > 0:
                    row.append(pending.pop(0))
            rows.append(row)
        row_heights = _split_height(remaining_height, len(rows))
        for row, height in zip(rows, row_heights):
            if len(row) == 1:
                widths = [72]
            elif roles[row[0]] == "trend":
                widths = [48, 24]
            elif roles[row[1]] == "trend":
                widths = [24, 48]
            elif "composition" in {roles[row[0]], roles[row[1]]}:
                widths = [48, 24] if roles[row[1]] == "composition" else [24, 48]
            else:
                widths = [36, 36]
            cursor_x = 1
            for index, width in zip(row, widths):
                result[index] = _layout(cursor_x, cursor_y, width, height, canvas_width, canvas_height)
                cursor_x += width
            cursor_y += height

    for index in details:
        result[index] = _layout(1, cursor_y, 72, detail_height, canvas_width, canvas_height)
        cursor_y += detail_height

    return [item for item in result if item is not None]


def describe_layout_strategy(charts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    roles = [_role(item) for item in charts]
    return {
        "engine": "semantic-v1",
        "roles": roles,
        "rules": ["KPI 优先置顶", "趋势图优先宽屏", "构成图作为侧栏", "明细表横跨底部"],
    }
