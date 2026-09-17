from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


REQUIRED_DEFINITION_KEYS = ("dataset", "version", "loadMode", "kusto", "columns")
REQUIRED_KUSTO_KEYS = ("database", "rawTable", "parquetMapping")
REQUIRED_COLUMN_KEYS = ("name", "type", "nullable")


def validate_schema_definition(definition: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_DEFINITION_KEYS if key not in definition]
    if missing:
        raise ValueError(f"Schema definition is missing: {', '.join(missing)}")

    missing_kusto = [
        key for key in REQUIRED_KUSTO_KEYS if key not in definition["kusto"]
    ]
    if missing_kusto:
        raise ValueError(f"Kusto definition is missing: {', '.join(missing_kusto)}")

    names: list[str] = []
    for index, column in enumerate(definition["columns"]):
        missing_column = [key for key in REQUIRED_COLUMN_KEYS if key not in column]
        if missing_column:
            raise ValueError(
                f"Column {index} is missing: {', '.join(missing_column)}"
            )
        names.append(column["name"])

    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"Schema contains duplicate columns: {', '.join(duplicates)}")


def build_dataset_manifest(
    definition: dict[str, Any],
    *,
    data_file_name: str,
    data_blob_name: str | None = None,
    row_count: int,
    organization: str,
    collected_at_utc: str,
    source_files: Iterable[str],
) -> dict[str, Any]:
    validate_schema_definition(definition)
    if not data_file_name.endswith(".csv"):
        raise ValueError("Manifest data file must use the .csv extension")
    if row_count < 0:
        raise ValueError("Manifest row count cannot be negative")

    blob_name = data_blob_name or data_file_name
    if not blob_name.endswith(f"/{data_file_name}"):
        raise ValueError("Manifest blob path must end with the data file name")

    ingestion_id = data_file_name.split("__", maxsplit=1)[0]
    export_resource_id = (
        f"/github/{organization}/providers/Microsoft.CostManagement/exports/"
        f"{definition['dataset']}"
    )

    canonical_schema = json.dumps(
        definition["columns"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "manifestVersion": "1.0",
        "dataset": definition["dataset"],
        "schemaVersion": definition["version"],
        "loadMode": definition["loadMode"],
        "organization": organization,
        "collectedAtUtc": collected_at_utc,
        "sourceFiles": list(source_files),
        "exportConfig": {
            "type": definition["dataset"],
            "dataVersion": definition["version"],
            "resourceId": export_resource_id,
            "exportName": definition["dataset"],
        },
        "runInfo": {
            "runId": ingestion_id,
            "startDate": collected_at_utc,
        },
        "blobCount": 1,
        "dataRowCount": row_count,
        "blobs": [{"blobName": blob_name}],
        "target": definition["kusto"],
        "files": [
            {
                "name": data_file_name,
                "format": "csv",
                "rowCount": row_count,
            }
        ],
        "schema": {
            "sha256": hashlib.sha256(canonical_schema).hexdigest(),
            "columns": definition["columns"],
        },
    }


def write_dataset_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )