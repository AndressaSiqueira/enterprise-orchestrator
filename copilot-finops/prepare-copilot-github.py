from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from dataset_manifest import build_dataset_manifest, write_dataset_manifest


BUDGETS_SOURCE = "raw/budgets.pages.json"
SEATS_SOURCE = "raw/copilot-seats.pages.json"
USAGE_SOURCE = "raw/metrics/users-28-day/latest.part-1.ndjson"
USAGE_METADATA = "raw/metrics/users-28-day/latest.metadata.json"
SCHEMA_VERSION = "1.0"

COMMON_DEFAULTS: dict[str, Any] = {
    "x_RowKind": None,
    "UserLogin": None,
    "UserId": None,
    "BudgetId": None,
    "BudgetType": None,
    "BudgetProductSku": None,
    "BudgetScope": None,
    "BudgetAmount": None,
    "PreventFurtherUsage": None,
    "BudgetEntityName": None,
    "WillAlert": None,
    "AlertRecipientsJson": None,
    "ConsumedAmount": None,
    "TotalSeats": None,
    "AssigneeType": None,
    "AssigningTeam": None,
    "PendingCancellationDate": None,
    "LastActivityAt": None,
    "LastActivityEditor": None,
    "LastAuthenticatedAt": None,
    "CreatedAt": None,
    "PlanType": None,
    "ReportStartDay": None,
    "ReportEndDay": None,
    "Day": None,
    "OrganizationId": None,
    "EnterpriseId": None,
    "Interactions": None,
    "CodeGenerations": None,
    "CodeAcceptances": None,
    "LocSuggestedToAdd": None,
    "LocSuggestedToDelete": None,
    "LocAdded": None,
    "LocDeleted": None,
    "UsedAgent": None,
    "UsedChat": None,
    "UsedCli": None,
    "UsedCopilotCloudAgent": None,
    "UsedCopilotCodingAgent": None,
    "AiAdoptionPhase": None,
    "AiCreditProduct": None,
    "AiCreditSku": None,
    "AiCreditModel": None,
    "AiCreditUnitType": None,
    "AiCreditPricePerUnit": None,
    "AiCreditGrossQuantity": None,
    "AiCreditGrossAmount": None,
    "AiCreditDiscountQuantity": None,
    "AiCreditDiscountAmount": None,
    "AiCreditNetQuantity": None,
    "AiCreditNetAmount": None,
    "models_used": None,
    "otel_request_count": None,
    "otel_input_tokens": None,
    "otel_output_tokens": None,
    "otel_total_tokens": None,
    "otel_avg_latency_ms": None,
    "otel_session_count": None,
    "otel_agents_used": None,
    "otel_tool_call_count": None,
    "otel_correlation_level": None,
}


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def find_latest_run(data_root: Path) -> Path:
    required = (
        "manifest.json",
        BUDGETS_SOURCE,
        SEATS_SOURCE,
        USAGE_SOURCE,
        USAGE_METADATA,
    )
    candidates = [
        path
        for path in data_root.iterdir()
        if path.is_dir() and all((path / item).is_file() for item in required)
    ]
    if not candidates:
        raise FileNotFoundError(f"No complete collection runs found under {data_root}")
    return max(candidates, key=lambda path: path.name)


def base_row(record_type: str, organization: str, collected_at_utc: str, source_file: str) -> dict[str, Any]:
    row = dict(COMMON_DEFAULTS)
    row.update(
        {
            "x_RecordType": record_type,
            "Organization": organization,
            "CollectedAtUtc": collected_at_utc,
            "SourceFile": source_file,
            "SchemaVersion": SCHEMA_VERSION,
        }
    )
    return row


def normalize_budgets(run_directory: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    source = load_json(run_directory / BUDGETS_SOURCE)
    organization = manifest["organization"]
    collected_at = manifest["collected_at_utc"]

    rows = []
    for budget in source.get("budgets", []):
        alerting = budget.get("budget_alerting") or {}
        row = base_row("Budget", organization, collected_at, BUDGETS_SOURCE)
        row.update(
            {
                "BudgetId": budget["id"],
                "BudgetType": budget["budget_type"],
                "BudgetProductSku": budget["budget_product_sku"],
                "BudgetScope": budget["budget_scope"],
                "BudgetAmount": Decimal(str(budget["budget_amount"])),
                "PreventFurtherUsage": budget["prevent_further_usage"],
                "BudgetEntityName": budget["budget_entity_name"],
                "WillAlert": alerting.get("will_alert", False),
                "AlertRecipientsJson": json.dumps(
                    alerting.get("alert_recipients", []), separators=(",", ":")
                ),
                "ConsumedAmount": (
                    Decimal(str(budget["consumed_amount"]))
                    if budget.get("consumed_amount") is not None
                    else None
                ),
                "UserLogin": budget.get("user"),
            }
        )
        rows.append(row)

    if source.get("total_count") != len(rows):
        raise ValueError(
            f"Budget count mismatch: expected {source.get('total_count')}, got {len(rows)}"
        )
    return rows


def seat_pages(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        yield payload
    elif isinstance(payload, list):
        yield from (page for page in payload if isinstance(page, dict))
    else:
        raise ValueError("Unexpected Copilot seats response shape")


def normalize_seats(run_directory: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    organization = manifest["organization"]
    collected_at = manifest["collected_at_utc"]
    pages = list(seat_pages(load_json(run_directory / SEATS_SOURCE)))
    total_seats = max((int(page.get("total_seats", 0)) for page in pages), default=0)
    seats = [seat for page in pages for seat in page.get("seats", [])]

    rows = []
    snapshot = base_row("Seat", organization, collected_at, SEATS_SOURCE)
    snapshot.update({"x_RowKind": "Snapshot", "TotalSeats": total_seats})
    rows.append(snapshot)

    for seat in seats:
        assignee = seat.get("assignee") or {}
        assigning_team = seat.get("assigning_team") or {}
        row = base_row("Seat", organization, collected_at, SEATS_SOURCE)
        row.update(
            {
                "x_RowKind": "Seat",
                "TotalSeats": total_seats,
                "UserLogin": assignee.get("login"),
                "UserId": assignee.get("id"),
                "AssigneeType": assignee.get("type"),
                "AssigningTeam": assigning_team.get("slug") or assigning_team.get("name"),
                "PendingCancellationDate": seat.get("pending_cancellation_date"),
                "LastActivityAt": seat.get("last_activity_at"),
                "LastActivityEditor": seat.get("last_activity_editor"),
                "LastAuthenticatedAt": seat.get("last_authenticated_at"),
                "CreatedAt": seat.get("created_at"),
                "PlanType": seat.get("plan_type"),
            }
        )
        rows.append(row)
    return rows


def normalize_usage(run_directory: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    organization = manifest["organization"]
    collected_at = manifest["collected_at_utc"]
    metadata = load_json(run_directory / USAGE_METADATA)
    usage_rows = load_ndjson(run_directory / USAGE_SOURCE)

    rows = []
    snapshot = base_row("UsageDaily", organization, collected_at, USAGE_SOURCE)
    snapshot.update(
        {
            "x_RowKind": "Snapshot",
            "ReportStartDay": metadata["report_start_day"],
            "ReportEndDay": metadata["report_end_day"],
            "Interactions": 0,
            "CodeGenerations": 0,
            "CodeAcceptances": 0,
            "LocSuggestedToAdd": 0,
            "LocSuggestedToDelete": 0,
            "LocAdded": 0,
            "LocDeleted": 0,
            "UsedAgent": False,
            "UsedChat": False,
            "UsedCli": False,
            "UsedCopilotCloudAgent": False,
            "UsedCopilotCodingAgent": False,
        }
    )
    rows.append(snapshot)

    for item in usage_rows:
        row = base_row("UsageDaily", organization, collected_at, USAGE_SOURCE)
        row.update(
            {
                "x_RowKind": "Usage",
                "ReportStartDay": metadata["report_start_day"],
                "ReportEndDay": metadata["report_end_day"],
                "Day": item["day"],
                "OrganizationId": item.get("organization_id"),
                "EnterpriseId": str(item.get("enterprise_id") or "") or None,
                "UserId": item.get("user_id"),
                "UserLogin": item.get("user_login"),
                "Interactions": item.get("user_initiated_interaction_count", 0),
                "CodeGenerations": item.get("code_generation_activity_count", 0),
                "CodeAcceptances": item.get("code_acceptance_activity_count", 0),
                "LocSuggestedToAdd": item.get("loc_suggested_to_add_sum", 0),
                "LocSuggestedToDelete": item.get("loc_suggested_to_delete_sum", 0),
                "LocAdded": item.get("loc_added_sum", 0),
                "LocDeleted": item.get("loc_deleted_sum", 0),
                "UsedAgent": item.get("used_agent", False),
                "UsedChat": item.get("used_chat", False),
                "UsedCli": item.get("used_cli", False),
                "UsedCopilotCloudAgent": item.get("used_copilot_cloud_agent", False),
                "UsedCopilotCodingAgent": item.get("used_copilot_coding_agent", False),
                "AiAdoptionPhase": item.get("ai_adoption_phase"),
            }
        )
        rows.append(row)
    return rows


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return value


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[dict[str, Any]]) -> None:
    names = [column["name"] for column in columns]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=names)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: csv_value(row[name]) for name in names})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare a unified GitHub Copilot budgets/seats/usage dataset for FinOps hubs ingestion."
    )
    parser.add_argument("--run-directory", type=Path)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output-root", type=Path, default=Path("staging"))
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path("schemas/github-copilot.schema.json"),
    )
    args = parser.parse_args()

    run_directory = args.run_directory or find_latest_run(args.data_root)
    manifest = load_json(run_directory / "manifest.json")
    schema_definition = load_json(args.schema)
    columns = schema_definition["columns"]

    rows = (
        normalize_budgets(run_directory, manifest)
        + normalize_seats(run_directory, manifest)
        + normalize_usage(run_directory, manifest)
    )

    collected_at = datetime.fromisoformat(
        manifest["collected_at_utc"].replace("Z", "+00:00")
    )
    ingestion_id = run_directory.name
    destination = (
        args.output_root
        / schema_definition["dataset"]
        / f"{collected_at.year:04d}"
        / f"{collected_at.month:02d}"
        / "github"
        / manifest["organization"]
    )
    destination.mkdir(parents=True, exist_ok=True)

    csv_path = destination / f"{ingestion_id}__github-copilot.csv"
    write_csv(csv_path, rows, columns)
    dataset_manifest = build_dataset_manifest(
        schema_definition,
        data_file_name=csv_path.name,
        data_blob_name=csv_path.relative_to(args.output_root).as_posix(),
        row_count=len(rows),
        organization=manifest["organization"],
        collected_at_utc=manifest["collected_at_utc"],
        source_files=[BUDGETS_SOURCE, SEATS_SOURCE, USAGE_SOURCE, USAGE_METADATA],
    )
    write_dataset_manifest(destination / "manifest.json", dataset_manifest)

    print(f"Run directory: {run_directory}")
    print(f"Rows: {len(rows)}")
    print(f"CSV: {csv_path}")


if __name__ == "__main__":
    main()
