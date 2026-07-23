import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from dataease_skill.interaction_planner import (
    build_query_component, infer_filter_cascades, normalize_interactions,
    query_style_for_background, shared_linkages,
)


class InteractionPlannerTests(unittest.TestCase):
    def test_query_component_binds_real_field_and_targets(self):
        field = {"id": "10", "name": "区域", "originName": "region", "type": "VARCHAR", "deType": 0}
        measure = {"id": "20", "name": "销售额", "originName": "sales", "type": "DECIMAL", "deType": 3}
        component, view = build_query_component(
            "99", "100", [field], ["1", "2"], canvas_width=1920, canvas_height=1080,
            dataset_fields=[field, measure],
        )
        self.assertEqual(component["component"], "VQuery")
        self.assertTrue(component["isShow"])
        self.assertEqual(component["category"], "base")
        self.assertEqual(component["propValue"][0]["checkedFieldsMap"], {"1": "10", "2": "10"})
        self.assertEqual(len(component["propValue"][0]["dataset"]["fields"]), 2)
        self.assertIsNone(component["propValue"][0]["defaultValue"])
        self.assertEqual(component["events"]["jump"]["type"], "_blank")
        self.assertEqual(component["commonBackground"]["innerPadding"]["top"], 12)
        self.assertEqual(component["matrixStyle"], {})
        self.assertEqual(view["tableId"], "100")

    def test_shared_linkage_only_uses_same_dataset_and_common_dimension(self):
        charts = [
            {"dataset_name": "100"}, {"dataset_name": "100"}, {"dataset_name": "200"},
        ]
        views = {
            "1": {"xAxis": [{"id": "10", "name": "区域"}]},
            "2": {"xAxis": [{"id": "10", "name": "区域"}]},
            "3": {"xAxis": [{"id": "30", "name": "区域"}]},
        }
        result = shared_linkages(charts, ["1", "2", "3"], views)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["linkageInfo"][0]["targetViewId"], "2")

    def test_interaction_defaults_are_safe(self):
        plan = normalize_interactions({"filters": ["日期", "区域"], "linkage": True})
        self.assertEqual(plan["filters"], ["日期", "区域"])
        self.assertTrue(plan["auto_linkage"])
        self.assertEqual(plan["jumps"], [])

    def test_geography_cascade_is_inferred_but_unrelated_filter_is_ignored(self):
        self.assertEqual(
            infer_filter_cascades(["统计月份", "大区", "省级行政区", "城市"]),
            [["大区", "省级行政区", "城市"]],
        )

    def test_explicit_filter_cascade_is_normalized(self):
        plan = normalize_interactions({
            "filters": ["品牌", "系列", "型号"],
            "filter_cascades": [["品牌", "系列", "型号"], ["不存在", "型号"]],
        })
        self.assertEqual(plan["filter_cascades"], [["品牌", "系列", "型号"]])

    def test_query_component_writes_native_cascade_dto(self):
        fields = [
            {"id": "10", "name": "大区", "type": "VARCHAR", "deType": 0},
            {"id": "11", "name": "省级行政区", "type": "VARCHAR", "deType": 0},
        ]
        component, _ = build_query_component(
            "99", "100", fields, ["1"], canvas_width=1920, canvas_height=1080,
            dataset_fields=fields, cascade_chains=[["大区", "省级行政区"]],
        )
        cascade = component["cascade"][0]
        self.assertEqual(cascade[0]["datasetId"], "100--991--10")
        self.assertEqual(cascade[1]["datasetId"], "100--992--11")
        self.assertEqual(cascade[0]["selectValue"], [])
        self.assertEqual(cascade[1]["currentSelectValue"], [])

    def test_query_style_uses_light_text_on_dark_background(self):
        dark = query_style_for_background("#031525", "#26C6DA")
        light = query_style_for_background("#F5F6F7", "#1E90FF")
        self.assertEqual(dark["labelColor"], "#EAF7FF")
        self.assertEqual(dark["btnColor"], "#26C6DA")
        self.assertEqual(light["labelColor"], "#1F2329")
        self.assertEqual(light["bgColor"], "#FFFFFF")

    def test_chart_alias_is_normalized_for_drill_and_jump_rules(self):
        plan = normalize_interactions({
            "drill_hierarchies": [{"chart": "区域销售", "fields": ["省", "市"]}],
            "jumps": [{"chart": "区域销售", "url": "https://example.invalid"}],
        })
        self.assertEqual(plan["drill_hierarchies"][0]["source"], "区域销售")
        self.assertEqual(plan["jumps"][0]["source"], "区域销售")


if __name__ == "__main__":
    unittest.main()
