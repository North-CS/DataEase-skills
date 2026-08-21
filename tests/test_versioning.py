import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.dataease_skill.errors import DataEaseError
from scripts.dataease_skill.versioning import parse_version, select_adapter


class VisualDetailClient:
    def __init__(self):
        self.call = None

    def data(self, method, path, payload=None):
        self.call = (method, path, payload)
        return {"id": "10", "canvasViewInfo": {}}


class VersionAdapterTests(unittest.TestCase):
    def test_selects_documented_endpoint_families(self):
        self.assertEqual(select_adapter("2.7.1")[1].visual_detail_mode, "legacy-get")
        self.assertEqual(select_adapter("v2.8.1")[1].visual_detail_mode, "request-post")
        self.assertFalse(select_adapter("2.10.9")[1].linkage_resource_table)
        self.assertTrue(select_adapter("2.10.10")[1].linkage_resource_table)

    def test_feature_availability_tracks_source_tags(self):
        self.assertNotIn("plugin_management", select_adapter("2.7.1")[1].features)
        self.assertIn("plugin_management", select_adapter("2.8.0")[1].features)
        self.assertNotIn("dataset_export", select_adapter("2.9.0")[1].features)
        self.assertIn("dataset_export", select_adapter("2.10.0")[1].features)

    def test_request_adapter_reads_the_editing_snapshot(self):
        version, adapter = select_adapter("2.10.25")
        client = VisualDetailClient()
        adapter.visual_detail(client, "10", "dataV", version)
        self.assertEqual(client.call[0:2], ("POST", "/dataVisualization/findById"))
        self.assertEqual(client.call[2]["resourceTable"], "snapshot")
        self.assertEqual(client.call[2]["source"], "main-edit")

    def test_future_version_is_readable_but_mutation_requires_override(self):
        version, adapter = select_adapter("2.11.0")
        adapter.require("visual_component_edit", version)
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(DataEaseError) as raised:
            adapter.require("visual_component_edit", version, mutation=True)
        self.assertEqual(raised.exception.code, "unverified_version_mutation")
        client = SimpleNamespace(settings=SimpleNamespace(allow_unverified_version=True))
        with patch.dict("os.environ", {}, clear=True):
            adapter.require("visual_component_edit", version, mutation=True, client=client)

    def test_21026_allows_only_live_verified_file_workflow(self):
        version, adapter = select_adapter("2.10.26")
        self.assertEqual(adapter.name, "v2.10.26")
        self.assertFalse(adapter.is_verified(version))
        self.assertTrue(adapter.is_verified(version, "file_datasource"))
        with patch.dict("os.environ", {}, clear=True):
            adapter.require("file_datasource", version, mutation=True)
            with self.assertRaises(DataEaseError) as raised:
                adapter.require("plugin_management", version, mutation=True)
        self.assertEqual(raised.exception.code, "unverified_version_mutation")

    def test_rejects_unsupported_or_unparseable_version(self):
        self.assertEqual(parse_version({"version": "2.10.25"}), (2, 10, 25))
        with self.assertRaises(DataEaseError):
            select_adapter("2.6.1")
        with self.assertRaises(DataEaseError):
            parse_version("unknown")


if __name__ == "__main__":
    unittest.main()
