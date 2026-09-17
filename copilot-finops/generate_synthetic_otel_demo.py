#!/usr/bin/env python3
"""
Generate SYNTHETIC GitHub Copilot usage + OTel-style token data for demo/dashboard
purposes only. Value-generation logic adapted from JerryMSFT/hackathon-jerry's
generate_mock_github.py (per-user intensity, agentic vs interactive token mix).

ALL DATA PRODUCED BY THIS SCRIPT IS FAKE. Organization is fixed to "Synthetic-Demo"
so it never mixes with real org data. Only fills the existing GitHubCopilot schema
columns (schemas/github-copilot.schema.json) -- no schema/pipeline changes.

Writes one CSV + manifest.json under staging/GitHubCopilot/<yyyy>/<mm>/github/Synthetic-Demo/,
ready for the existing publish-finops-dataset.ps1 mechanism.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dataset_manifest import build_dataset_manifest, write_dataset_manifest

SEED = 20260915
ORGANIZATION = "Synthetic-Demo"
SCHEMA_PATH = Path("schemas/github-copilot.schema.json")
OUTPUT_ROOT = Path("staging")

# Fictional population, deliberately unmistakable for real developers.
FIRST = [
    "charlie.brown", "snoopy", "lucy.vanpelt", "linus.vanpelt", "sally.brown",
    "schroeder", "peppermint.patty", "marcie", "pigpen", "woodstock",
    "franklin", "violet.gray",
]

# (model, share, agentic?)
MODELS = [
    ("gpt-5-codex", 0.34, False),
    ("claude-sonnet-4.5", 0.18, False),
    ("gpt-5-codex", 0.12, True),
    ("claude-sonnet-4.5", 0.22, True),
    ("gpt-5-mini", 0.09, False),
]
TOOLS = ["read_file", "run_in_terminal", "replace_string_in_file", "grep_search", "get_errors"]
AGENTS = ["copilot-chat", "copilot-cli", "copilot-coding-agent"]

# (sku, unit price per AI credit)
SKUS = [("copilot_chat", 0.04), ("copilot_cli", 0.04), ("copilot_coding_agent", 0.04)]


def build_population(rng: random.Random, count: int) -> list[dict[str, Any]]:
    pool = list(FIRST)
    rng.shuffle(pool)
    users = []
    for i in range(count):
        login = pool[i % len(pool)] if i < len(pool) else f"{rng.choice(FIRST)}-{rng.randint(10, 99)}"
        users.append({
            "user_login": login,
            "user_id": 900000 + i,
            "intensity": rng.choice([0.2, 0.4, 0.6, 0.8, 1.0, 1.0, 1.4, 2.2]),
            "agentic_lean": rng.random(),
        })
    return users


def gen_row(user: dict[str, Any], day: date, rng: random.Random, collected_at: str) -> dict[str, Any] | None:
    weekend = day.weekday() >= 5
    if weekend and rng.random() < 0.72:
        return None
    if rng.random() < 0.10:
        return None

    models_hit: set[str] = set()
    total_requests = 0
    total_input = 0
    total_output = 0
    tool_calls = 0
    latencies: list[float] = []

    for model, share, agentic in MODELS:
        odds = share * 2.4 * (1.6 if agentic and user["agentic_lean"] > 0.6 else 1.0)
        if rng.random() > odds:
            continue
        base = rng.uniform(8, 95) * user["intensity"]
        if agentic and user["agentic_lean"] > 0.75:
            base *= rng.uniform(2.0, 5.5)
        requests = max(1, int(base / 6))
        out_tok = int(base * rng.uniform(280, 620))
        in_tok = int(out_tok * rng.uniform(2.5, 9.0))

        models_hit.add(model)
        total_requests += requests
        total_input += in_tok
        total_output += out_tok
        latencies.append(rng.uniform(350, 1800) * (1.8 if agentic else 1.0))
        if agentic:
            tool_calls += rng.randint(1, 12)

    if total_requests == 0:
        return None

    suggested = int(rng.uniform(40, 420) * user["intensity"])
    accepted = int(suggested * rng.uniform(0.18, 0.42))

    primary_model = sorted(models_hit)[0]
    sku, rate = rng.choice(SKUS)
    gross_quantity = round(total_requests * rng.uniform(0.8, 3.5), 2)
    gross_amount = round(gross_quantity * rate, 4)
    discount_quantity = round(gross_quantity * rng.choice([0.0, 0.0, 0.10, 0.15]), 4)
    net_quantity = round(gross_quantity - discount_quantity, 4)
    net_amount = round(net_quantity * rate, 4)

    return {
        "x_RecordType": "UsageDaily",
        "x_RowKind": "Usage",
        "Organization": ORGANIZATION,
        "UserLogin": user["user_login"],
        "Day": day.isoformat(),
        "Interactions": int(rng.uniform(2, 40) * user["intensity"]),
        "CodeGenerations": suggested,
        "CodeAcceptances": accepted,
        "LocSuggestedToAdd": int(suggested * rng.uniform(0.5, 3)),
        "LocSuggestedToDelete": int(suggested * rng.uniform(0.05, 0.6)),
        "LocAdded": int(accepted * rng.uniform(0.5, 3)),
        "LocDeleted": int(accepted * rng.uniform(0.05, 0.6)),
        "UsedAgent": any(a for m, s, a in MODELS if m in models_hit),
        "UsedChat": True,
        "UsedCli": rng.random() < 0.3,
        "UsedCopilotCloudAgent": rng.random() < 0.15,
        "UsedCopilotCodingAgent": rng.random() < 0.2,
        "CollectedAtUtc": collected_at,
        "SourceFile": "synthetic/generate_synthetic_otel_demo.py",
        "SchemaVersion": "1.0",
        "AiCreditProduct": "Copilot",
        "AiCreditSku": sku,
        "AiCreditModel": primary_model,
        "AiCreditUnitType": "AI Credits",
        "AiCreditPricePerUnit": rate,
        "AiCreditGrossQuantity": gross_quantity,
        "AiCreditGrossAmount": gross_amount,
        "AiCreditDiscountQuantity": discount_quantity,
        "AiCreditDiscountAmount": round(gross_amount - net_amount, 4),
        "AiCreditNetQuantity": net_quantity,
        "AiCreditNetAmount": net_amount,
        "models_used": ";".join(sorted(models_hit)),
        "otel_request_count": total_requests,
        "otel_input_tokens": total_input,
        "otel_output_tokens": total_output,
        "otel_total_tokens": total_input + total_output,
        "otel_avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "otel_session_count": rng.randint(1, 6),
        "otel_agents_used": ";".join(sorted(rng.sample(AGENTS, k=rng.randint(1, len(AGENTS))))),
        "otel_tool_call_count": tool_calls,
        # "synthetic" is intentionally distinct from the real enrichment's
        # date/date-org/date-org-user levels -- this is fabricated demo data,
        # never to be confused with a genuine OTel correlation result.
        "otel_correlation_level": "synthetic",
    }


def gen_budget_rows(users: list[dict[str, Any]], collected_at: str, rng: random.Random) -> list[dict[str, Any]]:
    rows = [{
        "x_RecordType": "Budget",
        "Organization": ORGANIZATION,
        "BudgetId": "synthetic-org-budget",
        "BudgetType": "BundlePricing",
        "BudgetProductSku": "ai_credits",
        "BudgetScope": "organization",
        "BudgetAmount": 500,
        "PreventFurtherUsage": True,
        "BudgetEntityName": ORGANIZATION,
        "WillAlert": True,
        "AlertRecipientsJson": json.dumps([u["user_login"] for u in users[:3]]),
        "ConsumedAmount": round(rng.uniform(80, 420), 2),
        "CollectedAtUtc": collected_at,
        "SourceFile": "synthetic/generate_synthetic_otel_demo.py",
        "SchemaVersion": "1.0",
    }]
    for user in users:
        rows.append({
            "x_RecordType": "Budget",
            "Organization": ORGANIZATION,
            "BudgetId": f"synthetic-user-budget-{user['user_id']}",
            "BudgetType": "BundlePricing",
            "BudgetProductSku": "ai_credits",
            "BudgetScope": "user",
            "BudgetAmount": 50,
            "PreventFurtherUsage": True,
            "BudgetEntityName": user["user_login"],
            "WillAlert": True,
            "AlertRecipientsJson": json.dumps([user["user_login"]]),
            "ConsumedAmount": round(rng.uniform(5, 48) * user["intensity"], 2),
            "UserLogin": user["user_login"],
            "CollectedAtUtc": collected_at,
            "SourceFile": "synthetic/generate_synthetic_otel_demo.py",
            "SchemaVersion": "1.0",
        })
    return rows


def gen_seat_rows(users: list[dict[str, Any]], collected_at: str, rng: random.Random) -> list[dict[str, Any]]:
    rows = [{
        "x_RecordType": "Seat",
        "x_RowKind": "Snapshot",
        "Organization": ORGANIZATION,
        "TotalSeats": len(users),
        "CollectedAtUtc": collected_at,
        "SourceFile": "synthetic/generate_synthetic_otel_demo.py",
        "SchemaVersion": "1.0",
    }]
    for user in users:
        rows.append({
            "x_RecordType": "Seat",
            "x_RowKind": "Seat",
            "Organization": ORGANIZATION,
            "TotalSeats": len(users),
            "UserLogin": user["user_login"],
            "UserId": user["user_id"],
            "AssigneeType": "User",
            "AssigningTeam": rng.choice(["platform-core", "payments-api", "data-pipeline", ""]),
            "LastActivityAt": collected_at,
            "LastActivityEditor": rng.choice(["vscode", "jetbrains", "visual_studio"]),
            "LastAuthenticatedAt": collected_at,
            "CreatedAt": collected_at,
            "PlanType": "business",
            "CollectedAtUtc": collected_at,
            "SourceFile": "synthetic/generate_synthetic_otel_demo.py",
            "SchemaVersion": "1.0",
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--end-date", type=str, default=None, help="ISO date, default yesterday UTC")
    args = parser.parse_args()

    rng = random.Random(SEED)
    schema_definition = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    columns = schema_definition["columns"]
    column_names = [c["name"] for c in columns]

    end = date.fromisoformat(args.end_date) if args.end_date else date.today() - timedelta(days=1)
    days = [end - timedelta(days=i) for i in range(args.days - 1, -1, -1)]
    users = build_population(rng, args.users)

    collected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rows: list[dict[str, Any]] = []
    for day in days:
        for user in users:
            row = gen_row(user, day, rng, collected_at)
            if row:
                rows.append(row)
    rows.extend(gen_budget_rows(users, collected_at, rng))
    rows.extend(gen_seat_rows(users, collected_at, rng))

    full_rows = []
    for row in rows:
        full_row = {name: row.get(name, "") for name in column_names}
        full_rows.append(full_row)

    ingestion_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = OUTPUT_ROOT / schema_definition["dataset"] / f"{end.year:04d}" / f"{end.month:02d}" / "github" / ORGANIZATION
    destination.mkdir(parents=True, exist_ok=True)

    csv_name = f"{ingestion_id}__github-copilot-synthetic.csv"
    csv_path = destination / csv_name
    import csv as csv_module
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv_module.DictWriter(f, fieldnames=column_names)
        writer.writeheader()
        writer.writerows(full_rows)

    manifest = build_dataset_manifest(
        schema_definition,
        data_file_name=csv_name,
        data_blob_name=csv_path.relative_to(OUTPUT_ROOT).as_posix(),
        row_count=len(full_rows),
        organization=ORGANIZATION,
        collected_at_utc=collected_at,
        source_files=["synthetic/generate_synthetic_otel_demo.py"],
    )
    write_dataset_manifest(destination / "manifest.json", manifest)

    print("SYNTHETIC DATA -- not real usage, tokens, people or organizations")
    print(f"  window     : {days[0]} .. {days[-1]} ({len(days)} days)")
    print(f"  users      : {len(users)}")
    print(f"  rows       : {len(full_rows)}")
    print(f"  csv        : {csv_path}")
    print(f"  manifest   : {destination / 'manifest.json'}")


if __name__ == "__main__":
    main()
