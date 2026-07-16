from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from scripts.dataease_skill.audit import AuditLog
from scripts.dataease_skill.config import Settings
from scripts.dataease_skill.data_ops import handle_data_mutation
from scripts.dataease_skill.errors import DataEaseError
from scripts.dataease_skill.safety import PlanStore


class FakeDataClient:
    def __init__(self) -> None:
        self.settings = Settings(base_url="http://example", x_de_token="token", org_id="1")

    def data(self, method: str, path: str, payload=None):
        if path == "/license/version":
            return "2.10.25"
        if path == "/datasource/hidePw/10":
            return {
                "id": "10",
                "pid": "0",
                "name": "Codex Source",
                "nodeType": "datasource",
                "type": "mysql",
                "status": "Success",
            }
        if path == "/datasource/tree":
            return [{"id": "10", "pid": "0", "name": "Codex Source", "nodeType": "datasource"}]
        if path == "/datasource/perDelete/10":
            return True
        if path in {"/datasetTree/get/20", "/datasetTree/details/20"}:
            return {
                "id": "20",
                "pid": "0",
                "name": "Codex Dataset",
                "nodeType": "dataset",
                "type": "db",
                "mode": 0,
            }
        if path == "/datasetTree/tree":
            return [{"id": "20", "pid": "0", "name": "Codex Dataset", "nodeType": "dataset"}]
        if path == "/datasetTree/perDelete/20":
            return False
        raise AssertionError(f"unexpected request: {method} {path}")


class DataMutationTests(unittest.TestCase):
    def _runtime(self, root: Path):
        return (
            Settings(base_url="http://example", x_de_token="token", output_dir=root),
            FakeDataClient(),
            PlanStore(root),
            AuditLog(root),
        )

    def test_datasource_create_plan_stores_digest_not_connection_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "source.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "name": "Codex Source",
                        "pid": "0",
                        "type": "mysql",
                        "configuration": {"host": "db.internal", "password": "super-secret"},
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                domain="datasource",
                action="create",
                spec=str(spec_path),
                apply=False,
                plan_id="",
                confirm_token="",
            )
            settings, client, plans, audit = self._runtime(root)
            result = handle_data_mutation(args, settings, client, plans, audit)
            plan_text = (root / "plans" / f"{result['result']['plan_id']}.json").read_text(encoding="utf-8")
            self.assertNotIn("super-secret", plan_text)
            self.assertNotIn("db.internal", plan_text)
            self.assertEqual(result["result"]["risk"], "L1")

    def test_datasource_update_is_l3_and_requires_no_rollback_ack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "source.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "id": "10",
                        "name": "Codex Source",
                        "type": "mysql",
                        "configuration": {"host": "db.internal", "password": "changed"},
                    }
                ),
                encoding="utf-8",
            )
            settings, client, plans, audit = self._runtime(root)
            args = argparse.Namespace(
                domain="datasource",
                action="update",
                spec=str(spec_path),
                ack_no_rollback=False,
                apply=False,
                plan_id="",
                confirm_token="",
            )
            with self.assertRaises(DataEaseError) as raised:
                handle_data_mutation(args, settings, client, plans, audit)
            self.assertEqual(raised.exception.code, "rollback_ack_required")
            args.ack_no_rollback = True
            result = handle_data_mutation(args, settings, client, plans, audit)
            self.assertEqual(result["result"]["risk"], "L3")
            self.assertTrue(result["result"]["confirmation_token"])

    def test_datasource_delete_reports_downstream_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings, client, plans, audit = self._runtime(root)
            args = argparse.Namespace(
                domain="datasource",
                action="delete",
                id="10",
                name="Codex Source",
                ack_no_rollback=True,
                apply=False,
                plan_id="",
                confirm_token="",
            )
            result = handle_data_mutation(args, settings, client, plans, audit)
            self.assertTrue(result["warnings"])
            self.assertTrue(result["changes"][0]["referenced_by_downstream"])

    def test_dataset_update_is_l2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "dataset.json"
            spec_path.write_text(
                json.dumps({"id": "20", "name": "Codex Dataset", "nodeType": "dataset"}),
                encoding="utf-8",
            )
            settings, client, plans, audit = self._runtime(root)
            args = argparse.Namespace(
                domain="dataset",
                action="update",
                spec=str(spec_path),
                ack_no_rollback=False,
                apply=False,
                plan_id="",
                confirm_token="",
            )
            result = handle_data_mutation(args, settings, client, plans, audit)
            self.assertEqual(result["result"]["risk"], "L2")


if __name__ == "__main__":
    unittest.main()
