import base64
import json
import mimetypes
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from .visual_base import DataEaseChartEngine


class MultiDataEaseChartEngine(DataEaseChartEngine):
    """Compose template-backed charts into dashboard or DataV canvases."""

    NEON_COLORS = [
        "#00D9FF", "#7C5CFF", "#20E3B2", "#FFB347", "#FF5DA2",
        "#4D96FF", "#9DFFB0", "#A78BFA", "#22D3EE",
    ]

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

    def _apply_canvas_theme(self, canvas: dict[str, Any], theme: str) -> dict[str, Any]:
        if theme != "neon-dark":
            return canvas
        canvas.update({
            "width": 1920,
            "height": 1080,
            "screenAdaptor": "widthFirst",
            "dashboardAdaptor": "keepHeightAndWidth",
            "backgroundColorSelect": True,
            "backgroundImageEnable": False,
            "backgroundType": "backgroundColor",
            "background": "",
            "backgroundColor": "#050B1A",
            "color": "#EAF8FF",
            "fontFamily": "Microsoft YaHei",
            "scale": 100,
            "scaleWidth": 100,
            "scaleHeight": 100,
        })
        background = self._asset_data_uri(os.environ.get("DATAEASE_BACKGROUND_IMAGE", "").strip())
        if background:
            canvas["backgroundImageEnable"] = True
            canvas["background"] = background
        canvas.setdefault("dashboard", {}).update({
            "gap": "no", "gapSize": 0, "showGrid": False, "themeColor": "dark"
        })
        component = canvas.setdefault("component", {})
        component.setdefault("chartTitle", {}).update({
            "show": True, "fontSize": 18, "isBolder": True, "color": "#DDF8FF"
        })
        component.setdefault("chartColor", {}).setdefault("basicStyle", {}).update({
            "colors": self.NEON_COLORS,
            "gradient": True,
            "alpha": 92,
            "areaBaseColor": "rgba(3,12,29,0.35)",
            "areaBorderColor": "#00D9FF",
        })
        component.setdefault("chartCommonStyle", {}).update({
            "backgroundColorSelect": True,
            "backdropFilterEnable": True,
            "backdropFilter": 8,
            "backgroundImageEnable": False,
            "backgroundColor": "rgba(3,12,29,0.58)",
            "innerImageColor": "#00D9FF",
        })
        return canvas

    def _apply_component_theme(
        self, component: dict[str, Any], view_info: dict[str, Any], chart_type: str, theme: str
    ) -> None:
        if theme != "neon-dark":
            return
        component.setdefault("style", {}).update({
            "borderActive": True,
            "borderWidth": 1,
            "borderRadius": 14,
            "borderColor": "rgba(0,217,255,0.48)",
        })
        component["commonBackground"] = {
            "backgroundColorSelect": True,
            "backdropFilterEnable": True,
            "backgroundImageEnable": False,
            "backgroundType": "innerImage",
            "innerImage": "board/board_1.svg",
            "outerImage": None,
            "innerPadding": {"mode": "uniform", "top": 14},
            "borderRadius": {"mode": "uniform", "topLeft": 14},
            "backdropFilter": 8,
            "backgroundColor": "rgba(3,12,29,0.62)",
            "innerImageColor": "rgba(0,217,255,0.72)",
        }
        custom_attr = view_info.setdefault("customAttr", {})
        custom_attr.setdefault("basicStyle", {}).update({
            "colors": self.NEON_COLORS,
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
            "tableBorderColor": "rgba(0,217,255,0.28)",
            "tableScrollBarColor": "rgba(0,217,255,0.45)",
        })
        custom_attr.setdefault("misc", {}).update({"nameFontColor": "#BDEBFF", "valueFontColor": "#00D9FF"})
        label = custom_attr.setdefault("label", {})
        label.update({"color": "#EAF8FF", "fontSize": 12})
        if chart_type == "pie":
            label.update({"show": True, "position": "outside", "showProportion": True})
        custom_attr.setdefault("tooltip", {}).update({
            "color": "#EAF8FF", "backgroundColor": "rgba(4,14,34,0.94)"
        })
        custom_attr.setdefault("tableHeader", {}).update({
            "tableHeaderBgColor": "rgba(0,217,255,0.20)",
            "tableHeaderCornerBgColor": "rgba(0,217,255,0.24)",
            "tableHeaderColBgColor": "rgba(0,217,255,0.20)",
            "tableHeaderFontColor": "#EAF8FF",
            "tableHeaderCornerFontColor": "#EAF8FF",
            "tableHeaderColFontColor": "#EAF8FF",
        })
        custom_attr.setdefault("tableCell", {}).update({
            "tableItemBgColor": "rgba(3,12,29,0.18)",
            "tableItemSubBgColor": "rgba(0,217,255,0.08)",
            "tableFontColor": "#CDEFFF",
        })
        custom_style = view_info.setdefault("customStyle", {})
        custom_style.setdefault("text", {}).update({
            "show": True,
            "fontSize": 18,
            "isBolder": True,
            "color": "#DDF8FF",
            "remarkBackgroundColor": "rgba(3,12,29,0.85)",
        })
        custom_style.setdefault("legend", {}).update({
            "show": True, "color": "#B7D9EF", "fontSize": 12, "icon": "circle"
        })
        for axis_name in ("xAxis", "yAxis", "yAxisExt", "misc"):
            axis = custom_style.setdefault(axis_name, {})
            axis.update({"color": "#9BC7E5", "fontSize": 12})
            axis.setdefault("axisLabel", {}).update({"color": "#9BC7E5", "fontSize": 12})
            axis.setdefault("axisLine", {}).setdefault("lineStyle", {}).update({
                "color": "rgba(0,217,255,0.28)", "width": 1
            })
            axis.setdefault("splitLine", {}).setdefault("lineStyle", {}).update({
                "color": "rgba(122,184,224,0.16)", "width": 1
            })

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
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        template_dir = Path(__file__).resolve().parents[2] / "templates" / f"chart_{chart_type}"
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
                self._update_field_names(view_info, field_id, name)
        for index, name in enumerate(y_names):
            field_id = dataset_ctx.get(f"YAXIS{'' if index == 0 else index + 1}_FIELD_ID")
            if field_id:
                self._update_field_names(view_info, field_id, name)
        self._replace_template_names(view_info, x_names, y_names)

        components = json.loads(payload.get("componentData", "[]"))
        if not components:
            raise ValueError(f"Template {chart_type} has no componentData")
        component = components[0]
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
        theme: str = "business-light",
        publish: bool = True,
        append_timestamp: bool = True,
    ) -> tuple[str, str]:
        if busi_type not in {"dashboard", "dataV"}:
            raise ValueError("busi_type must be dashboard or dataV")
        if theme not in {"business-light", "neon-dark"}:
            raise ValueError("theme must be business-light or neon-dark")
        if not charts_config:
            raise ValueError("charts_config must not be empty")
        board_name = f"{title}_{int(time.time())}" if append_timestamp else title
        base_template = Path(__file__).resolve().parents[2] / "templates" / "dashboard" / "base.json"
        canvas_style = json.loads(json.loads(base_template.read_text(encoding="utf-8"))["canvasStyleData"])
        canvas_style = self._apply_canvas_theme(canvas_style, theme)

        component_data: list[dict[str, Any]] = []
        canvas_view_info: dict[str, Any] = {}
        active_view_ids: list[str] = []
        for index, config in enumerate(charts_config):
            view_id = self.rand_id()
            active_view_ids.append(view_id)
            layout = config.get("layout") or self._auto_layout(index, len(charts_config))
            component, view = self.extract_chart_payload(
                chart_type=config["type"],
                dataset_id=config["dataset_name"],
                x_names=config.get("x_axis", []),
                y_names=config.get("y_axis", []),
                view_id=view_id,
                layout=layout,
                title=config.get("title"),
            )
            self._apply_component_theme(component, view, config["type"], theme)
            if busi_type == "dataV":
                component.update({"x": 1, "y": 1, "sizeX": 36, "sizeY": 14})
            component["_dragId"] = index
            component_data.append(component)
            canvas_view_info[view_id] = view

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
