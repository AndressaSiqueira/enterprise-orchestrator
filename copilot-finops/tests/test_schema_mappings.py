import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_MAPPING_PAIRS = (
    (
        ROOT / "schemas" / "github-copilot.schema.json",
        ROOT / "config" / "schemas" / "githubcopilot_1.0.json",
    ),
    (
        ROOT / "schemas" / "github-copilot-focus.schema.json",
        ROOT / "config" / "schemas" / "githubcopilotfocus_1.0.json",
    ),
)


class SchemaMappingTests(unittest.TestCase):
    def test_schema_and_adf_mapping_columns_match(self) -> None:
        for schema_path, mapping_path in SCHEMA_MAPPING_PAIRS:
            with self.subTest(schema=schema_path.name):
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                mapping = json.loads(mapping_path.read_text(encoding="utf-8"))

                schema_names = [column["name"] for column in schema["columns"]]
                source_names = [
                    item["source"]["name"]
                    for item in mapping["translator"]["mappings"]
                ]
                sink_names = [
                    item["sink"]["name"]
                    for item in mapping["translator"]["mappings"]
                ]

                self.assertEqual(len(schema_names), len(set(schema_names)))
                self.assertEqual(source_names, schema_names)
                self.assertEqual(sink_names, schema_names)


if __name__ == "__main__":
    unittest.main()