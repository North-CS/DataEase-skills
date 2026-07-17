import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.dataease_skill.runtime import runtime_diagnostics


class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_missing_node_reports_api_only_fallback(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.dataease_skill.runtime.shutil.which",
            return_value=None,
        ):
            result = runtime_diagnostics(Path(directory))
        self.assertEqual(result["capture"]["engine"], "node-playwright")
        self.assertFalse(result["capture"]["ready"])
        self.assertTrue(any("Node.js" in item for item in result["recommendations"]))

    def test_node_playwright_manifest_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "node_modules" / "playwright" / "package.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text('{"version":"1.59.1"}', encoding="utf-8")
            with patch(
                "scripts.dataease_skill.runtime.shutil.which",
                side_effect=lambda name: "node" if name == "node" else "npm" if name == "npm" else None,
            ), patch(
                "scripts.dataease_skill.runtime._run",
                side_effect=[(0, "v22.0.0"), (0, str(root / "missing-chromium"))],
            ):
                result = runtime_diagnostics(root)
        self.assertEqual(result["capture"]["playwright_version"], "1.59.1")
        self.assertFalse(result["capture"]["chromium_exists"])
        self.assertTrue(any("playwright install chromium" in item for item in result["recommendations"]))


if __name__ == "__main__":
    unittest.main()
