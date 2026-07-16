from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from scripts.dataease_skill.audit import AuditLog
from scripts.dataease_skill.automation_ops import handle_automation_operation
from scripts.dataease_skill.config import Settings
from scripts.dataease_skill.errors import DataEaseError
from scripts.dataease_skill.safety import PlanStore


class FakeAutomationClient:
    def __init__(self) -> None:
        self.settings = Settings(base_url="http://example", x_de_token="token", org_id="1")

    def data(self, method: str, path: str, payload=None):
        if path == "/license/version":
            return "2.10.25"
        if path.startswith("/report/pager/"):
            return {"records": [], "total": 0}
        if path == "/report/info/20":
            return {
                "taskId": "20",
                "name": "Codex Report",
                "rid": "100",
                "rtid": 0,
                "rateType": 1,
                "rateVal": "2021-08-01 09:00:00",
                "emailList": ["private@example.invalid"],
            }
        if path.startswith("/webhook/pager/"):
            return {"records": [], "total": 0}
        if path == "/webhook/get/30":
            return {
                "id": "30",
                "name": "Codex Webhook",
                "url": "https://hooks.example.invalid/path?token=private",
                "secret": "existing-secret",
                "contentType": "application/json",
                "ssl": True,
                "msgTemplate": "{}",
            }
        raise AssertionError(f"unexpected request: {method} {path}")


class AutomationMutationTests(unittest.TestCase):
    def _runtime(self, root: Path):
        return (
            Settings(base_url="http://example", x_de_token="token", output_dir=root),
            FakeAutomationClient(),
            PlanStore(root),
            AuditLog(root),
        )

    def test_report_create_plan_hides_recipients_and_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "report.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "name": "Codex Report",
                        "rid": "100",
                        "rtid": 0,
                        "rateType": 1,
                        "rateVal": "2021-08-01 09:00:00",
                        "content": "confidential report text",
                        "emailList": ["private@example.invalid"],
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(domain="report", action="create", spec=str(spec_path), apply=False, plan_id="", confirm_token="")
            settings, client, plans, audit = self._runtime(root)
            result = handle_automation_operation(args, settings, client, plans, audit)
            plan_text = (root / "plans" / f"{result['result']['plan_id']}.json").read_text(encoding="utf-8")
            self.assertNotIn("private@example.invalid", plan_text)
            self.assertNotIn("confidential report text", plan_text)
            self.assertEqual(result["result"]["risk"], "L3")

    def test_report_update_requires_no_rollback_ack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "report.json"
            spec_path.write_text(
                json.dumps({"taskId": "20", "name": "Codex Report", "rid": "100", "rtid": 0, "rateType": 1, "rateVal": "2021-08-01 09:00:00"}),
                encoding="utf-8",
            )
            args = argparse.Namespace(domain="report", action="update", spec=str(spec_path), ack_no_rollback=False, apply=False, plan_id="", confirm_token="")
            settings, client, plans, audit = self._runtime(root)
            with self.assertRaises(DataEaseError) as raised:
                handle_automation_operation(args, settings, client, plans, audit)
            self.assertEqual(raised.exception.code, "rollback_ack_required")

    def test_webhook_create_plan_hides_url_and_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "webhook.json"
            spec_path.write_text(
                json.dumps({"name": "Codex Webhook", "url": "https://hooks.example.invalid/private", "secret": "new-secret", "contentType": "application/json", "ssl": True, "msgTemplate": "{}"}),
                encoding="utf-8",
            )
            args = argparse.Namespace(domain="webhook", action="save", spec=str(spec_path), ack_no_rollback=False, apply=False, plan_id="", confirm_token="")
            settings, client, plans, audit = self._runtime(root)
            result = handle_automation_operation(args, settings, client, plans, audit)
            plan_text = (root / "plans" / f"{result['result']['plan_id']}.json").read_text(encoding="utf-8")
            self.assertNotIn("hooks.example.invalid", plan_text)
            self.assertNotIn("new-secret", plan_text)
            self.assertEqual(result["result"]["risk"], "L2")

    def test_webhook_update_requires_no_rollback_ack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "webhook.json"
            spec_path.write_text(
                json.dumps({"id": "30", "name": "Codex Webhook", "url": "https://hooks.example.invalid/new", "contentType": "application/json", "ssl": True, "msgTemplate": "{}"}),
                encoding="utf-8",
            )
            args = argparse.Namespace(domain="webhook", action="save", spec=str(spec_path), ack_no_rollback=False, apply=False, plan_id="", confirm_token="")
            settings, client, plans, audit = self._runtime(root)
            with self.assertRaises(DataEaseError) as raised:
                handle_automation_operation(args, settings, client, plans, audit)
            self.assertEqual(raised.exception.code, "rollback_ack_required")


if __name__ == "__main__":
    unittest.main()
