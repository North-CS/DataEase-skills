import base64
import json
import os
import tempfile
import unittest
import base64
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.dataease_skill.config import Settings
from scripts.dataease_skill.client import DataEaseClient, _payload_secrets, _sanitize_value
from scripts.dataease_skill.crypto import build_ask_headers, decrypt_dekey_public_key
from scripts.dataease_skill.errors import DataEaseError
from scripts.dataease_skill.redact import redact, redact_configuration
from scripts.dataease_skill.safety import PlanStore
from cryptography.hazmat.primitives import padding as symmetric_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class SettingsTests(unittest.TestCase):
    def test_empty_optional_runtime_values_use_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "DATAEASE_BASE_URL=http://example\n"
                "DATAEASE_ACCESS_KEY=1234567890123456\n"
                "DATAEASE_SECRET_KEY=12345678901234567890123456789012\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "DATAEASE_LOGIN_ORIGIN": "",
                    "DATAEASE_TIMEOUT": "",
                    "DATAEASE_VERIFY_SSL": "",
                    "DATAEASE_API_PREFIX": "",
                    "DATAEASE_REQUEST_MODE": "",
                },
                clear=False,
            ):
                settings = Settings.load(env_file)
            self.assertEqual(settings.login_origin, 0)
            self.assertEqual(settings.timeout, 30.0)
            self.assertEqual(settings.api_prefix, "/de2api")
            self.assertEqual(settings.request_mode, "auto")
            self.assertFalse(settings.allow_unverified_version)

    def test_env_precedence_and_public_redaction(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "DATAEASE_BASE_URL=http://from-file\n"
                "DATAEASE_ACCESS_KEY=1234567890123456\n"
                "DATAEASE_SECRET_KEY=12345678901234567890123456789012\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"DATAEASE_BASE_URL": "http://from-env"}, clear=False):
                settings = Settings.load(env_file)
            self.assertEqual(settings.base_url, "http://from-env")
            self.assertNotIn("secret_key", settings.public_dict())
            self.assertEqual(settings.public_dict()["auth_mode"], "ak_sk")

    def test_partial_ak_pair_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "DATAEASE_BASE_URL=http://example\nDATAEASE_ACCESS_KEY=1234567890123456\n",
                encoding="utf-8",
            )
            keys = [key for key in os.environ if key.startswith("DATAEASE_")]
            with patch.dict(os.environ, {key: "" for key in keys}, clear=False):
                with self.assertRaises(DataEaseError):
                    Settings.load(env_file)

    def test_invalid_proxy_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "DATAEASE_BASE_URL=http://example\n"
                "DATAEASE_ACCESS_KEY=1234567890123456\n"
                "DATAEASE_SECRET_KEY=12345678901234567890123456789012\n"
                "DATAEASE_PROXY_MODE=invalid\n",
                encoding="utf-8",
            )
            with self.assertRaises(DataEaseError):
                Settings.load(env_file)


class ProxyTests(unittest.TestCase):
    @staticmethod
    def _settings(base_url: str, proxy_mode: str = "auto", no_proxy: str = "") -> Settings:
        return Settings(
            base_url=base_url,
            access_key="1234567890123456",
            secret_key="12345678901234567890123456789012",
            proxy_mode=proxy_mode,
            no_proxy=no_proxy,
        )

    def test_auto_mode_bypasses_private_target(self):
        with DataEaseClient(self._settings("http://10.1.13.57:9080")) as client:
            self.assertFalse(client.session.trust_env)

    def test_auto_mode_keeps_proxy_for_public_target(self):
        with patch.dict(os.environ, {"NO_PROXY": ""}, clear=False):
            with DataEaseClient(self._settings("https://dataease.example.com")) as client:
                self.assertTrue(client.session.trust_env)

    def test_explicit_proxy_modes_override_auto_detection(self):
        with DataEaseClient(self._settings("http://10.1.13.57:9080", "environment")) as client:
            self.assertTrue(client.session.trust_env)
        with DataEaseClient(self._settings("https://dataease.example.com", "direct")) as client:
            self.assertFalse(client.session.trust_env)

    def test_dataease_no_proxy_applies_to_public_target(self):
        settings = self._settings("https://dataease.example.com", no_proxy="dataease.example.com")
        with DataEaseClient(settings) as client:
            self.assertFalse(client.session.trust_env)


class PasswordLoginTests(unittest.TestCase):
    @staticmethod
    def _client() -> DataEaseClient:
        return DataEaseClient(
            Settings(
                base_url="http://example",
                username="alice",
                password="secret",
            )
        )

    def test_login_accepts_token_vo_response(self):
        client = self._client()
        with patch.object(
            client,
            "request",
            side_effect=[
                {"data": "encrypted-public-key.aes-key"},
                {"data": {"token": "token-value", "exp": 123}},
            ],
        ), patch("scripts.dataease_skill.client.split_dekey", return_value=("encrypted", "key")), patch(
            "scripts.dataease_skill.client.decrypt_dekey_public_key", return_value="public-key"
        ), patch("scripts.dataease_skill.client.rsa_encrypt", return_value="encrypted-value"):
            self.assertEqual(client.login_with_password(), "token-value")
        client.close()

    def test_login_reports_mfa_challenge(self):
        client = self._client()
        with patch.object(
            client,
            "request",
            side_effect=[
                {"data": "encrypted-public-key.aes-key"},
                {"data": {"mfa": {"enabled": True}}},
            ],
        ), patch("scripts.dataease_skill.client.split_dekey", return_value=("encrypted", "key")), patch(
            "scripts.dataease_skill.client.decrypt_dekey_public_key", return_value="public-key"
        ), patch("scripts.dataease_skill.client.rsa_encrypt", return_value="encrypted-value"):
            with self.assertRaises(DataEaseError) as raised:
                client.login_with_password()
            self.assertEqual(raised.exception.code, "mfa_required")
        client.close()


class OrganizationContextTests(unittest.TestCase):
    @staticmethod
    def _client() -> DataEaseClient:
        return DataEaseClient(Settings(base_url="http://example", x_de_token="token"))

    def test_same_organization_does_not_switch(self):
        client = self._client()
        with patch.object(client, "data", return_value={"oid": "1"}), patch.object(
            client, "switch_organization"
        ) as switch:
            self.assertFalse(client.ensure_organization("1"))
            switch.assert_not_called()
        client.close()

    def test_different_organization_switches_once(self):
        client = self._client()
        with patch.object(client, "data", return_value={"oid": "1"}), patch.object(
            client, "switch_organization", return_value="new-token"
        ) as switch:
            self.assertTrue(client.ensure_organization("2"))
            switch.assert_called_once_with("2")
        client.close()


class MultipartClientTests(unittest.TestCase):
    def test_multipart_request_removes_json_content_type(self):
        client = DataEaseClient(Settings(base_url="http://example", x_de_token="token"))
        response = MagicMock(status_code=200)
        response.json.return_value = {"code": 0, "data": None}
        with patch.object(client.session, "request", return_value=response) as request:
            client.request("POST", "/plugin/install", files={"file": ("plugin.jar", b"bytes")})
        kwargs = request.call_args.kwargs
        self.assertNotIn("Content-Type", kwargs["headers"])
        self.assertIn("file", kwargs["files"])
        self.assertIsNone(kwargs["json"])
        client.close()

class CryptoTests(unittest.TestCase):
    def test_ask_headers(self):
        headers = build_ask_headers("1234567890123456", "12345678901234567890123456789012")
        self.assertEqual(headers["accessKey"], "1234567890123456")
        self.assertEqual(len(headers["x-de-ask-token"].split(".")), 3)
        self.assertTrue(headers["signature"])

    @staticmethod
    def _dekey_cipher(plain_text: str, key: str, iv: bytes) -> str:
        padder = symmetric_padding.PKCS7(algorithms.AES.block_size).padder()
        padded = padder.update(plain_text.encode("utf-8")) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key.encode("utf-8")), modes.CBC(iv)).encryptor()
        return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode("ascii")

    def test_dekey_uses_21026_derived_iv_and_legacy_fallback(self):
        key = "1234567890abcdef"
        plain_text = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A"
        modern = self._dekey_cipher(plain_text, key, hashlib.sha256(key.encode("utf-8")).digest()[:16])
        legacy = self._dekey_cipher(plain_text, key, b"0000000000000000")
        self.assertEqual(decrypt_dekey_public_key(modern, key), plain_text)
        self.assertEqual(decrypt_dekey_public_key(legacy, key), plain_text)


class RedactionTests(unittest.TestCase):
    def test_nested_redaction(self):
        value = {
            "username": "alice",
            "password": "secret",
            "nested": [{"clientSecret": "abc", "enabled": True}],
        }
        safe = redact(value)
        self.assertEqual(safe["username"], "alice")
        self.assertEqual(safe["password"], "***REDACTED***")
        self.assertEqual(safe["nested"][0]["clientSecret"], "***REDACTED***")

    def test_key_value_setting_records_are_redacted(self):
        value = [
            {"pkey": "auth.hmac.secret", "pval": "must-not-leak"},
            {"pkey": "basic.language", "pval": "zh-CN"},
        ]
        safe = redact_configuration(value)
        self.assertEqual(safe[0]["pval"], "***REDACTED***")
        self.assertEqual(safe[1]["pval"], "zh-CN")

    def test_request_payload_secrets_are_removed_from_error_details(self):
        encoded = base64.b64encode(json.dumps({"password": "request-only-secret"}).encode()).decode()
        payload = {
            "configuration": encoded,
            "url": "https://hooks.example.invalid/path?token=request-token",
        }
        secrets = _payload_secrets(payload)
        safe = _sanitize_value(
            {"msg": "failed request-only-secret at https://hooks.example.invalid/path?token=request-token"},
            secrets,
        )
        self.assertNotIn("request-only-secret", safe["msg"])
        self.assertNotIn("request-token", safe["msg"])


class PlanStoreTests(unittest.TestCase):
    def test_l3_requires_confirmation_token(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PlanStore(Path(directory))
            visible = store.create(
                "admin.delete",
                target={"id": "1"},
                changes=[{"action": "delete"}],
                risk="L3",
                spec={"id": "1"},
                rollback={"available": False},
            )
            with self.assertRaises(DataEaseError):
                store.load(visible["plan_id"])
            plan = store.load(visible["plan_id"], visible["confirmation_token"])
            self.assertEqual(plan["spec"]["id"], "1")

    def test_plan_file_does_not_expose_secret_like_target_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PlanStore(Path(directory))
            visible = store.create(
                "integration.update",
                target={"clientSecret": "abc"},
                changes=[],
                risk="L2",
                spec={"enabled": True},
            )
            self.assertEqual(visible["target"]["clientSecret"], "***REDACTED***")

    def test_plan_rejects_changed_instance_context(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PlanStore(Path(directory))
            visible = store.create(
                "visual.create",
                target={"name": "A"},
                changes=[{"action": "create"}],
                risk="L1",
                spec={"name": "A"},
                context={"base_url": "http://one", "org_id": "1", "version": "2.10.25"},
            )
            with self.assertRaises(DataEaseError) as raised:
                store.load(
                    visible["plan_id"],
                    expected_context={"base_url": "http://two", "org_id": "1", "version": "2.10.25"},
                )
            self.assertEqual(raised.exception.code, "plan_context_changed")

    def test_applied_plan_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PlanStore(Path(directory))
            visible = store.create(
                "filling.create",
                target={"name": "test"},
                changes=[{"action": "create"}],
                risk="L1",
                spec={"name": "test"},
            )
            store.mark_applied(visible["plan_id"], "audit-test")
            with self.assertRaises(DataEaseError) as raised:
                store.load(visible["plan_id"])
            self.assertEqual(raised.exception.code, "plan_already_applied")


if __name__ == "__main__":
    unittest.main()
