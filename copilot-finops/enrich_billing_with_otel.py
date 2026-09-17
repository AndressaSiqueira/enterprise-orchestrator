"""Enrich an existing GitHub REST billing CSV with aggregated Copilot/OTEL telemetry.

This script is a standalone add-on. It does NOT modify the existing ADF pipeline,
Parquet conversion, ADX ingestion, Grafana dashboards, or OTEL Collector config.
It only reads the REST billing CSV, queries Azure Monitor Logs (Log Analytics
workspace or Application Insights resource) for the same date range, and writes:

  * github_usage_enriched.csv   (all original REST columns + new otel_* columns)
  * a JSON manifest/schema describing that CSV, compatible with the existing
    ADF pipeline's manifest shape (either updated from --existing-manifest, or
    freshly generated).

The OTEL table name and property/attribute names are NOT assumed. The script
discovers which tables actually have data in the requested time range, samples
rows from the most likely candidates, flattens whatever dynamic columns it
finds (Properties/Measurements/CustomDimensions/etc.), and heuristically maps
semantic fields (user, model, tokens, duration, session) to whatever real
column names show up. Every discovery/mapping decision is printed so a human
can confirm it before the join happens.

Prerequisites:
  pip install -r requirements.txt
  az login   (or any other credential supported by azure.identity.DefaultAzureCredential)

Example:
  python enrich_billing_with_otel.py \\
      --rest-csv billing/github_billing_2026-09.csv \\
      --workspace-id 00000000-0000-0000-0000-000000000000 \\
      --start-date 2026-09-01 --end-date 2026-09-30
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryStatus


# ---------------------------------------------------------------------------
# Field discovery heuristics (used to map REAL column names to semantic roles;
# nothing here is assumed to exist -- these are only candidate keywords used
# to score/rank whatever columns are actually discovered at runtime).
# ---------------------------------------------------------------------------

FIELD_KEYWORDS: dict[str, list[str]] = {
    "user": [
        "gen_ai.user.id", "user_login", "userlogin", "github_login", "githublogin",
        "user_id", "userid", "user.name", "username", "login", "upn",
        "user_email", "useremail", "actor", "identity", "principal",
    ],
    "organization": [
        "organization", "org_login", "orglogin", "org_name", "orgname",
        "account_name", "accountname", "enterprise",
    ],
    "model": [
        "gen_ai.request.model", "gen_ai.response.model", "model_name",
        "modelname", "ai_model", "aimodel", "model",
    ],
    "input_tokens": [
        "gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens",
        "input_tokens", "inputtoken", "prompt_tokens", "prompttoken",
        "tokens_input", "tokensin",
    ],
    "output_tokens": [
        "gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens",
        "output_tokens", "outputtoken", "completion_tokens", "completiontoken",
        "tokens_output", "tokensout",
    ],
    "total_tokens": [
        "gen_ai.usage.total_tokens", "total_tokens", "totaltoken", "tokens_total",
    ],
    "duration": [
        "duration_ms", "durationms", "duration", "latency_ms", "latencyms",
        "latency", "elapsed", "response_time_ms", "responsetime",
    ],
    "session": [
        "session_id", "sessionid", "conversation_id", "conversationid",
    ],
    "agent": [
        "agentname", "agent_name", "approlename", "app_role_name",
    ],
    "tool": [
        "gen_ai.tool.name", "toolname", "tool_name",
    ],
}

# TraceId / SpanId / ParentId / OperationId are OpenTelemetry correlation
# identifiers. They are intentionally NOT in FIELD_KEYWORDS and must never be
# used as a user identity -- only for linking rows across OTEL tables.

# Table names are only a display hint for ranking discovery output; the script
# never trusts a table just because its name looks right -- it always samples
# real rows and checks for a "copilot" hit before recommending a table.
LIKELY_TABLE_NAME_HINTS = (
    "copilot", "otel", "trace", "depend", "request", "event", "log",
)

NEW_OTEL_COLUMNS: list[dict[str, Any]] = [
    {"name": "models_used", "type": "string", "nullable": True},
    {"name": "otel_request_count", "type": "int64", "nullable": True},
    {"name": "otel_input_tokens", "type": "int64", "nullable": True},
    {"name": "otel_output_tokens", "type": "int64", "nullable": True},
    {"name": "otel_total_tokens", "type": "int64", "nullable": True},
    {"name": "otel_avg_latency_ms", "type": "double", "nullable": True},
    {"name": "otel_session_count", "type": "int64", "nullable": True},
    {"name": "otel_agents_used", "type": "string", "nullable": True},
    {"name": "otel_tool_call_count", "type": "int64", "nullable": True},
    {"name": "otel_correlation_level", "type": "string", "nullable": True},
]


# ---------------------------------------------------------------------------
# Azure Monitor Logs query helpers
# ---------------------------------------------------------------------------


def make_logs_client() -> LogsQueryClient:
    return LogsQueryClient(DefaultAzureCredential())


def run_kql(
    client: LogsQueryClient,
    query: str,
    timespan: tuple[datetime, datetime],
    *,
    workspace_id: str | None,
    resource_id: str | None,
) -> pd.DataFrame:
    try:
        if workspace_id:
            response = client.query_workspace(
                workspace_id=workspace_id, query=query, timespan=timespan
            )
        else:
            response = client.query_resource(
                resource_id=resource_id, query=query, timespan=timespan
            )
    except HttpResponseError as exc:
        raise RuntimeError(f"Azure Monitor query failed: {exc.message}\nQuery was:\n{query}") from exc

    if response.status == LogsQueryStatus.PARTIAL:
        print(f"WARNING: query returned partial results: {response.partial_error}")
        tables = response.partial_data
    elif response.status == LogsQueryStatus.SUCCESS:
        tables = response.tables
    else:
        raise RuntimeError(f"Unexpected Logs Query status: {response.status}")

    if not tables:
        return pd.DataFrame()
    table = tables[0]
    return pd.DataFrame(data=table.rows, columns=table.columns)


# ---------------------------------------------------------------------------
# Discovery: which tables actually have data, what columns/properties they have
# ---------------------------------------------------------------------------


def discover_tables_with_data(
    client: LogsQueryClient,
    timespan: tuple[datetime, datetime],
    *,
    workspace_id: str | None,
    resource_id: str | None,
) -> pd.DataFrame:
    query = (
        "union withsource=TableName1 *\n"
        "| summarize Count = count() by TableName1\n"
        "| order by Count desc"
    )
    return run_kql(client, query, timespan, workspace_id=workspace_id, resource_id=resource_id)


def sample_table(
    client: LogsQueryClient,
    table_name: str,
    timespan: tuple[datetime, datetime],
    *,
    workspace_id: str | None,
    resource_id: str | None,
    row_count: int,
) -> pd.DataFrame:
    query = f"{table_name}\n| take {row_count}"
    return run_kql(client, query, timespan, workspace_id=workspace_id, resource_id=resource_id)


def _try_parse_dynamic(value: Any) -> dict | list | None:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return None
    return None


def flatten_dynamic_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Expand dict-like columns (Properties/Measurements/CustomDimensions/...) in place."""
    if df.empty:
        return df

    flattened = df.copy()
    for column in df.columns:
        samples = [_try_parse_dynamic(value) for value in df[column].head(20) if value is not None]
        if not any(isinstance(sample, dict) for sample in samples):
            continue
        parsed = df[column].map(lambda value: _try_parse_dynamic(value) or {})
        normalized = pd.json_normalize(parsed)
        normalized.columns = [f"{column}.{name}" for name in normalized.columns]
        normalized.index = df.index
        flattened = flattened.drop(columns=[column]).join(normalized)
    return flattened


def table_contains_keyword(df: pd.DataFrame, keyword: str) -> bool:
    if df.empty:
        return False
    keyword = keyword.lower()
    return df.astype(str).apply(lambda col: col.str.lower().str.contains(keyword, na=False)).any().any()


def _normalize(name: str) -> str:
    return name.lower().replace("_", "").replace(".", "").replace("-", "")


def guess_field_mapping(columns: list[str]) -> dict[str, str | None]:
    mapping: dict[str, str | None] = {}
    normalized_columns = {column: _normalize(column) for column in columns}
    for field, keywords in FIELD_KEYWORDS.items():
        match: str | None = None
        for keyword in sorted(keywords, key=len, reverse=True):
            normalized_keyword = _normalize(keyword)
            for original, normalized in normalized_columns.items():
                if normalized_keyword in normalized:
                    match = original
                    break
            if match:
                break
        mapping[field] = match
    return mapping


def discover_otel_table(
    client: LogsQueryClient,
    timespan: tuple[datetime, datetime],
    *,
    workspace_id: str | None,
    resource_id: str | None,
    sample_rows: int,
    forced_table: str | None,
) -> tuple[str, pd.DataFrame, dict[str, str | None]]:
    print("\n=== Step 1: discovering tables with data in the requested time range ===")
    table_counts = discover_tables_with_data(
        client, timespan, workspace_id=workspace_id, resource_id=resource_id
    )
    if table_counts.empty:
        raise RuntimeError("No tables returned any data for the requested time range.")
    print(table_counts.to_string(index=False))

    if forced_table:
        candidates = [forced_table]
    else:
        ranked = table_counts.copy()
        ranked["_hint_score"] = ranked["TableName1"].str.lower().apply(
            lambda name: sum(hint in name for hint in LIKELY_TABLE_NAME_HINTS)
        )
        ranked = ranked.sort_values(["_hint_score", "Count"], ascending=[False, False])
        candidates = ranked["TableName1"].head(8).tolist()

    print("\n=== Step 2: sampling candidate tables to find real columns/properties ===")
    best_table: str | None = None
    best_sample: pd.DataFrame | None = None
    for table_name in candidates:
        raw_sample = sample_table(
            client, table_name, timespan,
            workspace_id=workspace_id, resource_id=resource_id, row_count=sample_rows,
        )
        if raw_sample.empty:
            continue
        flat_sample = flatten_dynamic_columns(raw_sample)
        has_copilot_hit = table_contains_keyword(flat_sample, "copilot")
        print(f"\n--- Table: {table_name} (copilot keyword hit: {has_copilot_hit}) ---")
        print(f"Columns discovered: {list(flat_sample.columns)}")
        if best_table is None or (has_copilot_hit and not table_contains_keyword(best_sample, "copilot")):
            best_table = table_name
            best_sample = flat_sample
        if forced_table:
            best_table, best_sample = table_name, flat_sample
            break

    if best_table is None or best_sample is None:
        raise RuntimeError(
            "None of the candidate tables returned sample rows. "
            "Pass --otel-table explicitly once you know which table to use."
        )

    mapping = guess_field_mapping(list(best_sample.columns))
    print(f"\n=== Selected OTEL table: {best_table} ===")
    print("Field mapping discovered (semantic field -> real column name):")
    for field, column in mapping.items():
        print(f"  {field:16s} -> {column}")

    return best_table, best_sample, mapping


# ---------------------------------------------------------------------------
# Full pull + aggregation
# ---------------------------------------------------------------------------


def fetch_otel_raw(
    client: LogsQueryClient,
    table_name: str,
    timespan: tuple[datetime, datetime],
    *,
    workspace_id: str | None,
    resource_id: str | None,
    max_rows: int,
) -> pd.DataFrame:
    print(f"\n=== Step 3: pulling raw OTEL rows from '{table_name}' (capped at {max_rows}) ===")
    query = f"{table_name}\n| take {max_rows}"
    raw = run_kql(client, query, timespan, workspace_id=workspace_id, resource_id=resource_id)
    print(f"Raw OTEL rows retrieved: {len(raw)}")
    return flatten_dynamic_columns(raw)


def discard_empty_mapped_columns(df: pd.DataFrame, mapping: dict[str, str | None]) -> dict[str, str | None]:
    """Drop any field mapping whose real column has zero non-empty values.

    A column matching by name (e.g. 'UserId') is not trusted just because the
    name looks right -- if every value retrieved is null/blank, the field is
    treated as absent rather than joined on, so we never fabricate a user
    mapping out of an always-empty column.
    """
    validated = dict(mapping)
    for field, column in mapping.items():
        if not column or column not in df.columns:
            continue
        series = df[column]
        has_values = (series.notna() & (series.astype(str).str.strip() != "")).any()
        if not has_values:
            print(
                f"NOTE: discovered column '{column}' for field '{field}' is always empty in the "
                "retrieved OTEL data -- discarding it rather than trusting the name."
            )
            validated[field] = None
    return validated


def build_otel_aggregate(
    df: pd.DataFrame,
    mapping: dict[str, str | None],
    *,
    time_column: str = "TimeGenerated",
    overrides: dict[str, str | None],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Aggregate OTEL rows. Falls back to organization/date-level aggregation
    (no user_level) when no user identity field exists in the OTEL data --
    never fabricates or infers a user mapping."""
    mapping = {**mapping, **{key: value for key, value in overrides.items() if value}}
    mapping = discard_empty_mapped_columns(df, mapping)

    if time_column not in df.columns:
        raise ValueError(f"Expected timestamp column '{time_column}' was not found in OTEL data.")

    working = df.copy()
    working["_otel_date"] = pd.to_datetime(working[time_column], utc=True, errors="coerce").dt.date.astype(str)

    user_col = mapping.get("user")
    user_level = bool(user_col)
    if user_level:
        working["_otel_user"] = working[user_col].astype("string")

    org_col = mapping.get("organization")
    if org_col:
        working["_otel_org"] = working[org_col].astype("string")

    model_col = mapping.get("model")
    input_col = mapping.get("input_tokens")
    output_col = mapping.get("output_tokens")
    total_col = mapping.get("total_tokens")
    duration_col = mapping.get("duration")
    session_col = mapping.get("session")
    agent_col = mapping.get("agent")
    tool_col = mapping.get("tool")

    for column in (input_col, output_col, total_col, duration_col):
        if column:
            working[column] = pd.to_numeric(working[column], errors="coerce")

    if user_level:
        group_keys = ["_otel_date", "_otel_org", "_otel_user"] if org_col else ["_otel_date", "_otel_user"]
        correlation_level = "date/org/user" if org_col else "date/user"
    else:
        group_keys = ["_otel_date", "_otel_org"] if org_col else ["_otel_date"]
        correlation_level = "date/org" if org_col else "date"
        print(
            "\nNOTE: no user identity field was found (or provided via --otel-user-column) in the OTEL data. "
            f"Falling back to {correlation_level}-level aggregation. "
            "No user identity mapping is being inferred or fabricated."
        )
    grouped = working.groupby(group_keys, dropna=False)

    size_column = "_otel_user" if user_level else "_otel_date"
    agg_spec: dict[str, pd.NamedAgg] = {
        "otel_request_count": pd.NamedAgg(column=size_column, aggfunc="size"),
    }
    if input_col:
        agg_spec["otel_input_tokens"] = pd.NamedAgg(column=input_col, aggfunc="sum")
    if output_col:
        agg_spec["otel_output_tokens"] = pd.NamedAgg(column=output_col, aggfunc="sum")
    if total_col:
        agg_spec["otel_total_tokens"] = pd.NamedAgg(column=total_col, aggfunc="sum")
    if duration_col:
        agg_spec["otel_avg_latency_ms"] = pd.NamedAgg(column=duration_col, aggfunc="mean")
    if session_col:
        agg_spec["otel_session_count"] = pd.NamedAgg(column=session_col, aggfunc="nunique")
    if model_col:
        agg_spec["models_used"] = pd.NamedAgg(
            column=model_col,
            aggfunc=lambda series: ";".join(sorted({str(value) for value in series.dropna().unique()})),
        )
    if agent_col:
        agg_spec["otel_agents_used"] = pd.NamedAgg(
            column=agent_col,
            aggfunc=lambda series: ";".join(sorted({str(value) for value in series.dropna().unique() if str(value)})),
        )
    if tool_col:
        agg_spec["otel_tool_call_count"] = pd.NamedAgg(column=tool_col, aggfunc="count")

    result = grouped.agg(**agg_spec).reset_index()

    if not total_col and input_col and output_col:
        result["otel_total_tokens"] = result["otel_input_tokens"].fillna(0) + result["otel_output_tokens"].fillna(0)

    for column, default in (
        ("models_used", ""),
        ("otel_input_tokens", pd.NA),
        ("otel_output_tokens", pd.NA),
        ("otel_total_tokens", pd.NA),
        ("otel_avg_latency_ms", pd.NA),
        ("otel_session_count", pd.NA),
        ("otel_agents_used", ""),
        ("otel_tool_call_count", pd.NA),
    ):
        if column not in result.columns:
            result[column] = default

    result = result.rename(columns={"_otel_date": "Date"})
    if user_level:
        result = result.rename(columns={"_otel_user": "User"})
    if org_col:
        result = result.rename(columns={"_otel_org": "Organization"})
    result["otel_correlation_level"] = correlation_level

    meta = {
        "user_level": user_level,
        "correlation_level": correlation_level,
        "group_keys": group_keys,
        "org_col": org_col,
    }
    return result, meta


def fetch_agent_usage_supplement(
    client: LogsQueryClient,
    table_counts: pd.DataFrame,
    primary_table: str,
    timespan: tuple[datetime, datetime],
    *,
    workspace_id: str | None,
    resource_id: str | None,
    max_rows: int,
) -> pd.DataFrame | None:
    """Supplement otel_agents_used from AppGenAIContent's AgentName column, if that
    table exists and wasn't already the primary table. Only AgentName/TimeGenerated
    are read -- InputMessages/OutputMessages are never inspected, per instruction
    not to infer identity from message content. TraceId/SpanId/ParentSpanId exist
    on this table only as correlation identifiers; they are not read here either.
    """
    table_name = "AppGenAIContent"
    if table_name == primary_table:
        return None
    if table_name not in set(table_counts["TableName1"]):
        return None

    print(f"\n=== Supplement: pulling AgentName from '{table_name}' (capped at {max_rows}) ===")
    query = f"{table_name}\n| project TimeGenerated, AgentName\n| take {max_rows}"
    raw = run_kql(client, query, timespan, workspace_id=workspace_id, resource_id=resource_id)
    if raw.empty or "AgentName" not in raw.columns:
        print(f"NOTE: '{table_name}' returned no usable AgentName rows; skipping agent supplement.")
        return None

    raw["_otel_date"] = pd.to_datetime(raw["TimeGenerated"], utc=True, errors="coerce").dt.date.astype(str)
    supplement = (
        raw.groupby("_otel_date")["AgentName"]
        .apply(lambda series: ";".join(sorted({str(value) for value in series.dropna().unique() if str(value)})))
        .rename("otel_agents_used")
        .reset_index()
        .rename(columns={"_otel_date": "Date"})
    )
    print(f"Agent supplement rows: {len(supplement)} distinct dates")
    return supplement


def apply_agent_supplement(otel_agg_df: pd.DataFrame, supplement: pd.DataFrame | None) -> pd.DataFrame:
    if supplement is None or supplement.empty:
        return otel_agg_df
    merged = otel_agg_df.merge(supplement, on="Date", how="left", suffixes=("", "_supplement"))
    if "otel_agents_used_supplement" in merged.columns:
        existing = merged["otel_agents_used"].fillna("") if "otel_agents_used" in merged.columns else ""
        supplemented = merged["otel_agents_used_supplement"].fillna("")
        merged["otel_agents_used"] = [
            ";".join(sorted({v for v in f"{a};{b}".split(";") if v})) for a, b in zip(existing, supplemented)
        ]
        merged = merged.drop(columns=["otel_agents_used_supplement"])
    return merged


# ---------------------------------------------------------------------------
# REST CSV side
# ---------------------------------------------------------------------------


def auto_detect_column(columns: list[str], keywords: list[str]) -> str | None:
    normalized_columns = {column: _normalize(column) for column in columns}
    for keyword in keywords:
        normalized_keyword = _normalize(keyword)
        for original, normalized in normalized_columns.items():
            if normalized_keyword in normalized:
                return original
    return None


def infer_rest_schema_columns(rest_df: pd.DataFrame) -> list[dict[str, Any]]:
    type_map = {
        "int64": "int64",
        "float64": "double",
        "bool": "bool",
        "datetime64[ns]": "datetime",
        "datetime64[ns, UTC]": "datetime",
    }
    columns = []
    for name, dtype in rest_df.dtypes.items():
        columns.append(
            {
                "name": str(name),
                "type": type_map.get(str(dtype), "string"),
                "nullable": bool(rest_df[name].isna().any()),
            }
        )
    return columns


def locate_columns_list(manifest: dict[str, Any]) -> tuple[Any, list[dict[str, Any]]]:
    if "columns" in manifest:
        return manifest, manifest["columns"]
    if "schema" in manifest and "columns" in manifest["schema"]:
        return manifest["schema"], manifest["schema"]["columns"]
    raise ValueError(
        "Could not find a 'columns' list in the existing manifest "
        "(looked at top-level 'columns' and 'schema.columns')."
    )


def build_or_update_manifest(
    existing_manifest_path: Path | None,
    rest_df: pd.DataFrame,
    output_csv_name: str,
    row_count: int,
) -> dict[str, Any]:
    if existing_manifest_path:
        manifest = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
        container, columns = locate_columns_list(manifest)
        existing_names = {column["name"] for column in columns}
        for new_column in NEW_OTEL_COLUMNS:
            if new_column["name"] not in existing_names:
                columns.append(new_column)
        container["columns"] = columns
        manifest["dataRowCount"] = row_count
        if "files" in manifest and manifest["files"]:
            manifest["files"][0]["name"] = output_csv_name
            manifest["files"][0]["rowCount"] = row_count
        if "blobs" in manifest and manifest["blobs"]:
            previous_blob_name = manifest["blobs"][0].get("blobName", "")
            blob_prefix, separator, _ = previous_blob_name.rpartition("/")
            manifest["blobs"][0]["blobName"] = (
                f"{blob_prefix}/{output_csv_name}" if separator else output_csv_name
            )
        if "schema" in manifest and "sha256" in manifest["schema"]:
            canonical_schema = json.dumps(
                columns, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            manifest["schema"]["sha256"] = hashlib.sha256(canonical_schema).hexdigest()
        return manifest

    return {
        "manifestVersion": "1.0",
        "dataset": "GitHubUsageEnriched",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "dataRowCount": row_count,
        "files": [{"name": output_csv_name, "format": "csv", "rowCount": row_count}],
        "columns": infer_rest_schema_columns(rest_df) + NEW_OTEL_COLUMNS,
    }


# ---------------------------------------------------------------------------
# Join + validation
# ---------------------------------------------------------------------------


def print_identifier_report(rest_users: set[str], otel_users: set[str]) -> None:
    print("\n=== Step 4: identifiers available on both sides (confirm before merging) ===")
    print(f"REST distinct users ({len(rest_users)}): {sorted(rest_users)[:10]}")
    print(f"OTEL distinct users ({len(otel_users)}): {sorted(otel_users)[:10]}")
    overlap = rest_users & otel_users
    print(f"Exact-match overlap: {len(overlap)}")
    if not overlap:
        print(
            "WARNING: zero overlap between REST and OTEL user identifiers. "
            "The join key is likely wrong -- inspect the columns printed above and "
            "pass --otel-user-column / --rest-user-column explicitly."
        )


def print_no_user_correlation_notice(correlation_level: str) -> None:
    print("\n=== Step 4: identifiers available on both sides (confirm before merging) ===")
    print("OTEL telemetry has NO user identity field (checked discovered columns and --otel-user-column override).")
    print("User-level OTel correlation: NOT PERFORMED")
    print("Reason: no deterministic GitHub user identity found in current OTel data")
    print(f"Enrichment join level: {correlation_level}")
    print(
        "Enrichment will be joined at that level only, applied identically to every REST row sharing "
        "that key -- no user identity mapping is being inferred or fabricated."
    )


def merge_rest_and_otel(
    rest_df: pd.DataFrame,
    otel_agg_df: pd.DataFrame,
    meta: dict[str, Any],
    *,
    rest_user_col: str,
    rest_date_col: str,
    rest_org_col: str | None,
) -> pd.DataFrame:
    rest = rest_df.copy()
    # Drop empty otel_*/models_used placeholders already present in the REST CSV
    # (emitted by prepare-copilot-github.py's schema defaults) so the merge below
    # doesn't collide and suffix them as _x/_y.
    placeholder_columns = [c["name"] for c in NEW_OTEL_COLUMNS if c["name"] in rest.columns]
    if placeholder_columns:
        rest = rest.drop(columns=placeholder_columns)
    rest["_merge_date"] = pd.to_datetime(rest[rest_date_col], errors="coerce").dt.date.astype(str)

    otel = otel_agg_df.copy()
    otel["_merge_date"] = otel["Date"]

    join_keys = ["_merge_date"]
    drop_from_otel = ["Date"]

    if meta["user_level"]:
        rest["_merge_user"] = rest[rest_user_col].astype("string").str.strip().str.lower()
        otel["_merge_user"] = otel["User"].astype("string").str.strip().str.lower()
        join_keys.append("_merge_user")
        drop_from_otel.append("User")

    if meta["org_col"] and rest_org_col and "Organization" in otel.columns:
        rest["_merge_org"] = rest[rest_org_col].astype("string").str.strip().str.lower()
        otel["_merge_org"] = otel["Organization"].astype("string").str.strip().str.lower()
        join_keys.append("_merge_org")
        drop_from_otel.append("Organization")

    merged = rest.merge(otel.drop(columns=drop_from_otel), on=join_keys, how="left")
    merged = merged.drop(columns=[column for column in merged.columns if column.startswith("_merge_")])

    fill_defaults = {
        "models_used": "",
        "otel_request_count": 0,
        "otel_input_tokens": 0,
        "otel_output_tokens": 0,
        "otel_total_tokens": 0,
        "otel_session_count": 0,
        "otel_agents_used": "",
        "otel_tool_call_count": 0,
        "otel_correlation_level": meta["correlation_level"],
    }
    for column, default in fill_defaults.items():
        if column in merged.columns:
            merged[column] = merged[column].fillna(default)
    return merged


def print_validation_summary(
    rest_df: pd.DataFrame,
    otel_raw_df: pd.DataFrame,
    otel_agg_df: pd.DataFrame,
    meta: dict[str, Any],
    *,
    rest_users: set[str] | None,
    otel_users: set[str] | None,
    rest_date_col: str,
    rest_org_col: str | None,
) -> None:
    print("\n=== Validation summary ===")
    print(f"REST rows:                {len(rest_df)}")
    print(f"OTEL records retrieved:   {len(otel_raw_df)}")

    if meta["user_level"]:
        assert rest_users is not None and otel_users is not None
        matched = rest_users & otel_users
        unmatched_rest = rest_users - otel_users
        unmatched_otel = otel_users - rest_users
        print("User-level OTEL correlation: PERFORMED")
        print(f"Matched users:            {len(matched)}")
        print(f"Unmatched REST users:     {len(unmatched_rest)}")
        print(f"Unmatched OTEL users:     {len(unmatched_otel)}")
        return

    print("User-level OTel correlation: NOT PERFORMED")
    print("Reason: no deterministic GitHub user identity found in current OTel data")
    print(f"Enrichment join level: {meta['correlation_level']}")

    rest_keys = set(pd.to_datetime(rest_df[rest_date_col], errors="coerce").dt.date.astype(str))
    if meta["org_col"] and rest_org_col:
        rest_keys = set(
            zip(
                pd.to_datetime(rest_df[rest_date_col], errors="coerce").dt.date.astype(str),
                rest_df[rest_org_col].astype("string").str.strip().str.lower(),
            )
        )
        otel_keys = set(
            zip(otel_agg_df["Date"], otel_agg_df["Organization"].astype("string").str.strip().str.lower())
        )
    else:
        otel_keys = set(otel_agg_df["Date"])

    matched_keys = rest_keys & otel_keys
    unmatched_rest_keys = rest_keys - otel_keys
    unmatched_otel_keys = otel_keys - rest_keys
    print(f"Matched {meta['correlation_level']} groups:      {len(matched_keys)}")
    print(f"Unmatched REST {meta['correlation_level']} groups: {len(unmatched_rest_keys)}")
    print(f"Unmatched OTEL {meta['correlation_level']} groups: {len(unmatched_otel_keys)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rest-csv", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, default=Path("github_usage_enriched.csv"))
    parser.add_argument("--output-manifest", type=Path, default=Path("github_usage_enriched.manifest.json"))
    parser.add_argument("--existing-manifest", type=Path, default=None)

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--workspace-id", help="Log Analytics workspace GUID")
    target.add_argument("--resource-id", help="Azure Resource ID of an Application Insights component")

    parser.add_argument("--start-date", type=str, default=None, help="ISO date, defaults to min date in REST CSV")
    parser.add_argument("--end-date", type=str, default=None, help="ISO date, defaults to max date in REST CSV")

    parser.add_argument("--rest-user-column", default=None)
    parser.add_argument("--rest-date-column", default=None)
    parser.add_argument("--rest-org-column", default=None)

    parser.add_argument(
        "--otel-table",
        default=None,
        help="Skip discovery ranking and sample this table directly (name unknown until discovery runs).",
    )
    parser.add_argument("--otel-user-column", default=None)
    parser.add_argument("--otel-org-column", default=None)
    parser.add_argument("--otel-model-column", default=None)
    parser.add_argument("--otel-input-tokens-column", default=None)
    parser.add_argument("--otel-output-tokens-column", default=None)
    parser.add_argument("--otel-total-tokens-column", default=None)
    parser.add_argument("--otel-duration-column", default=None)
    parser.add_argument("--otel-session-column", default=None)

    parser.add_argument("--max-otel-rows", type=int, default=200_000)
    parser.add_argument("--sample-rows", type=int, default=5)
    parser.add_argument("--assume-yes", action="store_true", help="Skip the pre-merge confirmation prompt")
    return parser.parse_args(argv)


def resolve_timespan(args: argparse.Namespace, rest_df: pd.DataFrame, rest_date_col: str) -> tuple[datetime, datetime]:
    if args.start_date and args.end_date:
        start = datetime.fromisoformat(args.start_date).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(args.end_date).replace(tzinfo=timezone.utc) + timedelta(days=1)
        return start, end

    parsed_dates = pd.to_datetime(rest_df[rest_date_col], errors="coerce").dropna()
    if parsed_dates.empty:
        raise ValueError(
            f"Could not infer a date range from column '{rest_date_col}'. Pass --start-date/--end-date explicitly."
        )
    start_value = parsed_dates.min()
    end_value = parsed_dates.max()
    start = datetime.combine(start_value.date(), datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(end_value.date(), datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
    return start, end


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    rest_df = pd.read_csv(args.rest_csv)
    print(f"REST billing CSV loaded: {args.rest_csv} ({len(rest_df)} rows, {len(rest_df.columns)} columns)")
    print(f"REST columns: {list(rest_df.columns)}")

    rest_user_col = args.rest_user_column or auto_detect_column(
        list(rest_df.columns), FIELD_KEYWORDS["user"]
    )
    rest_date_col = args.rest_date_column or auto_detect_column(
        list(rest_df.columns), ["day", "date", "period", "usage_date"]
    )
    rest_org_col = args.rest_org_column or auto_detect_column(
        list(rest_df.columns), FIELD_KEYWORDS["organization"]
    )
    if not rest_user_col or not rest_date_col:
        raise SystemExit(
            "Could not auto-detect the REST user/date columns. "
            "Pass --rest-user-column and --rest-date-column explicitly."
        )
    print(f"REST user column:   {rest_user_col}")
    print(f"REST date column:   {rest_date_col}")
    print(f"REST org column:    {rest_org_col}")

    timespan = resolve_timespan(args, rest_df, rest_date_col)
    print(f"Time range for OTEL query: {timespan[0].isoformat()} .. {timespan[1].isoformat()}")

    client = make_logs_client()
    table_name, _sample_df, discovered_mapping = discover_otel_table(
        client,
        timespan,
        workspace_id=args.workspace_id,
        resource_id=args.resource_id,
        sample_rows=args.sample_rows,
        forced_table=args.otel_table or None,
    )

    otel_raw_df = fetch_otel_raw(
        client,
        table_name,
        timespan,
        workspace_id=args.workspace_id,
        resource_id=args.resource_id,
        max_rows=args.max_otel_rows,
    )
    if otel_raw_df.empty:
        raise SystemExit(f"No OTEL rows found in '{table_name}' for the requested time range.")

    overrides = {
        "user": args.otel_user_column,
        "organization": args.otel_org_column,
        "model": args.otel_model_column,
        "input_tokens": args.otel_input_tokens_column,
        "output_tokens": args.otel_output_tokens_column,
        "total_tokens": args.otel_total_tokens_column,
        "duration": args.otel_duration_column,
        "session": args.otel_session_column,
    }
    otel_agg_df, meta = build_otel_aggregate(otel_raw_df, discovered_mapping, overrides=overrides)

    table_counts = discover_tables_with_data(
        client, timespan, workspace_id=args.workspace_id, resource_id=args.resource_id
    )
    agent_supplement = fetch_agent_usage_supplement(
        client, table_counts, table_name, timespan,
        workspace_id=args.workspace_id, resource_id=args.resource_id, max_rows=args.max_otel_rows,
    )
    otel_agg_df = apply_agent_supplement(otel_agg_df, agent_supplement)

    rest_users: set[str] | None = None
    otel_users: set[str] | None = None
    if meta["user_level"]:
        rest_users = set(rest_df[rest_user_col].dropna().astype(str).str.strip().str.lower())
        otel_users = set(otel_agg_df["User"].dropna().astype(str).str.strip().str.lower())
        print_identifier_report(rest_users, otel_users)
    else:
        print_no_user_correlation_notice(meta["correlation_level"])

    if not args.assume_yes:
        answer = input("\nProceed with the merge using the identifiers above? [y/N]: ").strip().lower()
        if answer != "y":
            print("Aborted before merge. Re-run with column overrides once the mapping looks right.")
            sys.exit(1)

    merged_df = merge_rest_and_otel(
        rest_df, otel_agg_df, meta,
        rest_user_col=rest_user_col, rest_date_col=rest_date_col, rest_org_col=rest_org_col,
    )

    print_validation_summary(
        rest_df, otel_raw_df, otel_agg_df, meta,
        rest_users=rest_users, otel_users=otel_users,
        rest_date_col=rest_date_col, rest_org_col=rest_org_col,
    )

    merged_df.to_csv(args.output_csv, index=False)
    print(f"\nWrote enriched CSV: {args.output_csv} ({len(merged_df)} rows)")

    manifest = build_or_update_manifest(
        args.existing_manifest, rest_df, args.output_csv.name, len(merged_df)
    )
    args.output_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote manifest/schema: {args.output_manifest}")
    print(
        "\nNo changes were made to the existing ADF pipeline, Parquet conversion, "
        "ADX ingestion, Grafana, or OTEL Collector configuration."
    )


if __name__ == "__main__":
    main()
