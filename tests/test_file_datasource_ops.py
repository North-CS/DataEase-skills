from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.dataease_skill.audit import AuditLog
from scripts.dataease_skill.config import Settings
from scripts.dataease_skill.cli import run
from scripts.dataease_skill.file_datasource_ops import create_file_datasource, generate_file, inspect_file
from scripts.dataease_skill.safety import PlanStore


class FakeFileClient:
    def __init__(self, version="2.10.25") -> None:
        self.settings = Settings(base_url="http://example", x_de_token="token", org_id="1")
        self.version = version
        self.requests = []

    def request(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs))
        if path == "/datasource/uploadFile":
            return {"code": 0, "data": {"excelLabel": "sales.csv", "sheets": [{"sheetId": "CSV", "tableName": "sales", "fields": [{"name": "amount", "checked": True}], "data": [{"amount": 1}], "jsonArray": [{"amount": 1}]}]}}
        raise AssertionError(f"unexpected request {method} {path}")

    def data(self, method, path, payload=None):
        self.requests.append((method, path, payload))
        if path == "/license/version":
            return self.version
        if path == "/datasource/save":
            self.saved = payload
            return {"id": "301"}
        if path == "/datasource/hidePw/301":
            return {"id": "301", "name": "销售模拟数据", "pid": "0", "type": "Excel", "nodeType": "datasource", "status": "Success"}
        raise AssertionError(f"unexpected request {method} {path}")


class FileDatasourceTests(unittest.TestCase):
    def test_generate_cli_needs_no_dataease_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = root / "data.json"
            output = root / "sales.csv"
            spec.write_text(json.dumps({"columns": ["date"], "rows": [["2026-08-01"]]}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                status = run(["file-datasource", "generate", "--spec", str(spec), "--output", str(output)])
            self.assertEqual(status, 0)
            self.assertTrue(output.is_file())

    def test_generate_csv_and_inspect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = root / "data.json"
            output = root / "sales.csv"
            spec.write_text(json.dumps({"columns": ["日期", "销售额"], "rows": [["2026-08-01", 12], {"日期": "2026-08-02", "销售额": 15}]}), encoding="utf-8")
            result = generate_file(argparse.Namespace(spec=str(spec), output=str(output)))
            self.assertTrue(output.is_file())
            self.assertEqual(result["result"]["rows"], 2)
            self.assertEqual(inspect_file(output)["columns"], 2)

    def test_create_plan_binds_file_digest_and_apply_uses_multipart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sales.csv"
            source.write_text("date,amount\n2026-08-01,12\n", encoding="utf-8")
            args = argparse.Namespace(file=str(source), name="销售模拟数据", pid="0", sheet=[], apply=False, plan_id="", confirm_token="")
            client = FakeFileClient()
            settings = Settings(base_url="http://example", x_de_token="token", output_dir=root)
            plans, audit = PlanStore(root), AuditLog(root)
            planned = create_file_datasource(args, settings, client, plans, audit)
            plan_id = planned["result"]["plan_id"]
            args.apply, args.plan_id = True, plan_id
            result = create_file_datasource(args, settings, client, plans, audit)
            self.assertEqual(result["result"]["id"], "301")
            self.assertEqual(client.saved["type"], "Excel")
            self.assertEqual(client.saved["sheets"][0]["data"], [])
            self.assertEqual(client.saved["sheets"][0]["jsonArray"], [])
            upload = next(request for request in client.requests if request[1] == "/datasource/uploadFile")
            self.assertEqual(upload[2]["form"], {"id": "0", "editType": "0"})

    def test_create_apply_blocks_unverified_server_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sales.csv"
            source.write_text("date,amount\n2026-08-01,12\n", encoding="utf-8")
            args = argparse.Namespace(file=str(source), name="销售模拟数据", pid="0", sheet=[], apply=False, plan_id="", confirm_token="")
            client = FakeFileClient(version="2.10.26")
            settings = Settings(base_url="http://example", x_de_token="token", output_dir=root)
            planned = create_file_datasource(args, settings, client, PlanStore(root), AuditLog(root))
            args.apply, args.plan_id = True, planned["result"]["plan_id"]
            with self.assertRaisesRegex(Exception, "验证版本"):
                create_file_datasource(args, settings, client, PlanStore(root), AuditLog(root))
