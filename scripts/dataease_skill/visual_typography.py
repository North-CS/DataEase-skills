from __future__ import annotations

from typing import Any


def text_units(value: Any) -> float:
    """Estimate rendered width: CJK/wide characters count more than Latin text."""
    return sum(2.0 if ord(char) > 255 else 1.0 for char in str(value or ""))


def compact_title(value: Any, max_units: int) -> str:
    title = str(value or "").strip()
    if text_units(title) <= max_units:
        return title
    budget = max(6, max_units - 1)
    result: list[str] = []
    used = 0.0
    for char in title:
        width = 2.0 if ord(char) > 255 else 1.0
        if used + width > budget:
            break
        result.append(char)
        used += width
    return "".join(result).rstrip(" ·_-") + "…"


def responsive_typography(
    chart_type: str,
    title: Any,
    *,
    width: int,
    height: int,
    dimension_count: int = 0,
    measure_count: int = 0,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Allocate a deterministic typography budget from component geometry and density."""
    policy = policy if isinstance(policy, dict) else {}
    mode = str(policy.get("mode") or "auto")
    if mode not in {"auto", "dense", "presentation", "compact"}:
        mode = "auto"
    scale = float(policy.get("scale") or 1.0)
    scale = max(0.75, min(1.5, scale))
    mode_scale = {"auto": 1.0, "dense": 0.88, "compact": 0.92, "presentation": 1.18}[mode]
    scale *= mode_scale
    safe_width = max(240, int(width or 0))
    safe_height = max(100, int(height or 0))
    title_units = text_units(title)

    title_size = 16
    if safe_width < 520 or safe_height < 180 or title_units > 34:
        title_size = 14
    if safe_width < 360 or title_units > 52:
        title_size = 12
    title_size = round(title_size * scale)
    title_size = max(int(policy.get("min_font_size") or 10), title_size)
    title_size = min(int(policy.get("max_title_font_size") or 22), title_size)
    max_title_units = max(14, min(64, int((safe_width - 36) / max(7, title_size * 0.72))))

    dense = dimension_count + measure_count >= 4
    axis_size = round((10 if safe_width < 520 or dense else 12) * scale)
    legend_size = round((10 if safe_width < 600 or dense else 12) * scale)
    label_size = round((10 if safe_width < 520 or dense else 12) * scale)

    indicator_size = max(20, min(48, round(safe_height * 0.22 * scale)))
    indicator_name_size = max(10, min(18, round(safe_height * 0.085 * scale)))
    if title_units > max_title_units:
        indicator_size = max(22, indicator_size - 2)

    chart_key = str(chart_type or "").lower()
    legend_show = chart_key not in {"indicator", "gauge", "table", "table_info", "table-pivot"}
    if isinstance(policy.get("legend_show"), bool):
        legend_show = policy["legend_show"]
    compact_titles = policy.get("compact_titles", True) is not False
    return {
        "full_title": str(title or "").strip(),
        "display_title": compact_title(title, max_title_units) if compact_titles else str(title or "").strip(),
        "title_font_size": title_size,
        "axis_font_size": axis_size,
        "legend_font_size": legend_size,
        "label_font_size": label_size,
        "indicator_font_size": indicator_size,
        "indicator_name_font_size": indicator_name_size,
        "legend_show": legend_show,
        "inner_padding_top": max(8, min(14, int(safe_height * 0.06))),
        "policy": {"mode": mode, "scale": round(scale, 3)},
    }
