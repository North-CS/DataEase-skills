from __future__ import annotations

import re
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


_PROVINCE_WORDS = ("province", "省", "自治区", "直辖市")
_CITY_WORDS = ("city", "城市", "市", "prefecture", "地级")
_COUNTRY_WORDS = ("country", "国家", "全国")
_UNIT_PATTERNS = (
    ("currency", re.compile(r"(元|￥|人民币|rmb|cny|金额|amount|revenue|cost|freight)", re.I)),
    ("hours", re.compile(r"(小时|时效|耗时|时长|hour|duration)", re.I)),
    ("percent", re.compile(r"(%|％|比例|比率|率|percent|ratio)", re.I)),
)


def _field_text(field: dict[str, Any]) -> str:
    return " ".join(str(field.get(key) or "") for key in ("name", "originName", "description")).lower()


def _administrative_scope(fields: list[dict[str, Any]]) -> str:
    """Return the strictest usable administrative scope for a regional China map."""
    text = " ".join(_field_text(field) for field in fields)
    if any(word in text for word in _PROVINCE_WORDS):
        return "province"
    if any(word in text for word in _COUNTRY_WORDS):
        return "country"
    if any(word in text for word in _CITY_WORDS):
        return "city"
    return "unknown"


def _measure_unit(field: dict[str, Any]) -> str | None:
    text = _field_text(field)
    for unit, pattern in _UNIT_PATTERNS:
        if pattern.search(text):
            return unit
    return None


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
    if chart_type == "table-pivot":
        # A grand total across e.g. currency and duration is not meaningful.  DataEase
        # renders it as "-", so hide both total axes instead of publishing a broken table.
        units = {_measure_unit(field) for field in view.get("yAxis") or []}
        units.discard(None)
        if len(units) > 1:
            totals = view.setdefault("customAttr", {}).setdefault("tableTotal", {})
            totals.setdefault("row", {})["showGrandTotals"] = False
            totals.setdefault("col", {})["showGrandTotals"] = False

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
    scope = _administrative_scope(view.get("xAxis") or [])
    if scope == "city":
        raise ValueError(
            f"{chart_type} cannot render city names on the national administrative map; "
            "use symbolic-map only with longitude/latitude fields, or use a ranking chart"
        )
    if scope not in {"province", "country"}:
        raise ValueError(
            f"{chart_type} requires a country/province administrative field; "
            "generic location text is not sufficient for the China map"
        )
    view.setdefault("customAttr", {})["map"] = {"id": "156", "level": "country"}
