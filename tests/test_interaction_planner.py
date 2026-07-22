import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from dataease_skill.interaction_planner import build_query_component, normalize_interactions, shared_linkages


class InteractionPlannerTests(unittest.TestCase):
    def test_query_component_binds_real_field_and_targets(self):
        field = {"id": "10", "name": "区域", "originName": "region", "type": "VARCHAR", "deType": 0}
        component, view = build_query_component(
            "99", "100", [field], ["1", "2"], canvas_width=1920, canvas_height=1080
        )
        self.assertEqual(component["component"], "VQuery")
        self.assertEqual(component["propValue"][0]["checkedFieldsMap"], {"1": "10", "2": "10"})
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


if __name__ == "__main__":
    unittest.main()
