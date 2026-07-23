import unittest

from scripts.dataease_skill.visual_typography import (
    compact_title,
    responsive_typography,
    text_units,
)


class VisualTypographyTests(unittest.TestCase):
    def test_cjk_and_latin_title_width_is_estimated(self) -> None:
        self.assertEqual(text_units("AB大区"), 6)
        self.assertEqual(compact_title("全国区域销售地图分析", 10), "全国区域…")

    def test_narrow_dense_chart_uses_compact_typography(self) -> None:
        plan = responsive_typography(
            "line",
            "地图Demo-省级月度汇总 · completion_rate趋势",
            width=420,
            height=180,
            dimension_count=2,
            measure_count=3,
        )
        self.assertLessEqual(plan["title_font_size"], 14)
        self.assertEqual(plan["axis_font_size"], 10)
        self.assertLess(text_units(plan["display_title"]), text_units(plan["full_title"]))

    def test_indicator_hides_legend_and_scales_value_to_height(self) -> None:
        compact = responsive_typography("indicator", "客户数", width=480, height=150)
        tall = responsive_typography("indicator", "客户数", width=480, height=240)
        self.assertFalse(compact["legend_show"])
        self.assertGreater(tall["indicator_font_size"], compact["indicator_font_size"])

    def test_user_scene_policy_overrides_auto_scale_without_fixed_chart_template(self) -> None:
        normal = responsive_typography("scatter", "相关性分析", width=700, height=320)
        presentation = responsive_typography(
            "scatter", "相关性分析", width=700, height=320,
            policy={"mode": "presentation", "scale": 1.1, "legend_show": False},
        )
        self.assertGreater(presentation["title_font_size"], normal["title_font_size"])
        self.assertFalse(presentation["legend_show"])


if __name__ == "__main__":
    unittest.main()
