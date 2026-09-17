#!/usr/bin/env python3
"""
Normalize real GitHub Copilot `ai_credit/usage` billing data into a
FOCUS-conformant table (GitHubCopilotFocus_final_v1_0) alongside the hub's
real Costs_final_v1_2 schema, plus the proposed x_AI* token/agent extension
family.

Only `billing-ai-credit-*.json` `usageItems[]` are mapped to FOCUS charge
columns (BilledCost/ListCost/etc.) -- this is the one real source with a
genuine charge period, quantity, and price. Per docs/github-focus-mapping.md,
budget `consumed_amount` (progress against a spending limit, no currency, no
reconciliation guarantee) must NOT be mapped to BilledCost/ListCost/
ContractedCost/EffectiveCost, so budgets are intentionally NOT read here --
they already live, correctly labeled as governance/allocation extensions, in
the separate GitHubCopilot dataset (x_RecordType="Budget").

Adapted from JerryMSFT/hackathon-jerry's normalize_to_focus.py, reading our
real REST JSON instead of a synthetic AI-usage-report CSV. Everything the REST
`ai_credit/usage` endpoint doesn't expose today (token counts, model name,
repository, cost center) is left null -- never inferred or fabricated.

Does not touch the existing GitHubCopilot dataset/pipeline/schema.
"""

from __future__ import annotations

import argparse
import glob
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from dataset_manifest import build_dataset_manifest, write_dataset_manifest

SCHEMA_PATH = Path("schemas/github-copilot-focus.schema.json")

PROVIDER = "GitHub"
SERVICE_NAME = "GitHub Copilot"
SERVICE_CATEGORY = "AI and Machine Learning"
SERVICE_SUBCATEGORY = "Developer Productivity"

SOURCE_NAME = "GitHub Copilot ai_credit billing export"
SOURCE_PROVIDER = "GitHub"
SOURCE_TYPE = "GitHub Enterprise REST API"
SOURCE_VERSION = "2026-03-10"


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def find_latest_run(data_root: Path) -> Path:
    required = ("manifest.json",)
    candidates = [
        path
        for path in data_root.iterdir()
        if path.is_dir()
        and all((path / item).is_file() for item in required)
        and glob.glob(str(path / "raw" / "billing-ai-credit-*.json"))
    ]
    if not candidates:
        raise FileNotFoundError(f"No complete collection runs found under {data_root}")
    return max(candidates, key=lambda path: path.name)


def empty_row(column_names: list[str]) -> dict[str, Any]:
    return {name: "" for name in column_names}


def normalize_ai_credit(
    run_directory: Path, organization: str, collected_at: str, column_names: list[str]
) -> list[dict[str, Any]]:
    """One row per real ai_credit/usage line item. Empty today for this org
    (no usageItems returned yet) -- the structure is ready for when real
    credit-usage data lands, without fabricating anything now.
    """
    rows: list[dict[str, Any]] = []
    for path_str in sorted(glob.glob(str(run_directory / "raw" / "billing-ai-credit-*.json"))):
        source = load_json(Path(path_str))
        year = source.get("timePeriod", {}).get("year")
        month = source.get("timePeriod", {}).get("month")
        bp_start = f"{year:04d}-{month:02d}-01" if year and month else ""
        bp_end = (
            date(year, month, 1).replace(year=year + 1, month=1) if month == 12
            else date(year, month, 1).replace(month=month + 1)
        ).isoformat() if year and month else ""

        for item in source.get("usageItems", []):
            row = empty_row(column_names)
            row.update({
                "BilledCost": item.get("netAmount"),
                "ListCost": item.get("grossAmount"),
                "ContractedCost": item.get("netAmount"),
                "EffectiveCost": item.get("netAmount"),
                "BillingAccountId": organization,
                "BillingAccountName": organization,
                "BillingAccountType": "Enterprise",
                "BillingCurrency": "USD",
                "BillingPeriodStart": bp_start,
                "BillingPeriodEnd": bp_end,
                "ChargePeriodStart": bp_start,
                "ChargePeriodEnd": bp_end,
                "ChargeCategory": "Usage",
                "ChargeFrequency": "Usage-Based",
                "ChargeDescription": f"{SERVICE_NAME} {item.get('sku')} ({item.get('model')})",
                "ConsumedQuantity": item.get("grossQuantity"),
                "ConsumedUnit": item.get("unitType"),
                "PricingQuantity": item.get("grossQuantity"),
                "PricingUnit": item.get("unitType"),
                "ListUnitPrice": item.get("pricePerUnit"),
                "ContractedUnitPrice": item.get("pricePerUnit"),
                "ProviderName": PROVIDER,
                "PublisherName": PROVIDER,
                "InvoiceIssuerName": PROVIDER,
                "ServiceName": SERVICE_NAME,
                "ServiceCategory": SERVICE_CATEGORY,
                "ServiceSubcategory": SERVICE_SUBCATEGORY,
                "SkuId": item.get("sku"),
                "SkuMeter": item.get("model"),
                "SubAccountId": organization,
                "SubAccountName": organization,
                "SubAccountType": "Organization",
                "x_BilledCostInUsd": item.get("netAmount"),
                "x_ListCostInUsd": item.get("grossAmount"),
                "x_BilledUnitPrice": item.get("pricePerUnit"),
                "x_EffectiveUnitPrice": item.get("pricePerUnit"),
                "x_CostType": "Usage",
                "x_UsageType": "Interactive",
                "x_SkuMeterCategory": "AI Credits",
                "x_IngestionTime": collected_at,
                "x_ExportTime": collected_at,
                "x_SourceName": SOURCE_NAME,
                "x_SourceProvider": SOURCE_PROVIDER,
                "x_SourceType": SOURCE_TYPE,
                "x_SourceVersion": SOURCE_VERSION,
                "x_SourceValues": json.dumps(item),
                "x_AICreditQuantity": item.get("netQuantity"),
                "x_AICreditGrossAmount": item.get("grossAmount"),
                "x_AIDiscountAmount": item.get("discountAmount"),
                "x_AIDiscountQuantity": item.get("discountQuantity"),
                "x_AIModelName": item.get("model"),
                # Not exposed by this source -- left empty, never inferred.
                "x_AIModelProvider": "", "x_AIAgentSurface": "",
                "x_AITokensInput": "", "x_AITokensOutput": "",
                "x_AITokensCacheRead": "", "x_AITokensCacheWrite": "", "x_AITokensTotal": "",
                "x_AIPrincipalRef": "", "x_AIAttributionGrain": "organization",
            })
            rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], column_names: list[str]) -> None:
    import csv
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=column_names)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in column_names})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare a FOCUS-conformant GitHub Copilot cost feed for FinOps hub ingestion."
    )
    parser.add_argument("--run-directory", type=Path)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output-root", type=Path, default=Path("staging"))
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    args = parser.parse_args()

    run_directory = args.run_directory or find_latest_run(args.data_root)
    manifest = load_json(run_directory / "manifest.json")
    schema_definition = load_json(args.schema)
    columns = schema_definition["columns"]
    column_names = [c["name"] for c in columns]

    organization = manifest["organization"]
    collected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    rows = normalize_ai_credit(run_directory, organization, collected_at, column_names)

    ingestion_id = run_directory.name
    destination = (
        args.output_root
        / schema_definition["dataset"]
        / f"{date.today().year:04d}"
        / f"{date.today().month:02d}"
        / "github"
        / organization
    )
    destination.mkdir(parents=True, exist_ok=True)

    csv_path = destination / f"{ingestion_id}__github-copilot-focus.csv"
    write_csv(csv_path, rows, column_names)

    dataset_manifest = build_dataset_manifest(
        schema_definition,
        data_file_name=csv_path.name,
        data_blob_name=csv_path.relative_to(args.output_root).as_posix(),
        row_count=len(rows),
        organization=organization,
        collected_at_utc=collected_at,
        source_files=["raw/billing-ai-credit-*.json"],
    )
    write_dataset_manifest(destination / "manifest.json", dataset_manifest)

    print(f"Run directory: {run_directory}")
    print(f"Rows: {len(rows)} x {len(column_names)} cols")
    print(f"CSV: {csv_path}")
    print("No token/model detail available from real REST sources today -- x_AITokens* left empty, not inferred.")


if __name__ == "__main__":
    main()
