import sys
import json
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from dataease_skill.visual_engine import MultiDataEaseChartEngine
from dataease_skill.chart_catalog import SUPPORTED_CHART_TYPES
from dataease_skill.layout_planner import plan_smart_layouts, recommended_dashboard_height


class LayoutTests(unittest.TestCase):
    def test_layout_stays_inside_canvas(self):
        for total in (1, 2, 3, 4, 9):
            for index in range(total):
                layout = MultiDataEaseChartEngine._auto_layout(index, total)
                self.assertGreater(layout["width"], 0)
                self.assertGreater(layout["height"], 0)
                self.assertLessEqual(layout["left"] + layout["width"], 1920)
                self.assertLessEqual(layout["top"] + layout["height"], 1080)

    def test_three_chart_layout_uses_full_width_for_last_chart(self):
        layout = MultiDataEaseChartEngine._auto_layout(2, 3)
        self.assertEqual(layout["sizeX"], 72)
        self.assertGreater(layout["width"], 1800)

    def test_neon_theme(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        canvas = engine._apply_canvas_theme({"dashboard": {}, "component": {}}, "neon-dark")
        self.assertEqual(canvas["backgroundColor"], "#050B1A")
        self.assertEqual(canvas["dashboard"]["themeColor"], "dark")

    def test_extended_theme_catalog(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        for theme in (
            "business-light", "minimal-light", "neon-dark", "deep-ocean", "dark-gold",
            "tech-blue", "chinese-red", "government-blue", "medical-health",
            "energy-green", "retail-vibrant",
        ):
            canvas = engine._apply_canvas_theme({"dashboard": {}, "component": {}}, theme)
            self.assertTrue(canvas["backgroundColor"])

    def test_custom_theme_is_applied(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        canvas = engine._apply_canvas_theme(
            {"dashboard": {}, "component": {}},
            {"base": "business-light", "accent": "#663399", "background": "#FAFAFA"},
        )
        self.assertEqual(canvas["backgroundColor"], "#FAFAFA")
        self.assertEqual(canvas["component"]["chartColor"]["basicStyle"]["colors"][0], "#663399")

    def test_light_brand_theme_reaches_chart_palette(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        component, view = {}, {}
        engine._apply_component_theme(
            component, view, "bar",
            {"base": "business-light", "accent": "#008C85", "background": "#F2FBFA"},
        )
        self.assertEqual(view["customAttr"]["basicStyle"]["colors"][0], "#008C85")
        self.assertEqual(view["customAttr"]["misc"]["valueFontColor"], "#008C85")

    def test_dark_industry_theme_reaches_indicator_and_table_styles(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        component, view = {}, {
            "customAttr": {
                "indicator": {"color": "#5470C6ff"},
                "indicatorName": {"color": "#646A73ff"},
            }
        }
        engine._apply_component_theme(component, view, "indicator", "energy-green")
        self.assertEqual(view["customAttr"]["indicator"]["color"], "#35D07FFF")
        self.assertEqual(view["customAttr"]["misc"]["valueFontColor"], "#35D07F")
        self.assertIn("53,208,127", view["customAttr"]["tableHeader"]["tableHeaderBgColor"])

    def test_common_chart_families_have_real_adapters(self):
        expected = {
            "bar", "bar-stack", "line", "area", "area-stack", "pie", "pie-donut",
            "indicator", "table-info", "table-normal", "table-pivot", "t-heatmap",
            "map", "bubble-map", "heat-map", "symbolic-map", "scatter", "funnel", "radar",
        }
        self.assertTrue(expected.issubset(SUPPORTED_CHART_TYPES))

    def test_adapter_rewrites_native_type_and_renderer(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        engine.get_dataset_ctx = lambda *_args: {
            "DATASET_GROUP_ID": "100", "XAXIS_FIELD_ID": "11", "XAXIS_DE_NAME": "f_region",
            "XAXIS_FIELD_METADATA": {"id": "11", "name": "省", "dataeaseName": "f_region", "deType": 0},
            "YAXIS_FIELD_ID": "22", "YAXIS_DE_NAME": "f_sales", "YAXIS_SERIES_ID": "22-yAxis",
            "YAXIS_FIELD_METADATA": {"id": "22", "name": "销售额", "dataeaseName": "f_sales", "deType": 2},
        }
        component, view = engine.extract_chart_payload(
            "indicator", "100", ["省"], ["销售额"], "9002",
            {"x": 1, "y": 1, "sizeX": 18, "sizeY": 6}, y_aggregations=["sum"],
        )
        self.assertEqual(view["type"], "indicator")
        self.assertEqual(view["render"], "custom")
        self.assertEqual(component["innerType"], "indicator")
        self.assertEqual(view["xAxis"][0]["summary"], "none")
        self.assertEqual(view["yAxis"][0]["compareCalc"]["type"], "none")
        self.assertIn("indicator", view["customAttr"])
        self.assertIn("indicatorName", view["customAttr"])
        self.assertEqual(component["events"]["jump"]["type"], "_blank")

    def test_every_catalog_adapter_renders_and_binds_fields(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        engine.get_dataset_ctx = lambda *_args: {
            "DATASET_GROUP_ID": "100", "XAXIS_FIELD_ID": "11", "XAXIS_DE_NAME": "f_region",
            "XAXIS_FIELD_METADATA": {"id": "11", "name": "省", "originName": "province", "dataeaseName": "f_region", "deType": 0},
            "XAXIS2_FIELD_ID": "12", "XAXIS2_DE_NAME": "f_city",
            "XAXIS2_FIELD_METADATA": {"id": "12", "name": "市", "originName": "city", "dataeaseName": "f_city", "deType": 0},
            "YAXIS_FIELD_ID": "22", "YAXIS_DE_NAME": "f_sales", "YAXIS_SERIES_ID": "22-yAxis",
            "YAXIS_FIELD_METADATA": {"id": "22", "name": "销售额", "originName": "sales", "dataeaseName": "f_sales", "deType": 2},
        }
        for index, chart_type in enumerate(sorted(SUPPORTED_CHART_TYPES), start=1):
            with self.subTest(chart_type=chart_type):
                x_fields = ["省", "市"] if chart_type == "flow-map" else ["省"]
                component, view = engine.extract_chart_payload(
                    chart_type, "100", x_fields, ["销售额"], str(9100 + index),
                    {"x": 1, "y": 1, "sizeX": 24, "sizeY": 12}, y_aggregations=["sum"],
                )
                self.assertEqual(component["innerType"], view["type"])
                self.assertTrue(_find_fields(view, "11"))
                self.assertTrue(_find_fields(view, "22"))
                if chart_type == "flow-map":
                    self.assertTrue(_find_fields(view.get("xAxisExt", []), "12"))
                if chart_type in {"map", "bubble-map", "heat-map", "flow-map"}:
                    self.assertEqual(view["customAttr"]["map"], {"id": "156", "level": "country"})

    def test_dense_dashboard_recommends_readable_scroll_height(self):
        charts = [
            *[{"type": "indicator", "intent": "kpi"} for _ in range(4)],
            {"type": "map"}, {"type": "map"}, {"type": "line", "intent": "trend"},
            {"type": "pie", "intent": "composition"}, {"type": "bar-horizontal", "intent": "ranking"},
            {"type": "bar"}, {"type": "table_info", "intent": "detail"},
        ]
        height = recommended_dashboard_height(charts, reserved_top_rows=4)
        layouts = plan_smart_layouts(charts, canvas_height=height, reserved_top_rows=4)
        self.assertEqual(height, 1440)
        self.assertGreaterEqual(min(item["height"] for item in layouts[4:10]), 240)
        self.assertGreaterEqual(layouts[-1]["height"], 320)

    def test_custom_4k_canvas_scales_datav_pixel_layout(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        engine.base_url = "http://example"
        engine.client = _FakeVisualClient()
        engine.rand_id = _sequential_ids()
        engine.extract_chart_payload = _fake_extract_chart_payload
        engine._apply_component_theme = lambda *_args: None
        engine._detect_check_version = lambda: "2.10.25"
        engine.deploy_multi(
            "4K 大屏", [{"type": "line", "intent": "trend", "dataset_name": "1"}],
            busi_type="dataV", publish=False, append_timestamp=False,
            canvas_config={"width": 3840, "height": 2160},
        )
        canvas = json.loads(engine.client.saved_payload["canvasStyleData"])
        component = json.loads(engine.client.saved_payload["componentData"])[0]
        self.assertEqual((canvas["width"], canvas["height"]), (3840, 2160))
        self.assertEqual((component["style"]["width"], component["style"]["height"]), (3840, 2160))

    def test_dark_theme_preserves_explicit_canvas_size(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        canvas = engine._apply_canvas_theme(
            {"width": 3840, "height": 2160, "dashboard": {}, "component": {}},
            "tech-blue",
        )
        self.assertEqual((canvas["width"], canvas["height"]), (3840, 2160))

    def test_missing_optional_background_falls_back_to_theme_color(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        self.assertEqual(engine._asset_data_uri("definitely-missing-background.jpg"), "")

    def test_supported_y_aggregation_updates_matching_fields(self):
        view = {
            "xAxis": [{"id": "1", "summary": "count"}],
            "yAxis": [{"id": "2", "summary": "sum"}],
        }
        MultiDataEaseChartEngine._update_field_aggregation(view, "2", "avg")
        self.assertEqual(view["xAxis"][0]["summary"], "count")
        self.assertEqual(view["yAxis"][0]["summary"], "avg")

    def test_rendered_fields_use_authoritative_dataset_metadata(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        engine.get_dataset_ctx = lambda *_args: {
            "DATASET_GROUP_ID": "100",
            "DATASOURCE_ID": "200",
            "DATASET_TABLE_ID": "300",
            "XAXIS_FIELD_ID": "11",
            "XAXIS_DE_NAME": "f_region",
            "XAXIS_FIELD_METADATA": {
                "id": "11", "name": "省级行政区", "originName": "province_name",
                "dataeaseName": "f_region", "fieldShortName": "f_region", "type": "VARCHAR",
                "deType": 0, "groupType": "d", "datasetGroupId": "100",
                "datasetTableId": "300", "datasourceId": "200",
            },
            "YAXIS_FIELD_ID": "22",
            "YAXIS_DE_NAME": "f_profit",
            "YAXIS_SERIES_ID": "22-yAxis",
            "YAXIS_FIELD_METADATA": {
                "id": "22", "name": "利润额", "originName": "profit_amount",
                "dataeaseName": "f_profit", "fieldShortName": "f_profit", "type": "DECIMAL",
                "deType": 2, "groupType": "q", "datasetGroupId": "100",
                "datasetTableId": "300", "datasourceId": "200",
            },
        }

        _component, view = engine.extract_chart_payload(
            "bar", "100", ["省级行政区"], ["利润额"], "9001",
            {"x": 1, "y": 1, "sizeX": 72, "sizeY": 18, "left": 0, "top": 0, "width": 1920, "height": 540},
            y_aggregations=["sum"],
        )

        x_fields = _find_fields(view, "11")
        y_fields = _find_fields(view, "22")
        self.assertTrue(x_fields)
        self.assertTrue(y_fields)
        self.assertTrue(all(item["originName"] == "province_name" for item in x_fields))
        self.assertTrue(all(item["dataeaseName"] == "f_region" for item in x_fields))
        self.assertTrue(all(item["groupType"] == "d" and item["deType"] == 0 for item in x_fields))
        self.assertTrue(all(item["originName"] == "profit_amount" for item in y_fields))
        self.assertTrue(all(item["dataeaseName"] == "f_profit" for item in y_fields))
        self.assertTrue(all(item["groupType"] == "q" and item["deType"] == 2 for item in y_fields))

    def test_datav_deploy_preserves_custom_component_layouts(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        engine.base_url = "http://example"
        engine.client = _FakeVisualClient()
        engine.rand_id = _sequential_ids()
        engine.extract_chart_payload = _fake_extract_chart_payload
        engine._apply_component_theme = lambda *_args: None
        engine._detect_check_version = lambda: "2.10.25"

        layouts = [
            {"x": 1, "y": 1, "sizeX": 20, "sizeY": 10, "left": 10, "top": 20, "width": 600, "height": 300},
            {"x": 22, "y": 1, "sizeX": 20, "sizeY": 10, "left": 630, "top": 20, "width": 600, "height": 300},
        ]
        charts = [
            {"type": "bar", "dataset_name": "1", "layout": layouts[0]},
            {"type": "line", "dataset_name": "2", "layout": layouts[1]},
        ]
        engine.deploy_multi("自定义布局", charts, busi_type="dataV", publish=False, append_timestamp=False)

        components = json.loads(engine.client.saved_payload["componentData"])
        self.assertEqual(
            [(item["x"], item["y"], item["sizeX"], item["sizeY"]) for item in components],
            [(1, 1, 20, 10), (22, 1, 20, 10)],
        )
        self.assertEqual([item["style"]["left"] for item in components], [10, 630])

    def test_datav_deploy_uses_distinct_auto_layouts(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        engine.base_url = "http://example"
        engine.client = _FakeVisualClient()
        engine.rand_id = _sequential_ids()
        engine.extract_chart_payload = _fake_extract_chart_payload
        engine._apply_component_theme = lambda *_args: None
        engine._detect_check_version = lambda: "2.10.25"
        charts = [{"type": "bar", "dataset_name": str(index)} for index in range(6)]

        engine.deploy_multi("自动布局", charts, busi_type="dataV", publish=False, append_timestamp=False)

        components = json.loads(engine.client.saved_payload["componentData"])
        positions = {(item["x"], item["y"], item["style"]["left"], item["style"]["top"]) for item in components}
        self.assertEqual(len(positions), 6)

    def test_datav_grid_only_layout_gets_pixel_geometry(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        engine.base_url = "http://example"
        engine.client = _FakeVisualClient()
        engine.rand_id = _sequential_ids()
        engine.extract_chart_payload = _fake_extract_chart_payload
        engine._apply_component_theme = lambda *_args: None
        engine._detect_check_version = lambda: "2.10.25"
        layouts = [
            {"x": 1, "y": 1, "sizeX": 36, "sizeY": 18},
            {"x": 37, "y": 1, "sizeX": 35, "sizeY": 18},
            {"x": 1, "y": 19, "sizeX": 36, "sizeY": 18},
            {"x": 37, "y": 19, "sizeX": 35, "sizeY": 18},
        ]
        charts = [
            {"type": "bar", "dataset_name": str(index), "layout": layout}
            for index, layout in enumerate(layouts)
        ]

        engine.deploy_multi("网格布局", charts, busi_type="dataV", publish=False, append_timestamp=False)

        components = json.loads(engine.client.saved_payload["componentData"])
        geometry = [
            (item["style"]["left"], item["style"]["top"], item["style"]["width"], item["style"]["height"])
            for item in components
        ]
        self.assertEqual(
            geometry,
            [(0, 0, 960, 540), (960, 0, 933, 540), (0, 540, 960, 540), (960, 540, 933, 540)],
        )
        self.assertEqual(len({(left, top) for left, top, _width, _height in geometry}), 4)

    def test_dashboard_smart_layout_uses_semantic_roles(self):
        engine = object.__new__(MultiDataEaseChartEngine)
        engine.base_url = "http://example"
        engine.client = _FakeVisualClient()
        engine.rand_id = _sequential_ids()
        engine.extract_chart_payload = _fake_extract_chart_payload
        engine._apply_component_theme = lambda *_args: None
        engine._detect_check_version = lambda: "2.10.25"
        charts = [
            {"type": "line", "intent": "trend", "dataset_name": "1"},
            {"type": "pie", "intent": "composition", "dataset_name": "1"},
            {"type": "table_info", "intent": "detail", "dataset_name": "1"},
        ]

        engine.deploy_multi("智能仪表板", charts, busi_type="dashboard", publish=False, append_timestamp=False)

        components = json.loads(engine.client.saved_payload["componentData"])
        self.assertEqual((components[0]["sizeX"], components[1]["sizeX"]), (48, 24))
        self.assertEqual(components[2]["sizeX"], 72)
        self.assertGreater(components[2]["y"], components[0]["y"])


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"code": 0, "data": "100"}


class _FakeVisualClient:
    def __init__(self):
        self.saved_payload = None

    def post(self, path, payload):
        if path == "/dataVisualization/saveCanvas":
            self.saved_payload = payload
        return _FakeResponse()


def _sequential_ids():
    values = iter(str(index) for index in range(1, 100))
    return lambda: next(values)


def _fake_extract_chart_payload(*, view_id, layout, **_kwargs):
    layout = layout.get("layout", layout)
    component = {"style": {}}
    for key in ("x", "y", "sizeX", "sizeY"):
        component[key] = layout[key]
    for key in ("width", "height", "left", "top"):
        component["style"][key] = layout[key]
    return component, {"id": view_id}


def _find_fields(value, field_id):
    result = []
    if isinstance(value, dict):
        if str(value.get("id")) == str(field_id):
            result.append(value)
        for item in value.values():
            result.extend(_find_fields(item, field_id))
    elif isinstance(value, list):
        for item in value:
            result.extend(_find_fields(item, field_id))
    return result


if __name__ == "__main__":
    unittest.main()
