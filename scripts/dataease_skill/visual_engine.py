import base64
import copy
import json
import mimetypes
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from .layout_planner import plan_smart_layouts, recommended_dashboard_height, validate_layouts
from .field_binding import bind_field_metadata
from .chart_catalog import (
    SUPPORTED_CHART_TYPES, apply_native_chart_defaults, chart_adapter, native_chart_type,
)
from .interaction_planner import build_native_link_jump_payloads, build_query_component, normalize_interactions, shared_linkages
from .theme_engine import BUILTIN_THEMES, color_with_alpha, resolve_theme
from .visual_typography import responsive_typography

from .visual_base import DataEaseChartEngine


class MultiDataEaseChartEngine(DataEaseChartEngine):
    """Compose template-backed charts into dashboard or DataV canvases."""

    NEON_COLORS = [
        "#00D9FF", "#7C5CFF", "#20E3B2", "#FFB347", "#FF5DA2",
        "#4D96FF", "#9DFFB0", "#A78BFA", "#22D3EE",
    ]
    SUPPORTED_AGGREGATIONS = {"sum", "avg", "max", "min", "count", "count_distinct", "last", "first", "none", "median", "stdev", "variance"}
    SUPPORTED_CHART_TYPES = SUPPORTED_CHART_TYPES
    THEMES = BUILTIN_THEMES

    def _theme(self, theme: Any) -> dict[str, Any]:
        return resolve_theme(theme, skill_root=Path(__file__).resolve().parents[2])

    def _asset_data_uri(self, configured_path: str) -> str:
        if not configured_path:
            return ""
        path = Path(configured_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        if not path.is_file():
            print(f"Warning: dashboard background not found, using theme color: {path}", file=sys.stderr)
            return ""
        mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _apply_canvas_theme(self, canvas: dict[str, Any], theme: Any) -> dict[str, Any]:
        palette = self._theme(theme)
        if not palette["dark"]:
            canvas.update({"backgroundColor": palette["background"], "color": palette["text"]})
            canvas.setdefault("dashboard", {}).update({"themeColor": "light"})
            canvas.setdefault("component", {}).setdefault("chartTitle", {}).update({"color": palette["text"]})
            canvas["component"].setdefault("chartColor", {}).setdefault("basicStyle", {}).update({
                "colors": palette["colors"]
            })
            return canvas
        canvas.update({
            "screenAdaptor": "widthFirst",
            "dashboardAdaptor": "keepHeightAndWidth",
            "backgroundColorSelect": True,
            "backgroundImageEnable": False,
            "backgroundType": "backgroundColor",
            "background": "",
            "backgroundColor": palette["background"],
            "color": palette["text"],
            "fontFamily": "Microsoft YaHei",
            "scale": 100,
            "scaleWidth": 100,
            "scaleHeight": 100,
        })
        background_path = str(
            palette.get("background_image")
            or os.environ.get("DATAEASE_BACKGROUND_IMAGE", "").strip()
        )
        background = self._asset_data_uri(background_path)
        if background:
            canvas["backgroundImageEnable"] = True
            canvas["background"] = background
        canvas.setdefault("dashboard", {}).update({
            "gap": "no", "gapSize": 0, "showGrid": False, "themeColor": "dark"
        })
        component = canvas.setdefault("component", {})
        component.setdefault("chartTitle", {}).update({
            "show": True, "fontSize": 18, "isBolder": True, "color": palette["text"]
        })
        component.setdefault("chartColor", {}).setdefault("basicStyle", {}).update({
            "colors": palette["colors"],
            "gradient": True,
            "alpha": 92,
            "areaBaseColor": "rgba(3,12,29,0.35)",
            "areaBorderColor": palette["accent"],
        })
        component.setdefault("chartCommonStyle", {}).update({
            "backgroundColorSelect": True,
            "backdropFilterEnable": True,
            "backdropFilter": 8,
            "backgroundImageEnable": False,
            "backgroundColor": "rgba(3,12,29,0.58)",
            "innerImageColor": palette["accent"],
        })
        return canvas

    def _apply_component_theme(
        self, component: dict[str, Any], view_info: dict[str, Any], chart_type: str, theme: Any,
        typography: dict[str, Any] | None = None, component_count: int = 1,
    ) -> None:
        palette = self._theme(theme)
        if not palette["dark"]:
            custom_attr = view_info.setdefault("customAttr", {})
            custom_attr.setdefault("basicStyle", {}).update({
                "colors": palette["colors"], "colorScheme": "custom", "gradient": False, "alpha": 100,
                "areaBaseColor": palette["background"], "areaBorderColor": palette["accent"],
            })
            custom_attr.setdefault("misc", {}).update({
                "nameFontColor": palette["text"], "valueFontColor": palette["accent"],
            })
            custom_attr.setdefault("label", {}).update({"color": palette["text"], "fontSize": 12})
            custom_attr.setdefault("tooltip", {}).update({
                "color": palette["text"], "backgroundColor": "#FFFFFF",
            })
            custom_attr.setdefault("tableHeader", {}).update({
                "tableHeaderBgColor": palette["accent"],
                "tableHeaderCornerBgColor": palette["accent"],
                "tableHeaderColBgColor": palette["accent"],
                "tableHeaderFontColor": "#FFFFFF",
                "tableHeaderCornerFontColor": "#FFFFFF",
                "tableHeaderColFontColor": "#FFFFFF",
            })
            custom_attr.setdefault("tableCell", {}).update({
                "tableItemBgColor": palette["background"],
                "tableFontColor": palette["text"],
            })
            self._apply_responsive_typography(component, view_info, chart_type, typography)
            return
        dense = component_count > 8
        component.setdefault("style", {}).update({
            "borderActive": True,
            "borderWidth": 1,
            "borderRadius": 8 if dense else 14,
            "borderColor": color_with_alpha(palette["accent"], 0.42 if dense else 0.78),
        })
        component["commonBackground"] = {
            "backgroundColorSelect": True,
            "backdropFilterEnable": True,
            "backgroundImageEnable": False,
            "backgroundType": "innerImage",
            "innerImage": "board/board_1.svg",
            "outerImage": None,
            "innerPadding": {"mode": "uniform", "top": 9 if dense else 14},
            "borderRadius": {"mode": "uniform", "topLeft": 8 if dense else 14},
            "backdropFilter": 4 if dense else 8,
            "backgroundColor": "rgba(3,12,29,0.54)" if dense else "rgba(3,12,29,0.62)",
            "innerImageColor": palette["accent"],
        }
        custom_attr = view_info.setdefault("customAttr", {})
        custom_attr.setdefault("basicStyle", {}).update({
            "colors": palette["colors"],
            "colorScheme": "custom",
            "gradient": True,
            "alpha": 94,
            "lineWidth": 3,
            "lineSmooth": True,
            "lineSymbolSize": 6,
            "radiusColumnBar": "roundAngle",
            "columnBarRightAngleRadius": 8,
            "columnWidthRatio": 58,
            "barWidth": 34,
            "radius": 76,
            "innerRadius": 52,
            "tableBorderColor": color_with_alpha(palette["accent"], 0.28),
            "tableScrollBarColor": color_with_alpha(palette["accent"], 0.45),
        })
        custom_attr.setdefault("misc", {}).update({
            "nameFontColor": palette["text"], "valueFontColor": palette["accent"],
        })
        if chart_type == "indicator":
            custom_attr.setdefault("indicator", {}).update({
                "color": f"{palette['accent']}FF", "suffixColor": f"{palette['accent']}FF",
            })
            custom_attr.setdefault("indicatorName", {}).update({
                "color": f"{palette['text']}FF",
            })
        label = custom_attr.setdefault("label", {})
        label.update({"color": palette["text"], "fontSize": 12})
        if chart_type in {"pie", "pie-donut"}:
            label.update({"show": True, "position": "outside", "showProportion": True})
        if chart_type == "candle":
            custom_attr.setdefault("basicStyle", {}).update({
                "candleUpColor": "#EF5350",
                "candleDownColor": "#26A69A",
                "candleLineColor": color_with_alpha(palette["accent"], 0.48),
            })
        if chart_type == "gauge":
            custom_attr.setdefault("misc", {}).update({
                "valueFontColor": palette["accent"],
                "nameFontColor": palette["text"],
                "gaugeStartAngle": 225,
                "gaugeEndAngle": -45,
            })
        if chart_type == "waterfall":
            custom_attr.setdefault("basicStyle", {}).update({
                "waterfallIncreaseColor": "#EF5350",
                "waterfallDecreaseColor": "#26A69A",
                "waterfallTotalColor": palette["accent"],
            })
        custom_attr.setdefault("tooltip", {}).update({
            "color": palette["text"], "backgroundColor": color_with_alpha(palette["background"], 0.94)
        })
        custom_attr.setdefault("tableHeader", {}).update({
            "tableHeaderBgColor": color_with_alpha(palette["accent"], 0.20),
            "tableHeaderCornerBgColor": color_with_alpha(palette["accent"], 0.24),
            "tableHeaderColBgColor": color_with_alpha(palette["accent"], 0.20),
            "tableHeaderFontColor": palette["text"],
            "tableHeaderCornerFontColor": palette["text"],
            "tableHeaderColFontColor": palette["text"],
        })
        custom_attr.setdefault("tableCell", {}).update({
            "tableItemBgColor": "rgba(3,12,29,0.18)",
            "tableItemSubBgColor": color_with_alpha(palette["accent"], 0.08),
            "tableFontColor": palette["text"],
        })
        custom_style = view_info.setdefault("customStyle", {})
        custom_style.setdefault("text", {}).update({
            "show": True,
            "fontSize": 18,
            "isBolder": True,
            "color": palette["text"],
            "remarkBackgroundColor": "rgba(3,12,29,0.85)",
        })
        custom_style.setdefault("legend", {}).update({
            "show": True, "color": palette["text"], "fontSize": 12, "icon": "circle"
        })
        for axis_name in ("xAxis", "yAxis", "yAxisExt", "misc"):
            axis = custom_style.setdefault(axis_name, {})
            axis.update({"color": palette["text"], "fontSize": 12})
            axis.setdefault("axisLabel", {}).update({"color": palette["text"], "fontSize": 12})
            axis.setdefault("axisLine", {}).setdefault("lineStyle", {}).update({
                "color": color_with_alpha(palette["accent"], 0.28), "width": 1
            })
            axis.setdefault("splitLine", {}).setdefault("lineStyle", {}).update({
                "color": "rgba(122,184,224,0.16)", "width": 1
            })
        self._apply_responsive_typography(component, view_info, chart_type, typography)

    @staticmethod
    def _apply_responsive_typography(
        component: dict[str, Any], view_info: dict[str, Any], chart_type: str,
        policy: dict[str, Any] | None = None,
    ) -> None:
        style = component.get("style") if isinstance(component.get("style"), dict) else {}
        width = int(style.get("width") or 0)
        height = int(style.get("height") or 0)
        dimensions = sum(
            len(view_info.get(axis) or []) for axis in ("xAxis", "xAxisExt")
            if isinstance(view_info.get(axis), list)
        )
        measures = sum(
            len(view_info.get(axis) or [])
            for axis in ("yAxis", "yAxisExt", "extStack", "extBubble", "extLabel")
            if isinstance(view_info.get(axis), list)
        )
        typography = responsive_typography(
            chart_type,
            view_info.get("title"),
            width=width,
            height=height,
            dimension_count=dimensions,
            measure_count=measures,
            policy=policy,
        )
        full_title = typography["full_title"]
        view_info["title"] = typography["display_title"]
        custom_style = view_info.setdefault("customStyle", {})
        custom_style.setdefault("text", {}).update({
            "show": True,
            "fontSize": typography["title_font_size"],
            "remarkShow": False,
            "remark": full_title,
        })
        custom_style.setdefault("legend", {}).update({
            "show": typography["legend_show"],
            "fontSize": typography["legend_font_size"],
        })
        for axis_name in ("xAxis", "yAxis", "yAxisExt", "misc"):
            axis = custom_style.setdefault(axis_name, {})
            axis["fontSize"] = typography["axis_font_size"]
            axis.setdefault("axisLabel", {})["fontSize"] = typography["axis_font_size"]

        custom_attr = view_info.setdefault("customAttr", {})
        custom_attr.setdefault("label", {})["fontSize"] = typography["label_font_size"]
        if chart_type == "indicator":
            custom_attr.setdefault("indicator", {})["fontSize"] = typography["indicator_font_size"]
            custom_attr.setdefault("indicatorName", {})["fontSize"] = typography["indicator_name_font_size"]
        custom_attr.setdefault("tableHeader", {}).update({
            "tableTitleFontSize": typography["label_font_size"],
            "tableTitleHeight": max(28, typography["label_font_size"] * 2 + 8),
        })
        custom_attr.setdefault("tableCell", {}).update({
            "tableItemFontSize": typography["label_font_size"],
            "tableItemHeight": max(28, typography["label_font_size"] * 2 + 8),
        })
        background = component.get("commonBackground")
        if isinstance(background, dict):
            background.setdefault("innerPadding", {})["top"] = typography["inner_padding_top"]

    @staticmethod
    def _flatten_params(value: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(item, dict):
                result.update(MultiDataEaseChartEngine._flatten_params(item))
            elif not key.startswith("_"):
                result[key] = item
        return result

    @staticmethod
    def _update_field_names(obj: Any, target_id: str, new_name: str) -> None:
        if isinstance(obj, dict):
            if str(obj.get("id")) == str(target_id):
                for key in ("name", "description", "originName"):
                    if key in obj or key == "name":
                        obj[key] = new_name
                if "dbFieldName" in obj:
                    obj["dbFieldName"] = None
                for key in ("optionLabel", "optionShowName"):
                    if key in obj:
                        suffix = obj[key][obj[key].find("("):] if "(" in obj[key] else ""
                        obj[key] = new_name + suffix
            for item in obj.values():
                MultiDataEaseChartEngine._update_field_names(item, target_id, new_name)
        elif isinstance(obj, list):
            for item in obj:
                MultiDataEaseChartEngine._update_field_names(item, target_id, new_name)

    @staticmethod
    def _update_field_aggregation(obj: Any, target_id: str, aggregation: str) -> None:
        if aggregation not in MultiDataEaseChartEngine.SUPPORTED_AGGREGATIONS:
            raise ValueError(f"Unsupported DataEase aggregation: {aggregation}")
        if isinstance(obj, dict):
            if str(obj.get("id")) == str(target_id) and "summary" in obj:
                obj["summary"] = aggregation
            for item in obj.values():
                MultiDataEaseChartEngine._update_field_aggregation(item, target_id, aggregation)
        elif isinstance(obj, list):
            for item in obj:
                MultiDataEaseChartEngine._update_field_aggregation(item, target_id, aggregation)

    @staticmethod
    def _replace_template_names(obj: Any, x_names: list[str], y_names: list[str]) -> None:
        if not x_names or not y_names:
            return
        replacements = {"访问平台": x_names[0], "访问次数": y_names[0], "浏览量": y_names[0]}
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, str):
                    for old, new in replacements.items():
                        value = value.replace(old, new)
                    obj[key] = value
                else:
                    MultiDataEaseChartEngine._replace_template_names(value, x_names, y_names)
        elif isinstance(obj, list):
            for item in obj:
                MultiDataEaseChartEngine._replace_template_names(item, x_names, y_names)

    def extract_chart_payload(
        self,
        chart_type: str,
        dataset_id: str,
        x_names: list[str],
        y_names: list[str],
        view_id: str,
        layout: dict[str, Any],
        title: str | None = None,
        y_aggregations: list[str] | None = None,
        secondary_y_axis: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        adapter = chart_adapter(chart_type)
        max_y_fields = int(adapter.get("max_y_fields") or 1)
        if len(y_names) > max_y_fields:
            raise ValueError(
                f"{chart_type} supports at most {max_y_fields} y_axis fields; "
                f"received {len(y_names)}"
            )
        template_type = str(adapter["template"])
        template_dir = Path(__file__).resolve().parents[2] / "templates" / f"chart_{template_type}"
        if not template_dir.exists():
            raise FileNotFoundError(f"Unsupported chart template: {chart_type}")
        template = (template_dir / "template.j2").read_text(encoding="utf-8")
        raw_params = json.loads((template_dir / "params.json").read_text(encoding="utf-8"))
        dataset_ctx = self.get_dataset_ctx(dataset_id, x_names, y_names)
        context = {**self._flatten_params(raw_params), **dataset_ctx, "VIEW_ID": view_id, "SCENE_ID": "0"}

        def replace(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            return str(context.get(key, match.group(0)))

        payload = json.loads(re.sub(r"\{\{\s*(\w+)\s*\}\}", replace, template))
        view_info = payload.get("canvasViewInfo", {}).get(view_id)
        if not view_info:
            raise ValueError(f"Rendered template does not contain view {view_id}")
        if title:
            view_info["title"] = title
        for index, name in enumerate(x_names):
            field_id = dataset_ctx.get(f"XAXIS{'' if index == 0 else index + 1}_FIELD_ID")
            if field_id:
                suffix = "" if index == 0 else str(index + 1)
                bind_field_metadata(view_info, field_id, dataset_ctx[f"XAXIS{suffix}_FIELD_METADATA"])
        for index, name in enumerate(y_names):
            field_id = dataset_ctx.get(f"YAXIS{'' if index == 0 else index + 1}_FIELD_ID")
            if field_id:
                suffix = "" if index == 0 else str(index + 1)
                bind_field_metadata(view_info, field_id, dataset_ctx[f"YAXIS{suffix}_FIELD_METADATA"])
                if y_aggregations and index < len(y_aggregations):
                    self._update_field_aggregation(view_info, field_id, y_aggregations[index])
        def build_axis_fields(
            prototype: dict[str, Any],
            axis: str,
            names: list[str],
            *,
            series_suffix: str | None = None,
            metadata_offset: int = 0,
        ) -> list[dict[str, Any]]:
            fields: list[dict[str, Any]] = []
            for index, _name in enumerate(names):
                metadata_index = index + metadata_offset
                suffix = "" if metadata_index == 0 else str(metadata_index + 1)
                metadata = dataset_ctx.get(f"{axis}{suffix}_FIELD_METADATA")
                if not metadata:
                    continue
                item = copy.deepcopy(prototype)
                bind_field_metadata(item, str(item.get("id")), metadata)
                if axis == "YAXIS":
                    if y_aggregations and metadata_index < len(y_aggregations):
                        item["summary"] = y_aggregations[metadata_index]
                    channel = series_suffix or "yAxis"
                    item["axisType"] = channel
                    item["seriesId"] = f"{metadata.get('id')}-{channel}"
                fields.append(item)
            return fields

        if adapter.get("preserve_table_axes"):
            x_prototype = copy.deepcopy((view_info.get("xAxis") or [{}])[0])
            y_prototype = copy.deepcopy((view_info.get("yAxis") or [x_prototype])[0])
            view_info["xAxis"] = build_axis_fields(x_prototype, "XAXIS", x_names)
            view_info["yAxis"] = build_axis_fields(y_prototype, "YAXIS", y_names)
        elif template_type == "table_info" and view_info.get("xAxis"):
            prototype = view_info["xAxis"][0]
            table_fields: list[dict[str, Any]] = []
            for axis, names in (("XAXIS", x_names), ("YAXIS", y_names)):
                for index, _name in enumerate(names):
                    suffix = "" if index == 0 else str(index + 1)
                    field_id = dataset_ctx.get(f"{axis}{suffix}_FIELD_ID")
                    metadata = dataset_ctx.get(f"{axis}{suffix}_FIELD_METADATA")
                    if not field_id or not metadata:
                        continue
                    item = copy.deepcopy(prototype)
                    bind_field_metadata(item, str(item.get("id")), metadata)
                    if axis == "YAXIS" and y_aggregations and index < len(y_aggregations):
                        item["summary"] = y_aggregations[index]
                    table_fields.append(item)
            view_info["xAxis"] = table_fields
            view_info["yAxis"] = []
        elif len(y_names) > 1:
            y_prototype = copy.deepcopy((view_info.get("yAxis") or [{}])[0])
            secondary_channel = "yAxisExt" if secondary_y_axis else adapter.get("secondary_y_channel")
            if secondary_channel:
                view_info["yAxis"] = build_axis_fields(y_prototype, "YAXIS", y_names[:1])
                secondary = build_axis_fields(
                    y_prototype, "YAXIS", y_names[1:2],
                    series_suffix=str(secondary_channel),
                    metadata_offset=1,
                )
                view_info[str(secondary_channel)] = secondary
            else:
                view_info["yAxis"] = build_axis_fields(y_prototype, "YAXIS", y_names)
            tooltip = (
                view_info.get("customAttr", {})
                .get("tooltip", {})
            )
            if isinstance(tooltip, dict) and isinstance(tooltip.get("seriesTooltipFormatter"), list):
                tooltip["seriesTooltipFormatter"] = [
                    {**copy.deepcopy(item), "show": True}
                    for item in view_info.get("yAxis", [])
                ]
        self._replace_template_names(view_info, x_names, y_names)
        if chart_type == "flow-map":
            if len(x_names) < 2:
                raise ValueError("flow-map requires origin and destination fields in x_axis")
            prototype = copy.deepcopy(view_info.get("xAxis", [{}])[0])
            target_id = dataset_ctx.get("XAXIS2_FIELD_ID")
            target_meta = dataset_ctx.get("XAXIS2_FIELD_METADATA")
            if not target_id or not target_meta:
                raise ValueError("flow-map destination field metadata is unavailable")
            bind_field_metadata(prototype, str(prototype.get("id")), target_meta)
            view_info["xAxisExt"] = [prototype]

        expected_y_ids = {
            str(dataset_ctx[f"YAXIS{'' if index == 0 else index + 1}_FIELD_METADATA"]["id"])
            for index in range(len(y_names))
        }
        if template_type == "table_info" and not adapter.get("preserve_table_axes"):
            bound_y_ids = {
                str(item.get("id")) for item in view_info.get("xAxis", [])
                if isinstance(item, dict)
            }
        else:
            bound_y_ids = {
                str(item.get("id")) for item in view_info.get("yAxis", [])
                if isinstance(item, dict)
            }
            secondary_channel = "yAxisExt" if secondary_y_axis else adapter.get("secondary_y_channel")
            if secondary_channel:
                bound_y_ids.update(
                    str(item.get("id")) for item in view_info.get(str(secondary_channel), [])
                    if isinstance(item, dict)
                )
        missing_y_ids = sorted(expected_y_ids - bound_y_ids)
        if missing_y_ids:
            raise ValueError(
                f"{chart_type} failed to bind y_axis fields to native channels: "
                f"{', '.join(missing_y_ids)}"
            )

        components = json.loads(payload.get("componentData", "[]"))
        if not components:
            raise ValueError(f"Template {chart_type} has no componentData")
        component = components[0]
        native_type = native_chart_type(chart_type)
        view_info["type"] = native_type
        view_info["render"] = str(adapter.get("render") or view_info.get("render") or "antv")
        component["innerType"] = native_type
        component["icon"] = native_type
        component["category"] = str(adapter.get("category") or component.get("category") or "base")
        component.setdefault("events", {}).setdefault("jump", {"value": "https://", "type": "_blank"})
        apply_native_chart_defaults(view_info, native_type)
        if title:
            component.update({"name": title, "label": title})
        layout = layout.get("layout", layout)
        component.setdefault("style", {})
        for key in ("x", "y", "sizeX", "sizeY"):
            if key in layout:
                component[key] = layout[key]
        for key in ("width", "height", "left", "top"):
            if key in layout:
                component["style"][key] = layout[key]
        return component, view_info

    @staticmethod
    def _auto_layout(index: int, total: int) -> dict[str, Any]:
        if total == 3:
            margin_x, margin_y, gap_x, gap_y = 32, 32, 24, 24
            half_width = (1920 - margin_x * 2 - gap_x) // 2
            row_height = (1080 - margin_y * 2 - gap_y) // 2
            if index < 2:
                return {
                    "x": index * 36 + 1,
                    "y": 1,
                    "sizeX": 36,
                    "sizeY": 18,
                    "width": half_width,
                    "height": row_height,
                    "left": margin_x + index * (half_width + gap_x),
                    "top": margin_y,
                }
            return {
                "x": 1,
                "y": 19,
                "sizeX": 72,
                "sizeY": 18,
                "width": 1920 - margin_x * 2,
                "height": row_height,
                "left": margin_x,
                "top": margin_y + row_height + gap_y,
            }
        columns = 1 if total == 1 else 2
        rows = (total + columns - 1) // columns
        margin_x, margin_y, gap_x, gap_y = 32, 32, 24, 24
        width = (1920 - margin_x * 2 - gap_x * (columns - 1)) // columns
        height = max(170, (1080 - margin_y * 2 - gap_y * (rows - 1)) // rows)
        col, row = index % columns, index // columns
        grid_width = 72 // columns
        grid_height = max(4, 36 // rows)
        return {
            "x": col * grid_width + 1,
            "y": row * grid_height + 1,
            "sizeX": grid_width,
            "sizeY": grid_height,
            "width": width,
            "height": height,
            "left": margin_x + col * (width + gap_x),
            "top": margin_y + row * (height + gap_y),
        }

    @staticmethod
    def _complete_datav_layout(
        layout: dict[str, Any],
        canvas_width: int = 1920,
        canvas_height: int = 1080,
    ) -> dict[str, Any]:
        """Add DataV pixel geometry when a spec only supplies 72x36 grid geometry."""
        result = dict(layout.get("layout", layout))
        grid_keys = ("x", "y", "sizeX", "sizeY")
        if not all(key in result for key in grid_keys):
            return result
        try:
            x, y, size_x, size_y = (float(result[key]) for key in grid_keys)
        except (TypeError, ValueError) as exc:
            raise ValueError("DataV layout x/y/sizeX/sizeY must be numeric") from exc
        result.setdefault("left", round((x - 1) * canvas_width / 72))
        result.setdefault("top", round((y - 1) * canvas_height / 36))
        result.setdefault("width", round(size_x * canvas_width / 72))
        result.setdefault("height", round(size_y * canvas_height / 36))
        return result

    def _detect_check_version(self) -> str:
        configured = os.environ.get("DATAEASE_CHECK_VERSION", "").strip()
        if configured:
            return configured.lstrip("vV")
        try:
            response = self.client.get("/license/version")
            value = response.json().get("data")
            if isinstance(value, dict):
                value = value.get("version") or value.get("currentVersion")
            if value:
                match = re.search(r"\d+\.\d+(?:\.\d+)?", str(value))
                if match:
                    return match.group(0)
        except Exception:
            pass
        return "2.10"

    def deploy_multi(
        self,
        title: str,
        charts_config: List[Dict[str, Any]],
        busi_type: str = "dashboard",
        theme: Any = "business-light",
        canvas_config: dict[str, Any] | None = None,
        interactions: dict[str, Any] | None = None,
        publish: bool = True,
        append_timestamp: bool = True,
    ) -> tuple[str, str]:
        if busi_type not in {"dashboard", "dataV"}:
            raise ValueError("busi_type must be dashboard or dataV")
        palette = self._theme(theme)
        if not charts_config:
            raise ValueError("charts_config must not be empty")
        unsupported = sorted({str(item.get("type")) for item in charts_config} - self.SUPPORTED_CHART_TYPES)
        if unsupported:
            raise ValueError(f"unsupported chart types: {', '.join(unsupported)}")
        board_name = f"{title}_{int(time.time())}" if append_timestamp else title
        base_template = Path(__file__).resolve().parents[2] / "templates" / "dashboard" / "base.json"
        canvas_style = json.loads(json.loads(base_template.read_text(encoding="utf-8"))["canvasStyleData"])
        if canvas_config:
            width = int(canvas_config.get("width") or canvas_style.get("width") or 1920)
            height = int(canvas_config.get("height") or canvas_style.get("height") or 1080)
            if width < 320 or height < 320 or width > 16384 or height > 16384:
                raise ValueError("canvas width/height must be between 320 and 16384")
            canvas_style.update({"width": width, "height": height})
            if canvas_config.get("screen_adaptor"):
                canvas_style["screenAdaptor"] = str(canvas_config["screen_adaptor"])
        canvas_style = self._apply_canvas_theme(canvas_style, theme)
        interaction_input = dict(interactions or {})
        declared_jumps = list(interaction_input.get("jumps") or [])
        for chart in charts_config:
            if chart.get("jump") is not None:
                declared_jumps.append({**dict(chart["jump"]), "source": chart.get("title")})
        interaction_input["jumps"] = declared_jumps
        interaction_plan = normalize_interactions(interaction_input)
        configured_titles = {
            str(item.get("title")).strip() for item in charts_config
            if str(item.get("title") or "").strip()
        }
        unknown_jump_sources = sorted({
            str(item["source"]) for item in interaction_plan["jumps"]
            if str(item["source"]) not in configured_titles
        })
        if unknown_jump_sources:
            raise ValueError(f"jump source does not match a chart title: {', '.join(unknown_jump_sources)}")
        reserved_top_rows = (
            4 if interaction_plan["filters"] and not any(item.get("layout") for item in charts_config) else 0
        )
        explicit_canvas_height = bool(canvas_config and canvas_config.get("height"))
        if busi_type == "dashboard" and not explicit_canvas_height and not any(item.get("layout") for item in charts_config):
            canvas_style["height"] = recommended_dashboard_height(
                charts_config,
                reserved_top_rows=reserved_top_rows,
                base_height=int(canvas_style.get("height") or 1080),
            )

        component_data: list[dict[str, Any]] = []
        canvas_view_info: dict[str, Any] = {}
        active_view_ids: list[str] = []
        chart_view_ids = [self.rand_id() for _ in charts_config]
        planned_layouts = plan_smart_layouts(
            charts_config,
            canvas_width=int(canvas_style.get("width", 1920)),
            canvas_height=int(canvas_style.get("height", 1080)),
            reserved_top_rows=reserved_top_rows,
        )
        effective_grid_layouts = [
            dict((config.get("layout") or planned_layouts[index]).get(
                "layout", config.get("layout") or planned_layouts[index],
            ))
            for index, config in enumerate(charts_config)
        ]
        grid_issues = validate_layouts(effective_grid_layouts)
        if grid_issues:
            raise ValueError(f"chart layouts overlap or exceed the 72x36 canvas: {grid_issues[:3]}")
        for index, config in enumerate(charts_config):
            view_id = chart_view_ids[index]
            active_view_ids.append(view_id)
            layout = config.get("layout") or planned_layouts[index]
            if busi_type == "dataV":
                layout = self._complete_datav_layout(
                    layout,
                    canvas_width=int(canvas_style.get("width", 1920)),
                    canvas_height=int(canvas_style.get("height", 1080)),
                )
            component, view = self.extract_chart_payload(
                chart_type=config["type"],
                dataset_id=config["dataset_name"],
                x_names=config.get("x_axis", []),
                y_names=config.get("y_axis", []),
                view_id=view_id,
                layout=layout,
                title=config.get("title"),
                y_aggregations=config.get("y_aggregations"),
                secondary_y_axis=bool(config.get("secondary_y_axis")),
            )
            typography_policy = (
                config.get("typography")
                if isinstance(config.get("typography"), dict)
                else (canvas_config or {}).get("typography")
            )
            self._apply_component_theme(
                component, view, config["type"], theme,
                typography_policy if isinstance(typography_policy, dict) else None,
                len(charts_config),
            )
            hierarchy_rule = next((item for item in interaction_plan["drill_hierarchies"] if isinstance(item, dict) and item.get("source") == config.get("title")), {})
            drill_fields = config.get("drill_fields") or hierarchy_rule.get("fields") or []
            if isinstance(drill_fields, list) and drill_fields:
                drill_ctx = self.get_dataset_ctx(config["dataset_name"], drill_fields, [])
                view["drill"] = True
                view["drillFields"] = [
                    drill_ctx[f"XAXIS{'' if pos == 0 else pos + 1}_FIELD_METADATA"]
                    for pos in range(len(drill_fields))
                ]
            component["_dragId"] = index
            component_data.append(component)
            canvas_view_info[view_id] = view

        if interaction_plan["filters"]:
            dataset_name = str(charts_config[0]["dataset_name"])
            filter_ctx = self.get_dataset_ctx(dataset_name, interaction_plan["filters"], [])
            filter_fields = [
                filter_ctx[f"XAXIS{'' if pos == 0 else pos + 1}_FIELD_METADATA"]
                for pos in range(len(interaction_plan["filters"]))
            ]
            target_ids = [
                chart_view_ids[pos] for pos, item in enumerate(charts_config)
                if str(item.get("dataset_name")) == dataset_name
            ]
            query_id = self.rand_id()
            query_component, query_view = build_query_component(
                query_id, str(filter_ctx["DATASET_GROUP_ID"]), filter_fields, target_ids,
                canvas_width=int(canvas_style.get("width", 1920)),
                canvas_height=int(canvas_style.get("height", 1080)),
                dataset_fields=filter_ctx.get("ALL_FIELD_METADATA"),
                cascade_chains=interaction_plan["filter_cascades"],
                background_color=str(canvas_style.get("backgroundColor") or "#FFFFFF"),
                accent_color=str(palette["accent"]),
            )
            query_component["_dragId"] = len(component_data)
            component_data.append(query_component)
            canvas_view_info[query_id] = query_view
            active_view_ids.append(query_id)

        payload = {
            "id": None,
            "name": board_name,
            "type": busi_type,
            "status": 0,
            "dataState": "ready",
            "selfWatermarkStatus": True,
            "checkVersion": self._detect_check_version(),
            "pid": "0",
            "mobileLayout": False,
            "canvasStyleData": json.dumps(canvas_style, separators=(",", ":"), ensure_ascii=False),
            "componentData": json.dumps(component_data, separators=(",", ":"), ensure_ascii=False),
            "canvasViewInfo": canvas_view_info,
            "contentId": self.rand_id(),
        }
        print(f"Deploying {busi_type} '{title}' with {len(charts_config)} charts...", file=sys.stderr)
        save_response = self.client.post("/dataVisualization/saveCanvas", payload)
        save_response.raise_for_status()
        save_body = save_response.json()
        if save_body.get("code") not in (None, 0):
            raise RuntimeError(f"saveCanvas failed: {save_body.get('msg')}")
        dashboard_id = str(save_body["data"])
        source_views = {
            str(config.get("title")): chart_view_ids[index]
            for index, config in enumerate(charts_config)
            if str(config.get("title") or "").strip()
        }
        field_ids: dict[tuple[str, str], str] = {}

        def field_id_for(source: str, field: str) -> str:
            cache_key = (source, field)
            if cache_key not in field_ids:
                chart = next(item for item in charts_config if str(item.get("title") or "") == source)
                ctx = self.get_dataset_ctx(str(chart["dataset_name"]), [field], [])
                field_ids[cache_key] = str(ctx["XAXIS_FIELD_METADATA"]["id"])
            return field_ids[cache_key]

        for jump_payload in build_native_link_jump_payloads(
            dashboard_id, interaction_plan["jumps"], source_views, field_id_for,
        ):
            jump_response = self.client.post("/linkJump/updateJumpSet", jump_payload)
            jump_response.raise_for_status()
            jump_body = jump_response.json()
            if jump_body.get("code") not in (None, 0):
                raise RuntimeError(f"updateJumpSet failed: {jump_body.get('msg')}")
            active_response = self.client.post("/linkJump/updateJumpSetActive", {
                "sourceDvId": dashboard_id, "sourceViewId": jump_payload["sourceViewId"], "activeStatus": True,
            })
            active_response.raise_for_status()
            active_body = active_response.json()
            if active_body.get("code") not in (None, 0):
                raise RuntimeError(f"updateJumpSetActive failed: {active_body.get('msg')}")
        if interaction_plan["auto_linkage"]:
            for linkage in shared_linkages(charts_config, chart_view_ids, canvas_view_info):
                linkage_response = self.client.post("/linkage/saveLinkage", {"dvId": dashboard_id, **linkage})
                linkage_response.raise_for_status()
                linkage_body = linkage_response.json()
                if linkage_body.get("code") not in (None, 0):
                    raise RuntimeError(f"saveLinkage failed: {linkage_body.get('msg')}")
        if publish:
            publish_response = self.client.post("/dataVisualization/updatePublishStatus", {
                "id": dashboard_id,
                "name": board_name,
                "activeViewIds": active_view_ids,
                "status": 1,
                "type": busi_type,
                "mobileLayout": False,
            })
            publish_response.raise_for_status()
            publish_body = publish_response.json()
            if publish_body.get("code") not in (None, 0):
                raise RuntimeError(f"publish failed: {publish_body.get('msg')}")
        url = f"{self.base_url}/#/preview?dvId={dashboard_id}&dvType={busi_type}&ignoreParams=true"
        return dashboard_id, url
