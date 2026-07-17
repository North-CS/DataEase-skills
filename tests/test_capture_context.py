import argparse
import os
import unittest
from unittest.mock import patch

from scripts import capture_dashboard


class CaptureOrganizationContextTests(unittest.TestCase):
    def test_capture_runtime_defaults_to_shared_environment_context(self):
        with patch.dict(
            os.environ,
            {"DATAEASE_ORG_ID": "200", "DATAEASE_X_DE_TOKEN": "private-token"},
            clear=False,
        ):
            args = capture_dashboard.build_parser().parse_args(
                ["list-resources", "--base-url", "http://example"]
            )
        self.assertEqual(args.org_id, "200")
        self.assertEqual(args.x_de_token, "private-token")

    def test_switch_org_does_not_print_token_by_default(self):
        args = argparse.Namespace(
            base_url="http://example",
            org_id="200",
            request_mode="gateway",
            show_token=False,
        )
        with patch.object(capture_dashboard, "build_headers", return_value={}), patch.object(
            capture_dashboard,
            "switch_organization",
            return_value={"data": {"token": "private-token", "exp": 123}},
        ), patch.object(capture_dashboard, "print_json") as print_json:
            capture_dashboard.command_switch_org(args, {"auth_mode": "ask_token"})
        payload = print_json.call_args.args[0]
        self.assertTrue(payload["token_available"])
        self.assertNotIn("x_de_token", payload)

    def test_switch_org_only_prints_token_with_explicit_flag(self):
        args = argparse.Namespace(
            base_url="http://example",
            org_id="200",
            request_mode="gateway",
            show_token=True,
        )
        with patch.object(capture_dashboard, "build_headers", return_value={}), patch.object(
            capture_dashboard,
            "switch_organization",
            return_value={"data": {"token": "private-token", "exp": 123}},
        ), patch.object(capture_dashboard, "print_json") as print_json:
            capture_dashboard.command_switch_org(args, {"auth_mode": "ask_token"})
        payload = print_json.call_args.args[0]
        self.assertEqual(payload["x_de_token"], "private-token")
        self.assertTrue(payload["warnings"])


if __name__ == "__main__":
    unittest.main()
