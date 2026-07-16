from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from scripts.dataease_skill.audit import AuditLog
from scripts.dataease_skill.config import Settings
from scripts.dataease_skill.errors import DataEaseError
from scripts.dataease_skill.safety import PlanStore
from scripts.dataease_skill.settings_ops import handle_settings_operation


class FakeSettingsClient:
    def __init__(self) -> None:
        self.settings = Settings(base_url="http://example", x_de_token="token", org_id="1")

    def data(self, method: str, path: str, payload=None):
        if path == "/license/version":
            return "2.10.25"
        if path == "/perSetting/mfa/query":
            return [{"pkey": "mfa.enable", "pval": "false", "type": "text", "sort": 1}]
        if path == "/email/setting/query":
            return [{"pkey": "email.host", "pval": "smtp.example.invalid", "type": "text", "sort": 1}]
        if path == "/lark/info":
            return {"appId": None, "appSecret": "", "callBack": None, "enable": False, "valid": False}
        if path == "/setting/authentication/info/oidc":
            return {"clientId": None, "clientSecret": "", "authEndpoint": None}
        raise AssertionError(f"unexpected request: {method} {path}")


class SettingsMutationTests(unittest.TestCase):
    def _runtime(self, root: Path):
        return (
            Settings(base_url="http://example", x_de_token="token", output_dir=root),
            FakeSettingsClient(),
            PlanStore(root),
            AuditLog(root),
        )

    def test_auth_setting_save_requires_no_rollback_ack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "mfa.json"
            spec_path.write_text('[{"pkey":"mfa.enable","pval":"true"}]', encoding="utf-8")
            args = argparse.Namespace(
                action="setting-save",
                scope="auth-mfa",
                spec=str(spec_path),
                ack_no_rollback=False,
                apply=False,
                plan_id="",
                confirm_token="",
            )
            settings, client, plans, audit = self._runtime(root)
            with self.assertRaises(DataEaseError) as raised:
                handle_settings_operation(args, settings, client, plans, audit)
            self.assertEqual(raised.exception.code, "rollback_ack_required")
            args.ack_no_rollback = True
            result = handle_settings_operation(args, settings, client, plans, audit)
            self.assertEqual(result["result"]["risk"], "L3")

    def test_email_setting_save_is_blocked_on_2_10_25(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "email.json"
            spec_path.write_text(
                '[{"pkey":"email.host","pval":"smtp.example.invalid","type":"text","sort":1}]',
                encoding="utf-8",
            )
            args = argparse.Namespace(
                action="setting-save",
                scope="email",
                spec=str(spec_path),
                ack_no_rollback=False,
                apply=False,
                plan_id="",
                confirm_token="",
            )
            settings, client, plans, audit = self._runtime(root)
            with self.assertRaises(DataEaseError) as raised:
                handle_settings_operation(args, settings, client, plans, audit)
            self.assertEqual(raised.exception.code, "unsafe_setting_endpoint")

    def test_setting_save_rejects_duplicate_pkeys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "mfa.json"
            spec_path.write_text(
                '[{"pkey":"mfa.enable","pval":"true"},{"pkey":"mfa.enable","pval":"false"}]',
                encoding="utf-8",
            )
            args = argparse.Namespace(
                action="setting-save",
                scope="auth-mfa",
                spec=str(spec_path),
                ack_no_rollback=True,
                apply=False,
                plan_id="",
                confirm_token="",
            )
            settings, client, plans, audit = self._runtime(root)
            with self.assertRaises(DataEaseError) as raised:
                handle_settings_operation(args, settings, client, plans, audit)
            self.assertEqual(raised.exception.code, "duplicate_setting_key")

    def test_setting_save_rejects_key_set_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "mfa.json"
            spec_path.write_text('[{"pkey":"mfa.unexpected","pval":"true"}]', encoding="utf-8")
            args = argparse.Namespace(
                action="setting-save",
                scope="auth-mfa",
                spec=str(spec_path),
                ack_no_rollback=True,
                apply=False,
                plan_id="",
                confirm_token="",
            )
            settings, client, plans, audit = self._runtime(root)
            with self.assertRaises(DataEaseError) as raised:
                handle_settings_operation(args, settings, client, plans, audit)
            self.assertEqual(raised.exception.code, "setting_key_set_changed")

    def test_integration_plan_does_not_store_app_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "lark.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "appId": "cli_test_app",
                        "appSecret": "very-secret-value",
                        "callBack": "https://callback.example.invalid",
                        "enable": False,
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                action="integration-save",
                provider="lark",
                spec=str(spec_path),
                ack_no_rollback=True,
                apply=False,
                plan_id="",
                confirm_token="",
            )
            settings, client, plans, audit = self._runtime(root)
            result = handle_settings_operation(args, settings, client, plans, audit)
            plan_text = (root / "plans" / f"{result['result']['plan_id']}.json").read_text(encoding="utf-8")
            self.assertNotIn("very-secret-value", plan_text)
            self.assertNotIn("callback.example.invalid", plan_text)
            self.assertEqual(result["result"]["risk"], "L3")

    def test_integration_enable_is_l3(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = argparse.Namespace(
                action="integration-enable",
                provider="lark",
                enable="true",
                apply=False,
                plan_id="",
                confirm_token="",
            )
            settings, client, plans, audit = self._runtime(root)
            result = handle_settings_operation(args, settings, client, plans, audit)
            self.assertEqual(result["result"]["risk"], "L3")
            self.assertTrue(result["result"]["confirmation_token"])

    def test_sso_plan_does_not_store_client_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "oidc.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "clientId": "codex-client",
                        "clientSecret": "oidc-super-secret",
                        "authEndpoint": "https://idp.example.invalid/authorize",
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                action="sso-save",
                provider="oidc",
                spec=str(spec_path),
                ack_no_rollback=True,
                apply=False,
                plan_id="",
                confirm_token="",
            )
            settings, client, plans, audit = self._runtime(root)
            result = handle_settings_operation(args, settings, client, plans, audit)
            plan_text = (root / "plans" / f"{result['result']['plan_id']}.json").read_text(encoding="utf-8")
            self.assertNotIn("oidc-super-secret", plan_text)
            self.assertNotIn("idp.example.invalid", plan_text)
            self.assertEqual(result["result"]["risk"], "L3")


if __name__ == "__main__":
    unittest.main()
