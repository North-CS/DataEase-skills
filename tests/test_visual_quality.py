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

    def test_fixed_datav_reports_overcrowding_while_dashboard_can_expand(self):
        charts = [
            {
                "type": ("bar", "line", "pie-donut")[index % 3],
                "title": f"分析组件 {index + 1}",
                "dataset_name": "1",
                "x_axis": ["区域"],
                "y_axis": ["销售额"],
            }
            for index in range(16)
        ]
        common = {
            "title": "高密度分析",
            "theme": "tech-blue",
            "charts": charts,
            "interactions": {"filters": ["日期"]},
        }
        datav = score_visual_spec(
            {**common, "kind": "dataV", "canvas": {"width": 1920, "height": 1080}},
            skill_root=Path.cwd(),
        )
        dashboard = score_visual_spec(
            {**common, "kind": "dashboard"},
            skill_root=Path.cwd(),
        )
        self.assertFalse(datav["ready"])
        self.assertIn("layout_readability", datav["failed_checks"])
        self.assertTrue(dashboard["layout"]["canvas"]["height"] > 1080)
        self.assertNotIn("layout_readability", dashboard["failed_checks"])

    def test_autopilot_profile_reduces_fixed_datav_density_until_readable(self):
        spec = {
            "kind": "dataV",
            "title": "低能力模型也可安全创建",
            "theme": "tech-blue",
            "charts": [
                {
                    "type": ("table-info", "line", "map", "bar-horizontal")[index % 4],
                    "intent": ("detail", "trend", "geospatial", "ranking")[index % 4],
                    "title": f"组件 {index + 1}",
                    "dataset_name": "1",
                    "x_axis": ["区域"],
                    "y_axis": ["销售额"],
                }
                for index in range(16)
            ],
            "interactions": {"filters": ["日期"]},
        }
        result = apply_complexity_profile(spec, "rich")
        quality = score_visual_spec(result, skill_root=Path.cwd())
        self.assertTrue(quality["ready"])
        self.assertGreater(result["complexity"]["readability_reduction"], 0)
        self.assertEqual(result["complexity"]["readability_policy"], "fit-fixed-canvas")

    def test_autopilot_dashboard_expands_before_persisting_layouts(self):
        spec = {
            "kind": "dashboard",
            "title": "滚动分析",
            "theme": "business-light",
            "charts": [
                {
                    "type": "bar",
                    "intent": "comparison",
                    "title": f"组件 {index + 1}",
                    "dataset_name": "1",
                    "x_axis": ["区域"],
                    "y_axis": ["销售额"],
                }
                for index in range(10)
            ],
            "interactions": {"filters": ["日期"]},
        }
        result = apply_complexity_profile(spec, "standard")
        self.assertGreater(result["canvas"]["height"], 1080)
        self.assertTrue(score_visual_spec(result, skill_root=Path.cwd())["ready"])

    def test_excessive_kpis_and_long_repeated_titles_fail_visual_hierarchy(self):
        title = "市场风险指标监控数据集 · 当前数值与最大目标数值综合评估"
        spec = {
            "kind": "dataV",
            "title": "金融驾驶舱",
            "theme": "dark-gold",
            "charts": [
                {
                    "type": "indicator",
                    "intent": "kpi",
                    "title": title,
                    "dataset_name": "1",
                    "x_axis": ["指标"],
                    "y_axis": [f"指标{index}"],
                }
                for index in range(6)
            ],
            "interactions": {"filters": ["指标"]},
        }
        result = score_visual_spec(spec, skill_root=Path.cwd())
        self.assertFalse(result["ready"])
        self.assertIn("visual_hierarchy", result["failed_checks"])
        issue_types = {item["type"] for item in result["visual_hierarchy"]["issues"]}
        self.assertIn("too_many_kpis", issue_types)
        self.assertIn("repeated_titles", issue_types)


if __name__ == "__main__":
    unittest.main()
