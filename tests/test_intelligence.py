import unittest

from scripts.dataease_skill.datasets import DatasetService, profile_field
from scripts.dataease_skill.intelligence import build_visual_plan


class FakeClient:
    def data(self, method, path, payload=None):
        if path == "/datasetTree/tree":
            return [{"name": "销售", "id": "100", "leaf": True}]
        if path == "/datasetTree/details/100":
            return {
                "allFields": [
                    {"id": "1", "name": "日期", "type": "DATE", "deType": 1},
                    {"id": "2", "name": "区域", "type": "VARCHAR", "deType": 0},
                    {"id": "3", "name": "销售额", "type": "DECIMAL", "deType": 2},
                    {"id": "4", "name": "客户手机号", "type": "VARCHAR", "deType": 0},
                ]
            }
        raise AssertionError((method, path, payload))


class MultiDatasetClient:
    def data(self, method, path, payload=None):
        if path == "/datasetTree/tree":
            return [
                {"name": "销售", "id": "100", "leaf": True},
                {"name": "目标", "id": "200", "leaf": True},
            ]
        if path == "/datasetTree/details/100":
            return {
                "allFields": [
                    {"id": "1", "name": "月份", "type": "DATE", "deType": 1},
                    {"id": "2", "name": "区域", "type": "VARCHAR", "deType": 0},
                    {"id": "3", "name": "销售额", "type": "DECIMAL", "deType": 2},
                ]
            }
        if path == "/datasetTree/details/200":
            return {
                "allFields": [
                    {"id": "4", "name": "月份", "type": "DATE", "deType": 1},
                    {"id": "5", "name": "区域", "type": "VARCHAR", "deType": 0},
                    {"id": "6", "name": "目标额", "type": "DECIMAL", "deType": 2},
                ]
            }
        raise AssertionError((method, path, payload))


class FieldProfileTests(unittest.TestCase):
    def test_roles_and_sensitive_detection(self):
        self.assertEqual(profile_field({"name": "订单日期", "type": "DATE"})["semantic_role"], "date")
        self.assertEqual(profile_field({"name": "销售额", "type": "DECIMAL"})["semantic_role"], "measure")
        self.assertEqual(profile_field({"name": "日志流水ID", "type": "BIGINT"})["semantic_role"], "identifier")
        self.assertEqual(profile_field({"name": "orderId", "type": "BIGINT"})["semantic_role"], "identifier")
        self.assertEqual(profile_field({"name": "平均利润率(%)", "type": "DECIMAL"})["recommended_aggregation"], "avg")
        self.assertEqual(profile_field({"name": "综合评分", "type": "DECIMAL"})["recommended_aggregation"], "avg")
        self.assertTrue(profile_field({"name": "客户手机号", "type": "VARCHAR"})["sensitive"])

    def test_profile_and_visual_plan(self):
        profile = DatasetService(FakeClient()).profile("销售")
        plan = build_visual_plan(profile, "销售经营分析", "dataV")
        self.assertEqual(plan["kind"], "dataV")
        self.assertEqual(plan["theme"], "deep-ocean")
        self.assertEqual(plan["design_inspiration"]["grammar"], "retail-operations")
        self.assertFalse(plan["design_inspiration"]["template_copying"])
        self.assertIn("line", [chart["type"] for chart in plan["charts"]])
        self.assertIn("bar", [chart["type"] for chart in plan["charts"]])
        table = next(chart for chart in plan["charts"] if chart["type"] == "table_info")
        self.assertEqual(table["x_axis"], ["日期", "区域"])
        self.assertEqual(table["y_axis"], ["销售额"])
        self.assertEqual(table["layout"]["sizeX"], 72)
        self.assertEqual(plan["layout_strategy"]["engine"], "constraint-v3")
        self.assertTrue(plan["layout_strategy"]["requirements"])
        self.assertTrue(plan["recommendations"])

    def test_dashboard_plan_gets_responsive_semantic_layout(self):
        profile = DatasetService(FakeClient()).profile("销售")
        plan = build_visual_plan(profile, "销售仪表板", "dashboard")
        trend = next(chart for chart in plan["charts"] if chart["intent"] == "trend")
        composition = next(chart for chart in plan["charts"] if chart["intent"] == "composition")
        detail = next(chart for chart in plan["charts"] if chart["intent"] == "detail")
        self.assertGreaterEqual(trend["layout"]["sizeX"], 36)
        self.assertGreaterEqual(composition["layout"]["sizeX"], 24)
        self.assertEqual(detail["layout"]["sizeX"], 72)
        self.assertEqual(plan["kind"], "dashboard")

    def test_autopilot_emits_explicit_cascade_for_reversed_hierarchy_fields(self):
        profile = {
            "dataset": {"id": "500", "name": "区域销售"},
            "dimensions": [{"name": "省级行政区"}, {"name": "大区"}],
            "dates": [],
            "identifiers": [],
            "measures": [{"name": "销售额", "recommended_aggregation": "sum"}],
            "sensitive_fields": [],
        }
        plan = build_visual_plan(profile, "区域驾驶舱", "dashboard")
        self.assertEqual(plan["interactions"]["filters"], ["省级行政区", "大区"])
        self.assertEqual(
            plan["interactions"]["filter_cascades"],
            [["大区", "省级行政区"]],
        )

    def test_multi_dataset_plan_uses_every_dataset_and_suggests_relationships(self):
        service = DatasetService(MultiDatasetClient())
        plan = build_visual_plan([service.profile("销售"), service.profile("目标")], "经营驾驶舱", "dataV")
        self.assertEqual(plan["schema_version"], 2)
        self.assertEqual({chart["dataset_name"] for chart in plan["charts"]}, {"100", "200"})
        self.assertEqual({item["dataset_id"] for item in plan["kpi_candidates"]}, {"100", "200"})
        relationship_fields = {item["field"] for item in plan["dataset_relationships"]}
        self.assertIn("月份", relationship_fields)
        self.assertIn("区域", relationship_fields)
        self.assertTrue(plan["interactions"]["cross_dataset_linkage_requires_confirmation"])
        self.assertTrue(all(" · " not in chart["title"] for chart in plan["charts"]))
        self.assertTrue(all(chart["source_label"] for chart in plan["charts"]))

    def test_identifier_only_dataset_uses_distinct_count_instead_of_sum(self):
        profile = {
            "dataset": {"id": "300", "name": "访问日志"},
            "dimensions": [{"name": "渠道", "semantic_role": "dimension"}],
            "dates": [{"name": "访问时间", "semantic_role": "date"}],
            "identifiers": [{"name": "日志流水ID", "semantic_role": "identifier"}],
            "measures": [],
            "sensitive_fields": [],
        }
        plan = build_visual_plan(profile, "访问分析")
        self.assertEqual(plan["kpi_candidates"][0]["aggregation"], "count_distinct")
        self.assertTrue(all(chart["y_aggregations"] == ["count_distinct"] for chart in plan["charts"]))

    def test_rich_profile_expands_semantic_chart_selection_without_unbounded_growth(self):
        profile = {
            "dataset": {"id": "400", "name": "营销分析"},
            "dimensions": [
                {"name": "渠道"}, {"name": "省份"}, {"name": "转化阶段"}, {"name": "搜索关键词"},
            ],
            "dates": [{"name": "日期"}],
            "identifiers": [],
            "measures": [
                {"name": "销售额", "recommended_aggregation": "sum"},
                {"name": "订单量", "recommended_aggregation": "sum"},
                {"name": "利润率", "recommended_aggregation": "avg"},
            ],
            "sensitive_fields": [],
        }
        plan = build_visual_plan(profile, "营销驾驶舱", "dataV")
        types = {chart["type"] for chart in plan["charts"]}
        self.assertTrue({
            "indicator", "line", "area-stack", "bar-horizontal", "map", "bubble-map",
            "funnel", "word-cloud", "scatter", "pie-donut", "table_info", "table-pivot",
        }.issubset(types))
        self.assertIn("radar", plan["auto_plannable_chart_types"])
        self.assertEqual(plan["planning_policy"]["max_profile_charts_per_dataset"], 12)


if __name__ == "__main__":
    unittest.main()
