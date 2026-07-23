from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.dataease_skill.audit import AuditLog
from scripts.dataease_skill.cli import (
    _active_view_ids,
    _capture,
    _capture_pixel_from_detail,
    _content_digest,
    _compensate_created_visual,
    _filling_create,
    _filling_delete,
    _filling_row_delete,
    _filling_row_save,
    _filling_task_lifecycle,
    _filling_truncate,
    _visual_delete,
    _validate_visual_chart_data,
    _validate_query_capture,
    _visual_publish,
    _write_snapshot,
)
from scripts.dataease_skill.config import Settings
from scripts.dataease_skill.errors import DataEaseError
from scripts.dataease_skill.safety import PlanStore


class PlannedWriteTests(unittest.TestCase):
    def test_query_capture_requires_visible_conditions(self) -> None:
        capture = {"capture_meta": {"renderState": {
            "visibleQueryComponents": 1,
            "visibleQueryConditions": 2,
        }}}
        self.assertEqual(_validate_query_capture(capture, 2)["visible_query_conditions"], 2)
        with self.assertRaises(DataEaseError) as raised:
            _validate_query_capture(capture, 3)
        self.assertEqual(raised.exception.code, "query_component_not_visible")

    def test_capture_uses_saved_canvas_size_by_default(self) -> None:
        detail = {"canvasStyleData": '{"width":1920,"height":1440}'}
        self.assertEqual(_capture_pixel_from_detail(detail), "1920*1440")
        self.assertEqual(_capture_pixel_from_detail(detail, "1280*720"), "1280*720")

    def test_visual_data_validation_calls_every_non_query_view(self) -> None:
        class Client:
            def __init__(self):
                self.calls = []

            def data(self, method, path, payload=None):
                self.calls.append((method, path, payload))
                return {"data": {"data": []}}

        client = Client()
        detail = {"canvasViewInfo": {
            "1": {"type": "indicator", "title": "销售额", "xAxis": [], "yAxis": [{"id": "2"}]},
            "2": {"type": "VQuery", "title": "查询"},
        }}
        result = _validate_visual_chart_data(client, detail)
        self.assertEqual(len(result), 1)
        self.assertEqual(client.calls[0][1], "/chartData/getData")
        self.assertEqual(client.calls[0][2]["yaxis"], [{"id": "2"}])

    def test_visual_data_validation_rejects_failed_view(self) -> None:
        class Client:
            @staticmethod
            def data(method, path, payload=None):
                raise DataEaseError("指标字段无效", code="api_error", stage="request")

        detail = {"canvasViewInfo": {
            "1": {"type": "indicator", "title": "销售额", "xAxis": [], "yAxis": [{"id": "2"}]},
        }}
        with self.assertRaises(DataEaseError) as raised:
            _validate_visual_chart_data(Client(), detail)
        self.assertEqual(raised.exception.code, "visual_chart_data_failed")
        self.assertEqual(raised.exception.details["failures"][0]["view_id"], "1")

    def test_compensating_delete_reports_result(self) -> None:
        class Client:
            def data(self, method, path, payload=None):
                self.path = path
                return None

        client = Client()
        result = _compensate_created_visual(client, "42", "dashboard")
        self.assertTrue(result["deleted"])
        self.assertEqual(client.path, "/dataVisualization/deleteLogic/42/dashboard")

    @patch("scripts.dataease_skill.cli.subprocess.run")
    def test_capture_passes_credentials_in_environment_only(self, run) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                base_url="http://example",
                access_key="test-access",
                secret_key="test-secret",
                org_id="1",
                no_proxy="example,127.0.0.1",
                output_dir=root,
                skill_root=root,
            )
            run.return_value = SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

            self.assertTrue(_capture(settings, "42", "dashboard", "1920*1080")["ok"])

            command = run.call_args.args[0]
            child_env = run.call_args.kwargs["env"]
            self.assertNotIn("test-access", command)
            self.assertNotIn("test-secret", command)
            self.assertEqual(child_env["DATAEASE_ACCESS_KEY"], "test-access")
            self.assertEqual(child_env["DATAEASE_SECRET_KEY"], "test-secret")
            self.assertEqual(child_env["NO_PROXY"], "example,127.0.0.1")
            self.assertEqual(child_env["DATAEASE_CANVAS_TIMEOUT_MS"], "60000")

    @patch("scripts.dataease_skill.cli.time.sleep")
    @patch("scripts.dataease_skill.cli.subprocess.run")
    def test_capture_retries_only_transient_empty_page(self, run, sleep) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                base_url="http://example", access_key="a", secret_key="b",
                output_dir=root, skill_root=root,
            )
            run.side_effect = [
                SimpleNamespace(
                    returncode=1, stdout="",
                    stderr='ERR_INCOMPLETE_CHUNKED_ENCODING {"hasCanvas":false,"bodyText":"","appHtml":""}',
                ),
                SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr=""),
            ]
            self.assertTrue(_capture(settings, "42", "dataV", "1920*1080")["ok"])
            self.assertEqual(run.call_count, 2)
            sleep.assert_called_once_with(1)

    def test_l3_deletes_require_no_rollback_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plans, audit = PlanStore(root), AuditLog(root)
            visual_args = argparse.Namespace(apply=False, ack_no_rollback=False)
            filling_args = argparse.Namespace(apply=False, ack_no_rollback=False)
            with self.assertRaises(DataEaseError) as visual_error:
                _visual_delete(visual_args, None, None, plans, audit)
            with self.assertRaises(DataEaseError) as filling_error:
                _filling_delete(filling_args, None, None, plans, audit)
            self.assertEqual(visual_error.exception.code, "rollback_ack_required")
            self.assertEqual(filling_error.exception.code, "rollback_ack_required")

    def test_snapshot_redacts_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(base_url="http://example", x_de_token="token", output_dir=root, skill_root=root)
            path = Path(_write_snapshot(settings, "visual", "1", {"clientSecret": "must-not-leak"}))
            self.assertNotIn("must-not-leak", path.read_text(encoding="utf-8"))

    def test_active_view_ids_fall_back_to_components_for_unpublished_resource(self) -> None:
        detail = {
            "canvasViewInfo": {},
            "componentData": '[{"id":"101","component":"UserView"},{"id":"202","component":"Label"}]',
        }
        self.assertEqual(_active_view_ids(detail), ["101"])

    def test_filling_form_create_is_dry_run_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_path = Path(directory) / "form.json"
            spec_path.write_text(
                '{"name":"客户回访","nodeType":"folder","pid":"0"}',
                encoding="utf-8",
            )
            args = argparse.Namespace(
                action="create",
                spec=str(spec_path),
                apply=False,
                plan_id="",
                confirm_token="",
            )
            plans = PlanStore(Path(directory))
            result = _filling_create(args, None, plans, AuditLog(Path(directory)))

            self.assertEqual(result["mode"], "dry-run")
            self.assertEqual(result["result"]["risk"], "L1")
            self.assertEqual(result["result"]["operation"], "filling.create")

    def test_filling_task_requires_form_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_path = Path(directory) / "task.json"
            spec_path.write_text('{"name":"月度收集"}', encoding="utf-8")
            args = argparse.Namespace(
                action="task-create",
                spec=str(spec_path),
                apply=False,
                plan_id="",
                confirm_token="",
            )
            with self.assertRaises(DataEaseError) as raised:
                _filling_create(args, None, PlanStore(Path(directory)), AuditLog(Path(directory)))
            self.assertEqual(raised.exception.code, "invalid_spec")

    def test_filling_task_normalizes_documented_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "task.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "name": "月度收集",
                        "formId": "100",
                        "assignUsers": ["11", 12],
                        "rateType": 1,
                        "rateValue": "2026-08-01 09:00:00",
                    }
                ),
                encoding="utf-8",
            )
            client = type(
                "FakeClient",
                (),
                {
                    "settings": Settings(base_url="http://example", x_de_token="token"),
                    "data": staticmethod(lambda method, path, payload=None: "2.10.25" if path == "/license/version" else None),
                },
            )()
            plans = PlanStore(root)
            result = _filling_create(
                argparse.Namespace(action="task-create", spec=str(spec_path), apply=False, plan_id="", confirm_token=""),
                client,
                plans,
                AuditLog(root),
            )
            stored = plans.load(result["result"]["plan_id"])["spec"]
            self.assertEqual(stored["uidList"], [11, 12])
            self.assertEqual(stored["rateVal"], "2026-08-01 09:00:00")
            self.assertNotIn("assignUsers", stored)
            self.assertNotIn("rateValue", stored)
            self.assertTrue(result["warnings"])

    def test_filling_task_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "task.json"
            spec_path.write_text(
                '{"name":"月度收集","formId":"100","silentTypo":true}',
                encoding="utf-8",
            )
            with self.assertRaises(DataEaseError) as raised:
                _filling_create(
                    argparse.Namespace(action="task-create", spec=str(spec_path), apply=False, plan_id="", confirm_token=""),
                    None,
                    PlanStore(root),
                    AuditLog(root),
                )
            self.assertEqual(raised.exception.code, "unknown_spec_fields")

    def test_filling_form_can_bind_existing_datasource_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "form.json"
            spec_path.write_text(json.dumps({
                "name": "销售填报", "pid": "0", "nodeType": "form",
                "datasource": "100", "tableName": "sales_input",
                "forms": "[]", "useExistsTable": True,
            }), encoding="utf-8")
            plans = PlanStore(root)
            result = _filling_create(
                argparse.Namespace(action="create", spec=str(spec_path), apply=False,
                                   plan_id="", confirm_token=""),
                None, plans, AuditLog(root),
            )
            stored = plans.load(result["result"]["plan_id"])["spec"]
            self.assertEqual(stored["datasource"], "100")
            self.assertEqual(stored["tableName"], "sales_input")
            self.assertTrue(stored["useExistsTable"])

    def test_filling_task_stop_is_l2_and_verified(self) -> None:
        class Client:
            def __init__(self):
                self.settings = Settings(base_url="http://example", x_de_token="token")
                self.task = {"id": "9", "formId": "10", "name": "月度收集", "status": 0}

            def data(self, method, path, payload=None):
                if path == "/license/version":
                    return "2.10.25"
                if path == "/data-filling/task/info/9":
                    return dict(self.task)
                if path == "/data-filling/form/10/task/9/stop":
                    self.task["status"] = 2
                    return None
                raise AssertionError((method, path, payload))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = Client()
            plans, audit = PlanStore(root), AuditLog(root)
            args = argparse.Namespace(
                action="task-stop", form_id="10", task_id="9",
                ack_no_rollback=False, apply=False, plan_id="", confirm_token="",
            )
            planned = _filling_task_lifecycle(args, client, plans, audit)
            self.assertEqual(planned["result"]["risk"], "L2")
            args.apply = True
            args.plan_id = planned["result"]["plan_id"]
            applied = _filling_task_lifecycle(args, client, plans, audit)
            self.assertEqual(applied["result"]["after"]["status"], 2)

    def test_filling_task_delete_requires_l3_ack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(
                action="task-delete", form_id="10", task_id="9",
                ack_no_rollback=False, apply=False, plan_id="", confirm_token="",
            )
            with self.assertRaises(DataEaseError) as raised:
                _filling_task_lifecycle(
                    args, None, PlanStore(Path(directory)), AuditLog(Path(directory)),
                )
            self.assertEqual(raised.exception.code, "rollback_ack_required")

    def test_row_write_plan_stores_digest_not_row_values(self) -> None:
        class FakeClient:
            settings = Settings(base_url="http://example", x_de_token="token")

            @staticmethod
            def data(method, path, payload=None):
                if path == "/license/version":
                    return "2.10.25"
                return {
                    "id": "10",
                    "name": "客户回访",
                    "nodeType": "form",
                    "tableName": "customer_visit",
                    "datasource": "-1",
                    "updateTime": 1,
                }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "row.json"
            spec_path.write_text(
                '{"formId":"10","data":{"email":"alice@example.invalid","api_key":"value"}}',
                encoding="utf-8",
            )
            args = argparse.Namespace(apply=False, spec=str(spec_path), plan_id="", confirm_token="")
            plans = PlanStore(root)
            result = _filling_row_save(args, FakeClient(), plans, AuditLog(root))
            plan_text = (root / "plans" / f"{result['result']['plan_id']}.json").read_text(encoding="utf-8")
            self.assertNotIn("alice@example.invalid", plan_text)
            self.assertNotIn('"api_key"', plan_text)
            self.assertIn(_content_digest({"email": "alice@example.invalid", "api_key": "value"}), plan_text)

    def test_destructive_row_operations_require_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plans, audit = PlanStore(root), AuditLog(root)
            row_args = argparse.Namespace(apply=False, ack_no_rollback=False)
            truncate_args = argparse.Namespace(apply=False, ack_no_rollback=False)
            with self.assertRaises(DataEaseError) as row_error:
                _filling_row_delete(row_args, None, None, plans, audit)
            with self.assertRaises(DataEaseError) as truncate_error:
                _filling_truncate(truncate_args, None, plans, audit)
            self.assertEqual(row_error.exception.code, "rollback_ack_required")
            self.assertEqual(truncate_error.exception.code, "rollback_ack_required")

    def test_publish_dry_run_requires_exact_target(self) -> None:
        args = argparse.Namespace(
            apply=False,
            resource_id="",
            name="",
            busi_type="dashboard",
            status=1,
            plan_id="",
            confirm_token="",
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DataEaseError) as raised:
                _visual_publish(args, None, PlanStore(Path(directory)), AuditLog(Path(directory)))
            self.assertEqual(raised.exception.code, "invalid_input")


if __name__ == "__main__":
    unittest.main()
