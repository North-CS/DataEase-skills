from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from scripts.dataease_skill.admin_ops import handle_admin_mutation
from scripts.dataease_skill.audit import AuditLog
from scripts.dataease_skill.config import Settings
from scripts.dataease_skill.errors import DataEaseError
from scripts.dataease_skill.safety import PlanStore


class FakeAdminClient:
    def __init__(self) -> None:
        self.settings = Settings(base_url="http://example", x_de_token="token", org_id="1")
        self.roles = [
            {"id": "2", "name": "组织管理员", "readonly": False, "root": True},
            {"id": "3", "name": "普通用户", "readonly": True, "root": True},
            {"id": "10", "name": "Codex Role", "readonly": False, "root": False},
        ]
        self.role = {"id": "10", "name": "Codex Role", "typeCode": 0, "desc": ""}
        self.user = {
            "id": "20",
            "account": "codex_user",
            "name": "Codex User",
            "email": "codex@example.invalid",
            "roleIds": ["10"],
            "enable": True,
            "mfaEnable": False,
            "variables": [],
        }

    def data(self, method: str, path: str, payload=None):
        if path == "/license/version":
            return "2.10.25"
        if path == "/user/queryById/20":
            return dict(self.user)
        if path == "/role/query":
            return [dict(role) for role in self.roles]
        if path == "/org/detail/30":
            return {"id": "30", "name": "Codex Org", "pid": "0"}
        if path == "/org/resourceExist/30":
            return False
        if path == "/role/detail/10":
            return dict(self.role)
        if path == "/role/edit":
            self.role.update(payload)
            return None
        if path == "/user/edit":
            self.user.update(payload)
            return None
        if path == "/user/enable":
            self.user["enable"] = bool(payload["enable"])
            return None
        if path == "/user/create":
            return "20"
        raise AssertionError(f"unexpected request: {method} {path}")


class AdminMutationTests(unittest.TestCase):
    def test_user_create_plan_stores_digest_not_pii(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "user.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "name": "Codex User",
                        "account": "codex_user",
                        "email": "codex@example.invalid",
                        "phone": "13800000000",
                        "roleIds": [10],
                        "enable": True,
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                action="user-create",
                apply=False,
                spec=str(spec_path),
                plan_id="",
                confirm_token="",
            )
            plans = PlanStore(root)
            result = handle_admin_mutation(
                args,
                Settings(base_url="http://example", x_de_token="token", output_dir=root),
                FakeAdminClient(),
                plans,
                AuditLog(root),
            )
            plan_path = root / "plans" / f"{result['result']['plan_id']}.json"
            plan_text = plan_path.read_text(encoding="utf-8")
            self.assertNotIn("codex@example.invalid", plan_text)
            self.assertNotIn("13800000000", plan_text)
            self.assertEqual(result["result"]["risk"], "L1")

    def test_user_create_with_administrator_role_is_l3(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "admin-user.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "name": "Admin User",
                        "account": "admin_user",
                        "email": "admin@example.invalid",
                        "roleIds": [2],
                        "enable": True,
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                action="user-create",
                apply=False,
                spec=str(spec_path),
                plan_id="",
                confirm_token="",
            )
            result = handle_admin_mutation(
                args,
                Settings(base_url="http://example", x_de_token="token", output_dir=root),
                FakeAdminClient(),
                PlanStore(root),
                AuditLog(root),
            )
            self.assertEqual(result["result"]["risk"], "L3")
            self.assertTrue(result["result"]["confirmation_token"])
            self.assertTrue(result["changes"][0]["administrator_role"])

    def test_user_create_rejects_role_state_change_after_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "admin-user.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "name": "Admin User",
                        "account": "admin_user",
                        "email": "admin@example.invalid",
                        "roleIds": [2],
                        "enable": True,
                    }
                ),
                encoding="utf-8",
            )
            settings = Settings(base_url="http://example", x_de_token="token", output_dir=root)
            client = FakeAdminClient()
            plans = PlanStore(root)
            dry_run = handle_admin_mutation(
                argparse.Namespace(
                    action="user-create",
                    apply=False,
                    spec=str(spec_path),
                    plan_id="",
                    confirm_token="",
                ),
                settings,
                client,
                plans,
                AuditLog(root),
            )
            client.roles[0]["readonly"] = True
            with self.assertRaises(DataEaseError) as raised:
                handle_admin_mutation(
                    argparse.Namespace(
                        action="user-create",
                        apply=True,
                        spec=str(spec_path),
                        plan_id=dry_run["result"]["plan_id"],
                        confirm_token=dry_run["result"]["confirmation_token"],
                    ),
                    settings,
                    client,
                    plans,
                    AuditLog(root),
                )
            self.assertEqual(raised.exception.code, "plan_risk_changed")

    def test_role_edit_is_l3_and_requires_confirmation_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "role.json"
            spec_path.write_text(
                json.dumps({"id": 10, "name": "Updated Role", "desc": "changed"}),
                encoding="utf-8",
            )
            settings = Settings(base_url="http://example", x_de_token="token", output_dir=root)
            client = FakeAdminClient()
            plans = PlanStore(root)
            dry_run = handle_admin_mutation(
                argparse.Namespace(
                    action="role-edit",
                    apply=False,
                    spec=str(spec_path),
                    plan_id="",
                    confirm_token="",
                ),
                settings,
                client,
                plans,
                AuditLog(root),
            )
            self.assertEqual(dry_run["result"]["risk"], "L3")
            self.assertTrue(dry_run["result"]["confirmation_token"])
            with self.assertRaises(DataEaseError) as raised:
                handle_admin_mutation(
                    argparse.Namespace(
                        action="role-edit",
                        apply=True,
                        spec=str(spec_path),
                        plan_id=dry_run["result"]["plan_id"],
                        confirm_token="",
                    ),
                    settings,
                    client,
                    plans,
                    AuditLog(root),
                )
            self.assertEqual(raised.exception.code, "confirmation_required")

    def test_user_edit_role_change_is_l3_but_profile_edit_is_l2(self) -> None:
        for role_ids, expected_risk in (([10], "L2"), ([3], "L3")):
            with self.subTest(role_ids=role_ids), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                spec_path = root / "user.json"
                spec_path.write_text(
                    json.dumps(
                        {
                            "id": 20,
                            "name": "Updated User",
                            "account": "codex_user",
                            "email": "codex@example.invalid",
                            "roleIds": role_ids,
                            "enable": True,
                        }
                    ),
                    encoding="utf-8",
                )
                result = handle_admin_mutation(
                    argparse.Namespace(
                        action="user-edit",
                        apply=False,
                        spec=str(spec_path),
                        plan_id="",
                        confirm_token="",
                    ),
                    Settings(base_url="http://example", x_de_token="token", output_dir=root),
                    FakeAdminClient(),
                    PlanStore(root),
                    AuditLog(root),
                )
                self.assertEqual(result["result"]["risk"], expected_risk)
                self.assertEqual(result["changes"][0]["permission_sensitive"], expected_risk == "L3")
                self.assertEqual(bool(result["result"]["confirmation_token"]), expected_risk == "L3")

    def test_digest_bound_apply_rejects_changed_spec(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "org.json"
            spec_path.write_text('{"name":"Codex Org","pid":0}', encoding="utf-8")
            plans = PlanStore(root)
            settings = Settings(base_url="http://example", x_de_token="token", output_dir=root)
            client = FakeAdminClient()
            dry_args = argparse.Namespace(
                action="organization-create",
                apply=False,
                spec=str(spec_path),
                plan_id="",
                confirm_token="",
            )
            dry_run = handle_admin_mutation(dry_args, settings, client, plans, AuditLog(root))
            spec_path.write_text('{"name":"Changed Org","pid":0}', encoding="utf-8")
            apply_args = argparse.Namespace(
                action="organization-create",
                apply=True,
                spec=str(spec_path),
                plan_id=dry_run["result"]["plan_id"],
                confirm_token="",
            )
            with self.assertRaises(DataEaseError) as raised:
                handle_admin_mutation(apply_args, settings, client, plans, AuditLog(root))
            self.assertEqual(raised.exception.code, "spec_changed")

    def test_user_disable_is_l3_and_enable_is_l2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(base_url="http://example", x_de_token="token", output_dir=root)
            client = FakeAdminClient()
            for value, expected_risk in (("false", "L3"), ("true", "L2")):
                args = argparse.Namespace(
                    action="user-enable",
                    apply=False,
                    id="20",
                    account="codex_user",
                    enable=value,
                    plan_id="",
                    confirm_token="",
                )
                result = handle_admin_mutation(args, settings, client, PlanStore(root), AuditLog(root))
                self.assertEqual(result["result"]["risk"], expected_risk)
                if expected_risk == "L3":
                    self.assertTrue(result["result"]["confirmation_token"])

    def test_admin_delete_requires_no_rollback_ack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = argparse.Namespace(action="role-delete", apply=False, ack_no_rollback=False)
            with self.assertRaises(DataEaseError) as raised:
                handle_admin_mutation(
                    args,
                    Settings(base_url="http://example", x_de_token="token", output_dir=root),
                    FakeAdminClient(),
                    PlanStore(root),
                    AuditLog(root),
                )
            self.assertEqual(raised.exception.code, "rollback_ack_required")


if __name__ == "__main__":
    unittest.main()
