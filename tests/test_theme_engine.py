import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from dataease_skill.errors import DataEaseError
from dataease_skill.theme_engine import (
    accessible_text,
    extract_asset_palette,
    recommend_theme_names,
    render_theme_previews,
    resolve_theme,
)


class ThemeEngineTests(unittest.TestCase):
    def test_accessibility_replaces_low_contrast_text(self):
        color, ratio, adjusted = accessible_text("#050B1A", "#111827")
        self.assertEqual(color, "#FFFFFF")
        self.assertGreaterEqual(ratio, 4.5)
        self.assertTrue(adjusted)

    def test_custom_brand_theme_derives_palette(self):
        theme = resolve_theme({
            "base": "corporate-brand",
            "accent": "#6750A4",
            "background": "#FFFFFF",
            "text": "auto",
        })
        self.assertEqual(theme["accent"], "#6750A4")
        self.assertEqual(len(theme["colors"]), 5)
        self.assertGreaterEqual(theme["contrast_ratio"], 4.5)

    def test_svg_logo_palette_is_extracted(self):
        with tempfile.TemporaryDirectory() as directory:
            logo = Path(directory) / "logo.svg"
            logo.write_text('<svg><rect fill="#123456"/><rect fill="#ABCDEF"/></svg>', encoding="utf-8")
            self.assertEqual(extract_asset_palette(logo), ["#123456", "#ABCDEF"])

    def test_unknown_custom_keys_are_rejected(self):
        with self.assertRaises(DataEaseError):
            resolve_theme({"base": "business-light", "javascript": "bad"})

    def test_industry_recommendation_and_preview_files(self):
        candidates = recommend_theme_names("医院运营驾驶舱", "dashboard")
        self.assertIn("medical-health", candidates)
        with tempfile.TemporaryDirectory() as directory:
            previews = render_theme_previews(
                Path(directory), "医院运营驾驶舱", "dashboard", candidates,
                skill_root=Path(directory),
            )
            self.assertEqual(len(previews), 3)
            self.assertTrue(all(Path(item["preview"]).is_file() for item in previews))
            self.assertIn("<svg", Path(previews[0]["preview"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
