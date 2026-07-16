import sys
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


if __name__ == "__main__":
    unittest.main()
