from __future__ import annotations

import argparse
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.dataease_skill.config import Settings
from scripts.dataease_skill.errors import DataEaseError
from scripts.dataease_skill.audit import AuditLog
from scripts.dataease_skill.model_ops import handle_model_operation, prepare_new_model_spec, validate_model_spec
from scripts.dataease_skill.permission_ops import _normalize as normalize_permission_bundle
from scripts.dataease_skill.plugin_ops import _package, _plugin_summary
from scripts.dataease_skill.solution_ops import _sample_quality, build_solution_manifest, execute_solution
from scripts.dataease_skill.safety import PlanStore
from scripts.dataease_skill.transfer_ops import (
    BUNDLE_SCHEMA,
    _linkage_pairs,
    _prepare_dataset_restore_payload,
    _prepare_visual_restore_payload,
    _replace_ids,
    build_bundle,
)
from scripts.dataease_skill.visual_ops import patch_visual_payload, verify_visual_patch


class VisualClient:
    def data(self, method, path, payload=None):
        if path == "/datasetTree/details/200":
            return {"allFields": [{"id": "9", "name": "利润", "originName": "profit",
                                    "datasetGroupId": "200", "datasetTableId": "201",
                                    "datasourceId": "202", "dataeaseName": "f_profit",
                                    "type": "DECIMAL", "deType": 2, "groupType": "q"}]}
        raise AssertionError((method, path, payload))


class BundleClient:
    def __init__(self) -> None:
        self.settings = Settings(base_url="http://example", x_de_token="token", org_id="1")

    def data(self, method, path, payload=None):
        if path == "/license/version":
            return "2.10.25"
        if path == "/dataVisualization/findById":
            return {"id": "10", "name": "经营大屏", "type": "dataV",
                    "componentData": "[]", "canvasStyleData": "{}", "canvasViewInfo": {}}
        if path == "/linkage/getVisualizationAllLinkageInfo/10/snapshot":
            return {"100": ["200"]}
        raise AssertionError((method, path, payload))


class SolutionClient:
    def __init__(self) -> None:
        self.settings = Settings(base_url="http://example", x_de_token="token", org_id="1")

    def data(self, method, path, payload=None):
        if path == "/license/version":
            return "2.10.25"
        if path == "/datasetTree/tree":
            return [{"id": "100", "name": "销售", "leaf": True}]
        if path == "/datasetTree/details/100":
            return {"allFields": [
                {"id": "1", "name": "日期", "type": "DATE", "deType": 1},
                {"id": "2", "name": "区域", "type": "VARCHAR", "deType": 0},
                {"id": "3", "name": "销售额", "type": "DECIMAL", "deType": 2},
            ]}
        if path == "/datasetData/previewData":
            return {"data": [{"区域": "华东", "销售额": 10}, {"区域": "华东", "销售额": 10},
                              {"区域": "华南", "销售额": None}]}
        raise AssertionError((method, path, payload))


class SolutionExecutionClient:
    def __init__(self, persist_permissions: bool = True) -> None:
        self.settings = Settings(base_url="http://example", x_de_token="token", org_id="1")
        self.permissions = []
        self.persist_permissions = persist_permissions
        self.visual_deleted = False

    def data(self, method, path, payload=None):
        if path == "/role/detail/20":
            return {"id": "20", "name": "analyst"}
        if path == "/auth/busiPermission":
            return {"permissions": list(self.permissions)}
        if path == "/auth/saveBusiPer":
            if self.persist_permissions:
                by_id = {int(item["id"]): dict(item) for item in self.permissions}
                for item in payload["permissions"]:
                    resource_id = int(item["id"])
                    if int(item["weight"]) == 0:
                        by_id.pop(resource_id, None)
                    else:
                        by_id[resource_id] = dict(item)
                self.permissions = list(by_id.values())
            return None
        if path.startswith("/dataVisualization/deleteLogic/"):
            self.visual_deleted = True
            return None
        raise AssertionError((method, path, payload))


class SolutionVisualEngine:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def deploy_multi(self, *args, **kwargs):
        return "900", "http://example/#/screen/900"


class SyncPolicyClient:
    def __init__(self, output_dir: Path, persist: bool = True) -> None:
        self.settings = Settings(base_url="http://example", x_de_token="token", org_id="1", output_dir=output_dir)
        self.sync_setting = {"syncRate": "MANUAL", "cron": ""}
        self.persist = persist

    def data(self, method, path, payload=None):
        if path == "/license/version":
            return "2.10.25"
        if path == "/datasource/hidePw/300":
            return {"id": "300", "name": "远程销售", "type": "ExcelRemote",
                    "syncSetting": self.sync_setting if self.persist else None}
        if path == "/datasource/cronNextTimes":
            return [1000, 2000, 3000]
        if path == "/datasource/update":
            if self.persist:
                self.sync_setting = payload["syncSetting"]
            return None
        raise AssertionError((method, path, payload))


class CalculatedFieldClient:
    def __init__(self) -> None:
        self.settings = Settings(base_url="http://example", x_de_token="token", org_id="1")
        self.fields = [{"id": "1", "name": "amount", "originName": "amount", "extField": 0}]

    def data(self, method, path, payload=None):
        if path == "/license/version":
            return "2.10.25"
        if path == "/datasetTree/details/100":
            return {"id": "100", "name": "sales", "allFields": list(self.fields)}
        if path == "/datasetField/save":
            self.fields.append(dict(payload))
            return None
        if path.startswith("/datasetField/get/"):
            field_id = path.rsplit("/", 1)[-1]
            return next((item for item in self.fields if str(item.get("id")) == field_id), None)
        raise AssertionError((method, path, payload))


class DatasetPermissionClient:
    def __init__(self, mutate: bool = True) -> None:
        self.settings = Settings(base_url="http://example", x_de_token="token", org_id="1")
        self.records = []
        self.mutate = mutate

    def data(self, method, path, payload=None):
        if path == "/license/version":
            return "2.10.25"
        if path == "/dataset/rowPermissions/pager/100/1/1000":
            return {"records": list(self.records), "total": len(self.records)}
        if path == "/dataset/rowPermissions/save":
            if self.mutate:
                self.records.append({**payload, "id": "500", "authTargetId": payload["authTargetIds"][0]})
            return None
        raise AssertionError((method, path, payload))


class AdvancedPlatformTests(unittest.TestCase):
    def test_visual_patch_moves_component_replaces_field_and_merges_theme(self) -> None:
        detail = {
            "id": "10",
            "componentData": json.dumps([{"id": "11", "component": "UserView", "x": 1, "y": 1,
                                           "style": {"left": 0, "top": 0}}]),
            "canvasStyleData": json.dumps({"themeId": "10001", "dashboard": {"showGrid": False}}),
            "canvasViewInfo": {"11": {"id": "11", "tableId": "200", "xAxis": [],
                                                "yAxis": [{"id": "3", "name": "销售额", "summary": "sum"}]}},
        }
        spec = {
            "component_updates": [{"id": "11", "patch": {"x": 8, "y": 4, "style": {"left": 120}}}],
            "field_replacements": [{"view_id": "11", "axis": "yAxis", "index": 0,
                                     "dataset_id": "200", "field_name": "利润", "aggregation": "avg"}],
            "theme": {"themeId": "neon", "dashboard": {"showGrid": True}},
        }
        patched, changes = patch_visual_payload(VisualClient(), detail, spec)
        component = json.loads(patched["componentData"])[0]
        style = json.loads(patched["canvasStyleData"])
        self.assertEqual((component["x"], component["y"], component["style"]["left"]), (8, 4, 120))
        self.assertEqual(patched["canvasViewInfo"]["11"]["yAxis"][0]["name"], "利润")
        self.assertEqual(patched["canvasViewInfo"]["11"]["yAxis"][0]["summary"], "avg")
        self.assertEqual(patched["canvasViewInfo"]["11"]["tableId"], "200")
        self.assertTrue(style["dashboard"]["showGrid"])
        self.assertEqual(len(changes), 3)

    def test_visual_patch_rejects_identity_overwrite(self) -> None:
        detail = {"componentData": '[{"id":"11"}]', "canvasStyleData": "{}", "canvasViewInfo": {}}
        with self.assertRaises(DataEaseError) as caught:
            patch_visual_payload(VisualClient(), detail,
                                 {"component_updates": [{"id": "11", "patch": {"id": "99"}}]})
        self.assertEqual(caught.exception.code, "unsafe_patch")

    def test_visual_restore_remaps_view_ids_and_linkage_pairs(self) -> None:
        payload = {
            "componentData": '[{"id":"11","component":"UserView"}]',
            "canvasViewInfo": {"11": {"id": "11", "tableId": "200"}},
        }
        prepared, mapping = _prepare_visual_restore_payload(payload)
        self.assertNotEqual(mapping["11"], "11")
        self.assertIn(mapping["11"], prepared["canvasViewInfo"])
        self.assertEqual(json.loads(prepared["componentData"])[0]["id"], mapping["11"])
        self.assertEqual(
            _linkage_pairs({"11#1": ["12#2", "13#3"]}),
            {("11", "1", "12", "2"), ("11", "1", "13", "3")},
        )

    def test_dataset_restore_remaps_table_field_and_expression_ids(self) -> None:
        payload = {
            "id": "100", "allFields": [{"id": "12", "datasetTableId": "11",
                                             "datasetGroupId": "100", "originName": "amount"}],
            "union": [{"currentDs": {"id": "11"}, "currentDsFields": [
                {"id": "12", "datasetTableId": "11", "datasetGroupId": "100"}
            ], "childrenDs": []}],
            "expression": "[12] / 100",
        }
        prepared, mapping = _prepare_dataset_restore_payload(payload, "100")
        self.assertNotEqual(mapping["11"], "11")
        self.assertNotEqual(mapping["12"], "12")
        self.assertEqual(prepared["union"][0]["currentDs"]["id"], mapping["11"])
        self.assertEqual(prepared["allFields"][0]["id"], mapping["12"])
        self.assertEqual(prepared["expression"], f"[{mapping['12']}] / 100")
        self.assertNotIn("datasetGroupId", prepared["allFields"][0])

    def test_visual_patch_verification_allows_unrelated_server_normalization(self) -> None:
        before = {
            "componentData": '[{"id":"11","x":1,"style":{"left":0}}]',
            "canvasStyleData": '{"backgroundColor":"#fff"}',
            "canvasViewInfo": {"11": {"id": "11", "tableId": "200", "yAxis": [
                {"id": "3", "name": "销售额", "originName": "amount", "summary": "sum"}
            ]}},
        }
        spec = {
            "component_updates": [{"id": "11", "patch": {"x": 2, "style": {"left": 20}}}],
            "view_updates": [{"id": "11", "patch": {"title": "销售分析", "customFilter": {"filter": []}}}],
            "theme": {"backgroundColor": "#000"},
        }
        expected = {
            "componentData": '[{"id":"11","x":2,"style":{"left":20}}]',
            "canvasStyleData": '{"backgroundColor":"#000"}',
            "canvasViewInfo": {"11": {"id": "11", "tableId": "200", "title": "销售分析",
                                            "yAxis": [{"id": "3", "name": "销售额", "summary": "sum"}]}},
        }
        after = {
            **expected,
            "canvasViewInfo": {"11": {**expected["canvasViewInfo"]["11"], "sceneId": "10"}},
        }
        result = verify_visual_patch(after, expected, spec, "before")
        self.assertTrue(result["server_normalized"])

    def test_model_validation_covers_sql_and_union(self) -> None:
        sql = {"name": "订单 SQL", "pid": "0", "nodeType": "dataset", "type": "sql", "mode": 0,
               "sql": "select * from orders", "allFields": []}
        union = {"name": "销售模型", "pid": "0", "nodeType": "dataset", "type": "union", "mode": 0,
                 "union": [{"currentDs": {"id": "1"}, "childrenDs": []}], "allFields": []}
        self.assertEqual(validate_model_spec(sql)["model_type"], "sql")
        self.assertEqual(validate_model_spec(union)["table_count"], 1)
        with self.assertRaises(DataEaseError):
            validate_model_spec({**sql, "sql": ""})

    def test_model_validation_accepts_native_physical_table_dto(self) -> None:
        physical = {
            "name": "销售明细", "pid": "0", "nodeType": "dataset", "type": None, "mode": 0,
            "union": [{"currentDs": {"tableName": "sales", "type": "db"},
                       "currentDsFields": [], "childrenDs": [],
                       "unionToParent": {"unionType": "left", "unionFields": []}}],
            "allFields": [],
        }
        result = validate_model_spec(physical)
        self.assertEqual(result["model_type"], "physical")
        self.assertEqual(result["table_count"], 1)
        self.assertIn("physical-table", result["features"])

    def test_new_join_model_gets_stable_unique_client_identities(self) -> None:
        field = lambda name: {"originName": name, "name": name, "type": "INT", "deType": 2}
        spec = {
            "name": "订单客户", "pid": "0", "nodeType": "dataset", "type": None, "mode": 0,
            "union": [{
                "currentDs": {"tableName": "orders", "datasourceId": "10", "type": "db"},
                "currentDsFields": [field("order_id"), field("customer_id")],
                "childrenDs": [{
                    "currentDs": {"tableName": "customers", "datasourceId": "10", "type": "db"},
                    "currentDsFields": [field("customer_id"), field("name")], "childrenDs": [],
                    "unionToParent": {"unionType": "left", "unionFields": [{
                        "parentField": field("customer_id"), "currentField": field("customer_id")
                    }]},
                }],
                "unionToParent": {"unionType": "left", "unionFields": []},
            }], "allFields": [],
        }
        first = prepare_new_model_spec(spec)
        second = prepare_new_model_spec(spec)
        self.assertEqual(first, second)
        aliases = [item["dataeaseName"] for item in first["allFields"]]
        self.assertEqual(len(aliases), len(set(aliases)))
        child = first["union"][0]["childrenDs"][0]
        link = child["unionToParent"]["unionFields"][0]
        self.assertEqual(link["parentField"]["id"], first["union"][0]["currentDsFields"][1]["id"])
        self.assertEqual(link["currentField"]["id"], child["currentDsFields"][0]["id"])

    def test_sync_policy_is_l3_and_plan_does_not_store_connection_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "sync.json"
            spec_path.write_text(json.dumps({
                "id": "300", "name": "远程销售", "type": "ExcelRemote",
                "configuration": {"url": "https://example.invalid/data.xlsx", "password": "never-store-this"},
                "syncSetting": {"syncRate": "CRON", "cron": "0 0 2 * * ? *"},
            }), encoding="utf-8")
            settings = Settings(base_url="http://example", x_de_token="token", org_id="1", output_dir=root)
            result = handle_model_operation(
                argparse.Namespace(action="sync-policy", spec=str(spec_path), ack_no_rollback=True,
                                   apply=False, plan_id="", confirm_token=""),
                settings, SyncPolicyClient(root), PlanStore(root), AuditLog(root),
            )
            self.assertEqual(result["result"]["risk"], "L3")
            plan_text = (root / "plans" / f"{result['result']['plan_id']}.json").read_text(encoding="utf-8")
            self.assertNotIn("never-store-this", plan_text)

    def test_sync_policy_requires_exact_readback(self) -> None:
        for persist, should_pass in ((True, True), (False, False)):
            with self.subTest(persist=persist), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                spec_path = root / "sync.json"
                spec_path.write_text(json.dumps({
                    "id": "300", "name": "远程销售", "type": "ExcelRemote",
                    "configuration": {"url": "https://example.invalid/data.xlsx"},
                    "syncSetting": {"syncRate": "CRON", "cron": "0 0 2 * * ? *"},
                }), encoding="utf-8")
                settings = Settings(base_url="http://example", x_de_token="token", org_id="1", output_dir=root)
                client = SyncPolicyClient(root, persist=persist)
                plans, audit = PlanStore(root), AuditLog(root)
                args = argparse.Namespace(action="sync-policy", spec=str(spec_path), ack_no_rollback=True,
                                          apply=False, plan_id="", confirm_token="")
                planned = handle_model_operation(args, settings, client, plans, audit)
                args.apply = True
                args.plan_id = planned["result"]["plan_id"]
                args.confirm_token = planned["result"]["confirmation_token"]
                if should_pass:
                    applied = handle_model_operation(args, settings, client, plans, audit)
                    self.assertEqual(applied["result"]["syncSetting"]["syncRate"], "CRON")
                else:
                    with self.assertRaises(DataEaseError) as raised:
                        handle_model_operation(args, settings, client, plans, audit)
                    self.assertEqual(raised.exception.code, "verification_failed")

    def test_calculated_field_create_verifies_void_save_by_dataset_readback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "calculated.json"
            spec_path.write_text(json.dumps({
                "datasetGroupId": "100", "name": "利润率", "originName": "[1] * 100",
                "dataeaseName": "f_profit_rate", "fieldShortName": "f_profit_rate",
                "groupType": "q", "type": "DECIMAL", "deType": 3, "extField": 2,
            }), encoding="utf-8")
            client = CalculatedFieldClient()
            settings = Settings(base_url="http://example", x_de_token="token", org_id="1", output_dir=root)
            plans, audit = PlanStore(root), AuditLog(root)
            args = argparse.Namespace(action="calculated-save", spec=str(spec_path), apply=False,
                                      plan_id="", confirm_token="")
            planned = handle_model_operation(args, settings, client, plans, audit)
            args.apply = True
            args.plan_id = planned["result"]["plan_id"]
            applied = handle_model_operation(args, settings, client, plans, audit)
            self.assertTrue(applied["result"]["id"])
            self.assertEqual(applied["result"]["name"], "利润率")

    def test_row_permission_create_requires_matching_readback(self) -> None:
        for mutate, should_pass in ((True, True), (False, False)):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                spec_path = root / "row.json"
                spec_path.write_text(json.dumps({
                    "datasetId": "100", "enable": True, "authTargetType": "user",
                    "authTargetIds": [20], "expressionTree": "{}", "whiteListUser": "[]",
                }), encoding="utf-8")
                client = DatasetPermissionClient(mutate=mutate)
                settings = Settings(base_url="http://example", x_de_token="token", org_id="1", output_dir=root)
                plans, audit = PlanStore(root), AuditLog(root)
                args = argparse.Namespace(action="permission-save", kind="row", spec=str(spec_path),
                                          apply=False, plan_id="", confirm_token="")
                planned = handle_model_operation(args, settings, client, plans, audit)
                args.apply = True
                args.plan_id = planned["result"]["plan_id"]
                args.confirm_token = planned["result"]["confirmation_token"]
                if should_pass:
                    applied = handle_model_operation(args, settings, client, plans, audit)
                    self.assertEqual(applied["result"]["changed_records"][0]["id"], "500")
                else:
                    with self.assertRaises(DataEaseError) as caught:
                        handle_model_operation(args, settings, client, plans, audit)
                    self.assertEqual(caught.exception.code, "verification_failed")

    def test_permission_bundle_supports_users_roles_and_multiple_scopes(self) -> None:
        value = normalize_permission_bundle({
            "subject_type": "user", "subject_id": "20", "identity": "alice",
            "scopes": {"dashboard": [{"id": "100", "weight": 7}],
                       "dataset": [{"id": 200, "weight": 3, "ext": 1}]},
        })
        self.assertEqual(value["subject_id"], 20)
        self.assertEqual(value["scopes"]["panel"][0], {"id": 100, "weight": 7, "ext": 0})

    def test_portable_bundle_and_reference_mapping(self) -> None:
        bundle = build_bundle(BundleClient(), "visual", "10", "dataV")
        self.assertEqual(bundle["schema"], BUNDLE_SCHEMA)
        self.assertEqual(bundle["relations"]["linkages"], {"100": ["200"]})
        mapped = _replace_ids({"tableId": "100", "ids": [100, "200", "300"]}, {"100": "900", "200": "901"})
        self.assertEqual(mapped, {"tableId": "900", "ids": ["900", "901", "300"]})

    def test_plugin_package_check_hashes_and_checks_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "driver.jar"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
                archive.writestr("plugin.class", b"bytecode")
            _, metadata = _package(str(path))
            self.assertTrue(metadata["valid_zip"])
            self.assertTrue(metadata["manifest"])
            self.assertEqual(len(metadata["sha256"]), 64)

    def test_plugin_package_rejects_archive_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "driver.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("plugin.class", b"bytecode")
            with self.assertRaises(DataEaseError) as raised:
                _package(str(path))
            self.assertEqual(raised.exception.code, "invalid_plugin_package")

    def test_plugin_list_summarizes_embedded_icon_payload(self) -> None:
        icon = "<svg>" + ("x" * 4096) + "</svg>"
        value = _plugin_summary({"id": "10", "name": "测试插件", "icon": icon, "version": "1.0"})
        self.assertNotIn("icon", value)
        self.assertEqual(value["name"], "测试插件")
        self.assertEqual(value["omitted_payloads"][0]["field"], "icon")
        self.assertEqual(value["omitted_payloads"][0]["bytes"], len(icon.encode("utf-8")))
        self.assertEqual(len(value["omitted_payloads"][0]["sha256"]), 64)

    def test_solution_manifest_enforces_confirmed_metrics_and_builds_pipeline(self) -> None:
        spec = {
            "name": "销售分析体系", "datasets": ["100"], "busi_type": "dataV",
            "metrics": [{"name": "销售额", "definition": "含税成交金额", "dataset_id": "100",
                         "field": "销售额", "aggregation": "sum", "confirmed": True}],
        }
        manifest = build_solution_manifest(SolutionClient(), spec)
        self.assertEqual(manifest["steps"][0]["id"], "quality")
        self.assertGreaterEqual(len(manifest["visual"]["charts"]), 3)
        with self.assertRaises(DataEaseError) as caught:
            build_solution_manifest(SolutionClient(), {**spec, "metrics": [{**spec["metrics"][0], "confirmed": False}]})
        self.assertEqual(caught.exception.code, "metric_confirmation_required")

    def test_solution_sample_quality_reports_nulls_and_duplicates(self) -> None:
        result = _sample_quality(SolutionClient(), {"id": "100"}, 100)
        self.assertEqual(result["sample_rows"], 3)
        self.assertEqual(result["duplicate_rows"], 1)
        self.assertEqual(result["null_ratios"]["销售额"], 0.3333)

    def test_solution_prepares_new_model_fields_before_planning(self) -> None:
        spec = {
            "name": "新模型方案", "datasets": [], "busi_type": "dataV",
            "models": [{
                "name": "新销售模型", "pid": "0", "nodeType": "dataset", "type": None, "mode": 0,
                "union": [{
                    "currentDs": {"tableName": "sales", "datasourceId": "10", "type": "db"},
                    "currentDsFields": [
                        {"originName": "region", "name": "区域", "type": "VARCHAR", "deType": 0},
                        {"originName": "amount", "name": "销售额", "type": "DECIMAL", "deType": 2},
                    ],
                    "childrenDs": [], "unionToParent": {"unionType": "left", "unionFields": []},
                }],
                "allFields": [],
            }],
            "metrics": [{"name": "销售额", "definition": "成交金额", "dataset_id": "$model:新销售模型",
                         "field": "销售额", "aggregation": "sum", "confirmed": True}],
        }
        manifest = build_solution_manifest(SolutionClient(), spec)
        self.assertTrue(manifest["quality"][0]["passed"])
        self.assertGreaterEqual(len(manifest["visual"]["charts"]), 1)

    def test_solution_resource_permission_requires_exact_readback_and_rolls_back(self) -> None:
        spec = {
            "models": [],
            "permissions": [{"subject_type": "role", "subject_id": "20", "identity": "analyst",
                             "scope": "screen"}],
        }
        manifest = {
            "name": "销售分析体系",
            "visual": {"title": "销售驾驶舱", "kind": "dataV", "theme": "neon-dark",
                       "charts": [{"type": "bar", "dataset_id": "100"}]},
        }
        settings = Settings(base_url="http://example", x_de_token="token", org_id="1")
        with patch("scripts.dataease_skill.visual_engine.MultiDataEaseChartEngine", SolutionVisualEngine):
            client = SolutionExecutionClient(persist_permissions=True)
            result = execute_solution(client, settings, spec, manifest)
            self.assertEqual(result["permissions_applied"], 1)
            self.assertEqual(client.permissions, [{"id": 900, "weight": 7, "ext": 0}])

            client = SolutionExecutionClient(persist_permissions=False)
            with self.assertRaises(DataEaseError) as caught:
                execute_solution(client, settings, spec, manifest)
            self.assertEqual(caught.exception.code, "verification_failed")
            self.assertTrue(client.visual_deleted)


if __name__ == "__main__":
    unittest.main()
