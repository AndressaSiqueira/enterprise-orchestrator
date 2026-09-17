#!/usr/bin/env python3
"""
Generate SYNTHETIC FOCUS-shaped GitHub Copilot cost/usage rows for demo/dashboard
purposes only, adapted from JerryMSFT/hackathon-jerry's generate_mock_github.py.

Unlike prepare-copilot-focus.py (real data, x_AITokens*/model/agent left honestly
empty because our real GitHub REST sources have zero token/model detail), this
script fabricates full token/model/agent detail because none of it is real --
Organization is fixed to "Synthetic-Demo" so it can never be confused with
genuine organization rows in schemas/github-copilot-focus.schema.json.

Writes one CSV + manifest.json under staging/GitHubCopilotFocus/<yyyy>/<mm>/github/Synthetic-Demo/,
ready for the existing publish-finops-dataset.ps1 mechanism.
"""

from __future__ import annotations

import argparse
import csv as csv_module
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dataset_manifest import build_dataset_manifest, write_dataset_manifest

SEED = 20260915
ORGANIZATION = "Synthetic-Demo"
SCHEMA_PATH = Path("schemas/github-copilot-focus.schema.json")
OUTPUT_ROOT = Path("staging")

PROVIDER = "GitHub"
SERVICE_NAME = "GitHub Copilot"
SERVICE_CATEGORY = "AI and Machine Learning"
SERVICE_SUBCATEGORY = "Developer Productivity"

FIRST = [
    "charlie.brown", "snoopy", "lucy.vanpelt", "linus.vanpelt", "sally.brown",
    "schroeder", "peppermint.patty", "marcie", "pigpen", "woodstock",
    "franklin", "violet.gray",
]

# (model, provider, share, agentic?)
MODELS = [
    ("gpt-5-codex", "OpenAI", 0.34, False),
    ("claude-sonnet-4.5", "Anthropic", 0.18, False),
    ("gpt-5-codex", "OpenAI", 0.12, True),
    ("claude-sonnet-4.5", "Anthropic", 0.22, True),
    ("gpt-5-mini", "OpenAI", 0.09, False),
]
AGENTS = ["copilot-chat", "copilot-cli", "copilot-coding-agent"]
SKUS = [("copilot_chat", 0.04), ("copilot_cli", 0.04), ("copilot_coding_agent", 0.04)]


def build_population(rng: random.Random, count: int) -> list[dict[str, Any]]:
    pool = list(FIRST)
    rng.shuffle(pool)
    users = []
    for i in range(count):
        login = pool[i % len(pool)] if i < len(pool) else f"{rng.choice(FIRST)}-{rng.randint(10, 99)}"
        users.append({
            "user_login": login,
            "intensity": rng.choice([0.2, 0.4, 0.6, 0.8, 1.0, 1.0, 1.4, 2.2]),
            "agentic_lean": rng.random(),
        })
    return users


def month_bounds(day: date) -> tuple[str, str]:
    first = day.replace(day=1)
    nxt = (first.replace(year=first.year + 1, month=1) if first.month == 12
           else first.replace(month=first.month + 1))
    return first.isoformat(), nxt.isoformat()


def gen_row(
    user: dict[str, Any], day: date, rng: random.Random, collected_at: str, column_names: list[str]
) -> dict[str, Any] | None:
    weekend = day.weekday() >= 5
    if weekend and rng.random() < 0.72:
        return None
    if rng.random() < 0.10:
        return None

    model, provider, share, agentic = rng.choice(MODELS)
    base = rng.uniform(8, 95) * user["intensity"]
    if agentic and user["agentic_lean"] > 0.75:
        base *= rng.uniform(2.0, 5.5)
    requests = max(1, int(base / 6))
    out_tok = int(base * rng.uniform(280, 620))
    in_tok = int(out_tok * rng.uniform(2.5, 9.0))
    cache_read = int(in_tok * rng.uniform(0.1, 0.4))
    cache_write = int(in_tok * rng.uniform(0.02, 0.12))

    sku, rate = rng.choice(SKUS)
    gross_quantity = round(requests * rng.uniform(0.8, 3.5), 2)
    gross_amount = round(gross_quantity * rate, 4)
    discount_quantity = round(gross_quantity * rng.choice([0.0, 0.0, 0.10, 0.15]), 4)
    net_quantity = round(gross_quantity - discount_quantity, 4)
    net_amount = round(net_quantity * rate, 4)
    bp_start, bp_end = month_bounds(day)

    row = {name: "" for name in column_names}
    row.update({
        "BilledCost": net_amount,
        "ListCost": gross_amount,
        "ContractedCost": net_amount,
        "EffectiveCost": net_amount,
        "BillingAccountId": ORGANIZATION,
        "BillingAccountName": ORGANIZATION,
        "BillingAccountType": "Enterprise",
        "BillingCurrency": "USD",
        "BillingPeriodStart": bp_start,
        "BillingPeriodEnd": bp_end,
        "ChargePeriodStart": day.isoformat(),
        "ChargePeriodEnd": (day + timedelta(days=1)).isoformat(),
        "ChargeCategory": "Usage",
        "ChargeFrequency": "Usage-Based",
        "ChargeDescription": f"{SERVICE_NAME} {sku} ({model})",
        "ConsumedQuantity": gross_quantity,
        "ConsumedUnit": "AI Credits",
        "PricingQuantity": gross_quantity,
        "PricingUnit": "AI Credits",
        "ListUnitPrice": rate,
        "ContractedUnitPrice": rate,
        "ProviderName": PROVIDER,
        "PublisherName": PROVIDER,
        "InvoiceIssuerName": PROVIDER,
        "ServiceName": SERVICE_NAME,
        "ServiceCategory": SERVICE_CATEGORY,
        "ServiceSubcategory": SERVICE_SUBCATEGORY,
        "SkuId": sku,
        "SkuMeter": model,
        "SubAccountId": ORGANIZATION,
        "SubAccountName": ORGANIZATION,
        "SubAccountType": "Organization",
        "x_BilledCostInUsd": net_amount,
        "x_ListCostInUsd": gross_amount,
        "x_BilledUnitPrice": rate,
        "x_EffectiveUnitPrice": rate,
        "x_CostType": "Usage",
        "x_UsageType": "Interactive" if not agentic else "Agentic",
        "x_SkuMeterCategory": "AI Credits",
        "x_IngestionTime": collected_at,
        "x_ExportTime": collected_at,
        "x_SourceName": "Synthetic demo generator",
        "x_SourceProvider": "generate_synthetic_focus_demo.py",
        "x_SourceType": "Fabricated demo data",
        "x_SourceVersion": "1.0",
        "x_SourceValues": json.dumps({"sku": sku, "model": model, "requests": requests}),
        "x_AICreditQuantity": net_quantity,
        "x_AICreditGrossAmount": gross_amount,
        "x_AIDiscountAmount": round(gross_amount - net_amount, 4),
        "x_AIDiscountQuantity": discount_quantity,
        "x_AIModelName": model,
        "x_AIModelProvider": provider,
        "x_AIAgentSurface": rng.choice(AGENTS) if agentic else "copilot-chat",
        "x_AITokensInput": in_tok,
        "x_AITokensOutput": out_tok,
        "x_AITokensCacheRead": cache_read,
        "x_AITokensCacheWrite": cache_write,
        "x_AITokensTotal": in_tok + out_tok + cache_read + cache_write,
        "x_AIPrincipalRef": user["user_login"],
        "x_AIAttributionGrain": "principal",
    })
    return row


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
            row = gen_row(user, day, rng, collected_at, column_names)
            if row:
                rows.append(row)

    ingestion_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = OUTPUT_ROOT / schema_definition["dataset"] / f"{end.year:04d}" / f"{end.month:02d}" / "github" / ORGANIZATION
    destination.mkdir(parents=True, exist_ok=True)

    csv_name = f"{ingestion_id}__github-copilot-focus-synthetic.csv"
    csv_path = destination / csv_name
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv_module.DictWriter(f, fieldnames=column_names)
        writer.writeheader()
        writer.writerows(rows)

    manifest = build_dataset_manifest(
        schema_definition,
        data_file_name=csv_name,
        data_blob_name=csv_path.relative_to(OUTPUT_ROOT).as_posix(),
        row_count=len(rows),
        organization=ORGANIZATION,
        collected_at_utc=collected_at,
        source_files=["synthetic/generate_synthetic_focus_demo.py"],
    )
    write_dataset_manifest(destination / "manifest.json", manifest)

    print("SYNTHETIC FOCUS DATA -- not real usage, tokens, models or organizations")
    print(f"  window     : {days[0]} .. {days[-1]} ({len(days)} days)")
    print(f"  users      : {len(users)}")
    print(f"  rows       : {len(rows)}")
    print(f"  csv        : {csv_path}")
    print(f"  manifest   : {destination / 'manifest.json'}")


if __name__ == "__main__":
    main()
