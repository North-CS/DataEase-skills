import sys
import json
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from dataease_skill.visual_engine import MultiDataEaseChartEngine


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


if __name__ == "__main__":
    unittest.main()
