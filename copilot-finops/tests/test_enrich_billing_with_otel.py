import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from enrich_billing_with_otel import NEW_OTEL_COLUMNS, build_or_update_manifest


class EnrichedManifestTests(unittest.TestCase):
    def test_updates_file_blob_counts_and_schema_hash(self) -> None:
        manifest = {
            "dataRowCount": 1,
            "files": [{"name": "old.csv", "format": "csv", "rowCount": 1}],
            "blobs": [
                {
                    "blobName": (
                        "GitHubCopilot/2026/09/github/example/old.csv"
                    )
                }
            ],
            "schema": {
                "sha256": "0" * 64,
                "columns": [
                    {"name": "Day", "type": "datetime", "nullable": False}
                ],
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            result = build_or_update_manifest(
                path,
                pd.DataFrame({"Day": ["2026-09-17"]}),
                "new.csv",
                7,
            )

        canonical_schema = json.dumps(
            result["schema"]["columns"], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        expected_hash = hashlib.sha256(canonical_schema).hexdigest()
        names = [column["name"] for column in result["schema"]["columns"]]

        self.assertEqual(result["files"][0]["name"], "new.csv")
        self.assertEqual(result["files"][0]["rowCount"], 7)
        self.assertEqual(
            result["blobs"][0]["blobName"],
            "GitHubCopilot/2026/09/github/example/new.csv",
        )
        self.assertEqual(result["dataRowCount"], 7)
        self.assertTrue(
            all(names.count(column["name"]) == 1 for column in NEW_OTEL_COLUMNS)
        )
        self.assertEqual(result["schema"]["sha256"], expected_hash)


if __name__ == "__main__":
    unittest.main()