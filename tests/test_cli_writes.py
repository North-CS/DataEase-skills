from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.dataease_skill.audit import AuditLog
from scripts.dataease_skill.cli import (
    _active_view_ids,
    _capture,
    _content_digest,
    _filling_create,
    _filling_delete,
    _filling_row_delete,
    _filling_row_save,
    _filling_truncate,
    _visual_delete,
    _visual_publish,
    _write_snapshot,
)
from scripts.dataease_skill.config import Settings
from scripts.dataease_skill.errors import DataEaseError
from scripts.dataease_skill.safety import PlanStore


class PlannedWriteTests(unittest.TestCase):
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
