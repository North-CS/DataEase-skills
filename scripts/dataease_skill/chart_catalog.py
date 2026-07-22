from __future__ import annotations

from typing import Any


# DataEase v2.10.25 native type -> captured template with a compatible field-channel shape.
CHART_ADAPTERS: dict[str, dict[str, Any]] = {
    "bar": {"template": "bar", "category": "compare"},
    "bar-stack": {"template": "bar", "category": "compare"},
    "percentage-bar-stack": {"template": "bar", "category": "compare"},
    "bar-group": {"template": "bar", "category": "compare"},
    "bar-horizontal": {"template": "bar", "category": "compare"},
    "bar-stack-horizontal": {"template": "bar", "category": "compare"},
    "line": {"template": "line", "category": "trend"},
    "area": {"template": "line", "category": "trend"},
    "area-stack": {"template": "line", "category": "trend"},
    "pie": {"template": "pie", "category": "distribute"},
    "pie-donut": {"template": "pie", "category": "distribute"},
    "pie-rose": {"template": "pie", "category": "distribute"},
    "pie-donut-rose": {"template": "pie", "category": "distribute"},
    "indicator": {"template": "gauge", "category": "quota", "render": "custom"},
    "gauge": {"template": "gauge", "category": "quota"},
    "table_info": {"template": "table_info", "native_type": "table-info", "category": "table"},
    "table-info": {"template": "table_info", "category": "table"},
    "table-normal": {"template": "table_info", "category": "table"},
    "table-pivot": {"template": "table_info", "category": "table"},
    "t-heatmap": {"template": "table_info", "category": "table"},
    "map": {"template": "bar", "category": "map"},
    "bubble-map": {"template": "bar", "category": "map"},
    "flow-map": {"template": "bar", "category": "map"},
    "heat-map": {"template": "bar", "category": "map"},
    "symbolic-map": {"template": "bar", "category": "map"},
    "scatter": {"template": "bar", "category": "relation"},
    "funnel": {"template": "pie", "category": "relation"},
    "radar": {"template": "bar", "category": "distribute"},
    "treemap": {"template": "pie", "category": "distribute"},
    "word-cloud": {"template": "pie", "category": "distribute"},
    "candle": {"template": "candle", "category": "trend"},
    "waterfall": {"template": "waterfall", "category": "compare"},
}

SUPPORTED_CHART_TYPES = frozenset(CHART_ADAPTERS)


def chart_adapter(chart_type: str) -> dict[str, Any]:
    try:
        return CHART_ADAPTERS[chart_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported chart type: {chart_type}") from exc


def native_chart_type(chart_type: str) -> str:
    adapter = chart_adapter(chart_type)
    return str(adapter.get("native_type") or chart_type)
