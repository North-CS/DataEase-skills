import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from dataease_skill.visual_quality import apply_complexity_profile, score_visual_spec


class VisualQualityTests(unittest.TestCase):
    def test_complete_spec_passes_without_multimodal_model(self):
        spec = {
            "kind": "dataV",
            "title": "销售驾驶舱",
            "theme": "tech-blue",
            "charts": [
                {"type": "indicator", "dataset_name": "1", "x_axis": ["区域"], "y_axis": ["销售额"]},
                {"type": "line", "dataset_name": "1", "x_axis": ["日期"], "y_axis": ["销售额"]},
                {"type": "table-info", "dataset_name": "1", "x_axis": ["区域"], "y_axis": ["销售额"]},
            ],
            "interactions": {"filters": ["日期", "区域"]},
        }
        result = score_visual_spec(spec, skill_root=Path.cwd())
        self.assertTrue(result["ready"])
        self.assertFalse(result["requires_multimodal_model"])
        self.assertGreaterEqual(result["score"], 90)

    def test_incomplete_spec_returns_machine_readable_failures(self):
        result = score_visual_spec(
            {"kind": "dashboard", "charts": [{"type": "bar"}]},
            skill_root=Path.cwd(),
        )
        self.assertFalse(result["ready"])
        self.assertIn("title", result["failed_checks"])
        self.assertIn("dataset_binding", result["failed_checks"])

    def test_standard_profile_caps_components_and_preserves_detail(self):
        spec = {
            "interactions": {"filters": ["日期"]},
            "charts": [
                *[
                    {"type": "bar", "intent": "comparison", "dataset_name": "1",
                     "x_axis": ["区域"], "y_axis": ["销售额"]}
                    for _ in range(14)
                ],
                {"type": "table-info", "intent": "detail", "dataset_name": "1",
                 "x_axis": ["区域"], "y_axis": ["销售额"]},
            ],
        }
        result = apply_complexity_profile(spec, "standard")
        self.assertEqual(len(result["charts"]), 10)
        self.assertEqual(result["charts"][-1]["intent"], "detail")
        self.assertEqual(result["complexity"]["component_limit"], 10)
        self.assertTrue(all("layout" in chart for chart in result["charts"]))

    def test_complexity_refreshes_design_density(self):
        spec = {
            "kind": "dataV",
            "charts": [
                {"type": "bar", "intent": "comparison", "dataset_name": "1",
                 "x_axis": ["区域"], "y_axis": ["销售额"]}
                for _ in range(9)
            ],
            "interactions": {},
            "layout_strategy": {"variant": "balanced"},
            "design_inspiration": {"design_dimensions": {"density": "rich"}},
        }
        result = apply_complexity_profile(spec, "compact")
        self.assertEqual(result["design_inspiration"]["design_dimensions"]["density"], "compact")

    def test_compact_profile_preserves_role_diversity(self):
        charts = [
            *[{"type": "indicator", "intent": "kpi"} for _ in range(3)],
            {"type": "map", "intent": "geospatial"},
            {"type": "bubble-map", "intent": "geospatial"},
            {"type": "line", "intent": "trend"},
            {"type": "bar-horizontal", "intent": "ranking"},
            {"type": "pie-donut", "intent": "composition"},
            {"type": "table-info", "intent": "detail"},
        ]
        result = apply_complexity_profile({"charts": charts, "interactions": {}}, "compact")
        roles = {item["intent"] for item in result["charts"]}
        self.assertTrue({"kpi", "geospatial", "trend", "detail"}.issubset(roles))
        self.assertLessEqual(sum(item["intent"] == "kpi" for item in result["charts"]), 2)


if __name__ == "__main__":
    unittest.main()
