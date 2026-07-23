import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from dataease_skill.design_inspiration import apply_design_inspiration


class DesignInspirationTests(unittest.TestCase):
    def _spec(self):
        return {
            "theme": "business-light",
            "charts": [
                {"type": "table-info", "intent": "detail"},
                {"type": "map", "intent": "geospatial"},
                {"type": "indicator", "intent": "kpi"},
                {"type": "line", "intent": "trend"},
            ],
            "interactions": {"filters": ["省"]},
        }

    def test_geo_dashboard_uses_map_focal_grammar_without_copying(self):
        result = apply_design_inspiration(
            self._spec(), title="全国生态环境驾驶舱", busi_type="dataV",
        )
        self.assertEqual(result["design_inspiration"]["grammar"], "geo-command")
        self.assertEqual(result["layout_strategy"]["archetype"], "map-focal")
        self.assertFalse(result["design_inspiration"]["template_copying"])
        self.assertEqual(result["charts"][0]["intent"], "kpi")
        self.assertEqual(result["charts"][1]["intent"], "geospatial")
        self.assertGreaterEqual(result["charts"][1]["layout"]["sizeX"], 36)
        self.assertTrue(all("layout" in chart for chart in result["charts"]))

    def test_operations_title_selects_command_center(self):
        result = apply_design_inspiration(
            self._spec(), title="网络设备告警监控", busi_type="dashboard",
        )
        self.assertEqual(result["design_inspiration"]["grammar"], "operations-command")
        self.assertEqual(result["theme"], "tech-blue")

    def test_explicit_theme_can_be_preserved(self):
        result = apply_design_inspiration(
            self._spec(), title="销售驾驶舱", busi_type="dashboard",
            preserve_explicit_theme=True,
        )
        self.assertEqual(result["theme"], "business-light")


if __name__ == "__main__":
    unittest.main()
