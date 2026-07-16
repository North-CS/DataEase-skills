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


class FieldProfileTests(unittest.TestCase):
    def test_roles_and_sensitive_detection(self):
        self.assertEqual(profile_field({"name": "订单日期", "type": "DATE"})["semantic_role"], "date")
        self.assertEqual(profile_field({"name": "销售额", "type": "DECIMAL"})["semantic_role"], "measure")
        self.assertTrue(profile_field({"name": "客户手机号", "type": "VARCHAR"})["sensitive"])

    def test_profile_and_visual_plan(self):
        profile = DatasetService(FakeClient()).profile("销售")
        plan = build_visual_plan(profile, "销售经营分析", "dataV")
        self.assertEqual(plan["kind"], "dataV")
        self.assertEqual(plan["theme"], "neon-dark")
        self.assertIn("line", [chart["type"] for chart in plan["charts"]])
        self.assertIn("bar", [chart["type"] for chart in plan["charts"]])
        table = next(chart for chart in plan["charts"] if chart["type"] == "table_info")
        self.assertEqual(table["x_axis"], ["日期", "区域"])
        self.assertEqual(table["y_axis"], ["销售额"])
        self.assertTrue(plan["recommendations"])


if __name__ == "__main__":
    unittest.main()
