from __future__ import annotations

from typing import Any


# DataEase v2.10.25 native type -> captured template with a compatible field-channel shape.
CHART_ADAPTERS: dict[str, dict[str, Any]] = {
    "bar": {"template": "bar", "category": "compare", "max_y_fields": 5},
    "bar-stack": {"template": "bar", "category": "compare", "max_y_fields": 5},
    "percentage-bar-stack": {"template": "bar", "category": "compare", "max_y_fields": 5},
    "bar-group": {"template": "bar", "category": "compare", "max_y_fields": 5},
    "bar-horizontal": {"template": "bar", "category": "compare", "max_y_fields": 5},
    "bar-stack-horizontal": {"template": "bar", "category": "compare", "max_y_fields": 5},
    "line": {"template": "line", "category": "trend", "max_y_fields": 5},
    "area": {"template": "line", "category": "trend", "max_y_fields": 5},
    "area-stack": {"template": "line", "category": "trend", "max_y_fields": 5},
    "pie": {"template": "pie", "category": "distribute"},
    "pie-donut": {"template": "pie", "category": "distribute"},
    "pie-rose": {"template": "pie", "category": "distribute"},
    "pie-donut-rose": {"template": "pie", "category": "distribute"},
    "indicator": {"template": "gauge", "category": "quota", "render": "custom"},
    "gauge": {"template": "gauge", "category": "quota"},
    "table_info": {"template": "table_info", "native_type": "table-info", "category": "table"},
    "table-info": {"template": "table_info", "category": "table"},
    "table-normal": {"template": "table_info", "category": "table"},
    "table-pivot": {
        "template": "table_info", "category": "table",
        "max_y_fields": 10, "preserve_table_axes": True,
    },
    "t-heatmap": {"template": "table_info", "category": "table"},
    "map": {"template": "bar", "category": "map"},
    "bubble-map": {
        "template": "bar", "category": "map",
        "max_y_fields": 2, "secondary_y_channel": "extBubble",
    },
    "flow-map": {"template": "bar", "category": "map"},
    "heat-map": {"template": "bar", "category": "map"},
    "symbolic-map": {"template": "bar", "category": "map"},
    "scatter": {"template": "bar", "category": "relation", "max_y_fields": 5},
    "funnel": {"template": "pie", "category": "relation"},
    "radar": {"template": "bar", "category": "distribute", "max_y_fields": 5},
    "treemap": {"template": "pie", "category": "distribute"},
    "word-cloud": {"template": "pie", "category": "distribute"},
    "candle": {"template": "candle", "category": "trend", "max_y_fields": 4},
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


def apply_native_chart_defaults(view: dict[str, Any], chart_type: str) -> None:
    """Complete DTO fields required by handlers that cannot share the base template verbatim."""
    if chart_type == "indicator":
        for field in view.get("yAxis") or []:
            field["chartType"] = "indicator"
            field["compareCalc"] = {
                "type": "none", "resultData": "percent", "field": None, "custom": None,
            }
        custom_attr = view.setdefault("customAttr", {})
        custom_attr.setdefault("indicator", {
            "show": True, "fontSize": 32, "color": "#5470C6ff",
            "hPosition": "center", "vPosition": "center", "isItalic": False,
            "isBolder": True, "fontFamily": "Microsoft YaHei", "letterSpace": 0,
            "fontShadow": False, "suffixEnable": False, "suffix": "",
            "suffixFontSize": 14, "suffixColor": "#5470C6ff",
        })
        custom_attr.setdefault("indicatorName", {
            "show": True, "fontSize": 16, "color": "#646A73ff",
            "isItalic": False, "isBolder": False, "fontFamily": "Microsoft YaHei",
            "letterSpace": 0, "fontShadow": False, "nameValueSpacing": 8,
            "namePosition": "bottom",
        })
        return

    if chart_type not in {"map", "bubble-map", "heat-map", "flow-map"}:
        return
    geography = " ".join(
        str(field.get(key) or "").lower()
        for field in view.get("xAxis") or []
        for key in ("name", "originName", "description", "dataeaseName")
    )
    china_geo_words = (
        "province", "city", "county", "district", "prefecture",
        "省", "市", "区县", "行政区", "地级",
    )
    if any(word in geography for word in china_geo_words):
        view.setdefault("customAttr", {})["map"] = {"id": "156", "level": "country"}
