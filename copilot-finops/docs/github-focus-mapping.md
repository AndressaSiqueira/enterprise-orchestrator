# GitHub Copilot FinOps and FOCUS Mapping

## Status and decision

This document reviews the current GitHub Copilot datasets against the FinOps for AI framework and FOCUS 1.4. FOCUS 1.4 is the implementation baseline. FOCUS 1.5 is forward-looking guidance only; it is scheduled for ratification in December 2026 and is not treated as a published requirement.

The current datasets are not a FOCUS Cost and Usage dataset:

- `GitHubCopilotBudgets` contains governance configuration and reported budget consumption.
- `GitHubCopilotSeats` contains SaaS license inventory and assignment state.
- `GitHubCopilotUserUsage` contains user-level product telemetry, adoption, and productivity signals.

No current field is mapped directly to a FOCUS 1.4 column. This is intentional. Similar names do not establish equivalent semantics, and the current sources do not provide a complete FOCUS charge row. Existing working schemas remain unchanged and are documented as provider-specific fields. New provider-specific fields must use the `x_` prefix; existing fields are grandfathered until a versioned schema migration is approved.

Financial charges from GitHub billing usage exports must be modeled separately from budgets, seats, and telemetry. They must be reconciled to an authoritative billing feed before any FOCUS cost view is introduced. Telemetry must never create an additional billed-cost record.

## References reviewed

| Reference | Version/status reviewed | Design use |
|---|---|---|
| [FinOps for AI: Mapping AI to the FinOps Framework](https://www.finops.org/wg/finops-for-ai-overview/#mapping-to-finops-framework) | Web content reviewed 2026-09-15; page last updated 2026-02-17 | Usage and cost separation, ingestion, allocation, reporting, benchmarking, unit economics, governance |
| [FinOps for AI: KPIs and FOCUS alignment](https://www.finops.org/framework/technology-categories/ai/) | Web content reviewed 2026-09-15 | AI KPI semantics and additive telemetry alongside cost and usage data |
| [FOCUS Cost and Usage Column Library](https://focus.finops.org/docs/column-library/) | FOCUS 1.4, current published release | Baseline for standard Cost and Usage columns |
| [FOCUS 1.5 release scope](https://focus.finops.org/focus-1-5-release-scope/) | Working scope as of 2026-09-15; planned December 2026 release | Forward-looking model identity, actor attribution, AI billing examples, and token pricing dimensions |
| [GitHub REST API: Budgets](https://docs.github.com/en/rest/billing/budgets) | API documentation reviewed 2026-09-15 | Source semantics for budget configuration |
| [GitHub REST API: Copilot user management](https://docs.github.com/en/rest/copilot/copilot-user-management) | Public preview reviewed 2026-09-15 | Source semantics for billed seat inventory and activity metadata |
| [GitHub REST API: Copilot usage metrics](https://docs.github.com/en/rest/copilot/copilot-metrics) | API documentation reviewed 2026-09-15 | Organization and enterprise report availability and telemetry semantics |

## FinOps for AI alignment

| Capability | Current implementation | Required evolution |
|---|---|---|
| Understanding Usage and Cost | Seats and telemetry expose adoption and product activity; budgets expose controls. Cost remains separate. | Reconcile GitHub billing usage into a dedicated charge dataset and join analytically, not by duplicating charges. |
| Data Ingestion | JSON/NDJSON is normalized to typed Parquet, landed in Storage, and ingested through ADF into Kusto. | Add source-contract tests, lineage identifiers, reconciliation totals, and explicit data quality status. |
| Allocation | Organization, user, and assigning team are available where provided. | Enterprise user-team reports and governed cost-center mappings are needed for accountable allocation. |
| Reporting and Analytics | Kusto functions expose license summary, utilization, and daily activity. | Label financial, usage, telemetry, adoption, and estimates explicitly on every dashboard. |
| KPI and Benchmarking | Active days, interactions, generations, acceptances, and seat utilization are available. | Establish agreed KPI definitions and denominators; do not call telemetry a financial KPI without a reconciled cost numerator. |
| Unit Economics | Not implemented. | Derive only after authoritative cost and a governed business-output denominator exist. |
| Policy and Governance | Budgets, hard-stop behavior, alerts, pending cancellations, and adoption status are visible. | Add ownership, retention, privacy classification, thresholds, and review workflow. |

## FOCUS 1.4 baseline and candidate columns

FOCUS 1.4 Cost and Usage columns apply to charge records, not to arbitrary configuration or observability rows. The following candidates were explicitly evaluated and rejected for the current datasets.

| FOCUS 1.4 column ID | FOCUS semantic meaning | Type / requirement | Decision for current datasets |
|---|---|---|---|
| `BilledCost` | Amount charged on an invoice after discounts; excludes non-charge configuration and telemetry. | Decimal; mandatory in the Cost and Usage dataset | Unsupported. Budget limits, consumed budget amounts, seat counts, and activity are not invoice charges. |
| `EffectiveCost` | Amortized cost after applying applicable discounts and commitment adjustments. | Decimal; mandatory in the Cost and Usage dataset | Unsupported. No amortization or authoritative effective charge is present. |
| `ListCost` | Cost calculated using public list prices before discounts. | Decimal; conditional | Unsupported. No validated list-price multiplication exists in the current pipeline. |
| `ContractedCost` | Cost calculated using negotiated contract prices before applicable discounts. | Decimal; conditional | Unsupported. Contract rates are not present. |
| `ConsumedQuantity` | Quantity of a resource or service consumed for a charge period. | Decimal; conditional | Deferred. Interaction, generation, acceptance, LOC, and seat inventory metrics are not asserted as the billed meter. A future billing feed may expose premium requests or AI credits as a valid consumed quantity. |
| `ConsumedUnit` | Provider-specified unit corresponding to `ConsumedQuantity`. | String; conditional with consumed quantity | Deferred with `ConsumedQuantity`; the unit must come from the authoritative charge source. |
| `BillingCurrency` | Currency used for billing amounts. | String; mandatory | Unsupported. Currency is not returned by the current budget, seat, or telemetry datasets. |
| `ProviderName` | Entity making the resource or service available for purchase. | String; mandatory | Candidate derived constant `GitHub` only in a future FOCUS charge view, not in the current operational datasets. |
| `ServiceProviderName` | Entity responsible for delivering the service. | String; conditional | Candidate derived constant `GitHub` only after validating the billing relationship. |
| `PublisherName` | Entity that produced or published the purchased product. | String; conditional | Candidate derived constant `GitHub` for Copilot charges, subject to billing-contract review. |
| `ServiceName` | Provider-recognizable name of the service associated with the charge. | String; mandatory | Candidate `GitHub Copilot` only in a future charge view. It is not mapped from activity fields. |
| `SkuId` | Provider-assigned identifier for the SKU associated with the charge. | String; conditional | Deferred. `budget_product_sku` controls a budget and is not necessarily the SKU on a charge. |
| `ChargePeriodStart` / `ChargePeriodEnd` | Inclusive start and exclusive end of the charge aggregation period. | Datetime; mandatory | Unsupported for current rows. Report windows and collection time are not charge periods. |
| `SubAccountId` / `SubAccountName` | Provider-assigned billing subaccount identity. | String; conditional | Deferred. A GitHub organization is not assumed to be a billing subaccount without billing-export evidence. |
| `ResourceId` / `ResourceName` | Provider-assigned identity/name of the resource incurring the charge. | String; conditional | Unsupported. User IDs, budget IDs, and organization IDs are not resources merely because they are identifiers. |
| `Tags` | Provider or user-defined key/value metadata associated with the charge/resource. | JSON map; conditional | Deferred. Team and user dimensions are structured telemetry/allocation fields, not FOCUS tags by default. |

Requirement labels above are design guidance for a future FOCUS Cost and Usage view. Before implementation, the project must revalidate the exact FOCUS 1.4 normative definition, data type, feature level, and applicability in the published specification artifact. The interactive Column Library did not expose all normative details through static retrieval during this review; this limitation is an open validation item, not permission to infer mappings.

## Field-level mapping

Legend:

- **Direct**: source semantics exactly match a FOCUS 1.4 column.
- **Derived**: calculated from source fields with documented semantics.
- **Extension**: provider-specific operational field outside the FOCUS Cost and Usage contract.
- **Deferred**: potentially useful for a future FOCUS or allocation view, but evidence is incomplete.
- **Unsupported**: must not be mapped to the proposed FOCUS column.

### Budget configuration

Source API: `GET /organizations/{org}/settings/billing/budgets`.
Organization availability: yes. Enterprise-level availability: budget scopes may include enterprise, but the current collector calls the organization endpoint and has not validated enterprise-wide completeness.

| GitHub source field | Source definition | Proposed FOCUS 1.4 column | Status and semantic justification | Transformation | Classification | Org / enterprise availability | Validation | FOCUS 1.5 note | Dashboard use / risks |
|---|---|---|---|---|---|---|---|---|---|
| `id` | Identifier corresponding to the budget. | None | Extension as existing `BudgetId`; a budget is not a charge or resource. | String copy. | allocation / governance | Yes / partial scope only | Schema and row-count validated | No identified migration | Drill-through key; do not use as `ResourceId`. |
| `budget_type` | Pricing model controlling interpretation of the product/SKU selector. | None | Extension as `BudgetType`. | Enum copied. | allocation / governance | Yes / partial | Schema validated | SaaS pricing categories may evolve, but 1.5 does not make this a cost row. | Budget segmentation. |
| `budget_product_sku` | Product or SKU covered by the budget. | `SkuId` candidate rejected | Extension as `BudgetProductSku`; budget coverage is not proof of charged SKU identity. | String copy. | allocation / governance | Yes / partial | Schema validated | Future price catalog is confirmed/core; candidate for later reconciliation. | Filter only; risk of confusing product names with billed SKU IDs. |
| `budget_scope` | Scope to which the budget applies. | None | Extension as `BudgetScope`. | Enum copied. | allocation / governance | Yes / partial | Schema validated | Actor/allocation work may inform a future bridge, not a direct mapping. | Scope filter. |
| `budget_amount` | Whole-dollar limit for spend; for license-based products it can represent number of licenses. | `BilledCost`, `EffectiveCost`, `ListCost`: unsupported | Extension as `BudgetAmount`. Its unit is polymorphic and the current source does not emit a currency field. | Decimal(38,9), no rounding beyond exact decimal conversion. Missing not allowed. | allocation / governance | Yes / partial | Type and Parquet validated | Future price catalog does not change budget semantics. | Budget limit. Must label unit context; never label as cost without verified currency/product semantics. |
| `prevent_further_usage` | Whether additional spending is prevented after the budget is exceeded. | None | Extension as `PreventFurtherUsage`. | Boolean copy. | governance | Yes / partial | Schema validated | No identified migration | Hard-stop control. |
| `budget_entity_name` | Name of the entity to which the budget applies. | `SubAccountName`, `ResourceName`: unsupported | Extension as `BudgetEntityName`; entity type depends on scope. | String copy. | allocation | Yes / partial | Schema validated | Actor dimensions may provide a future normalized bridge. | Display label; ambiguous without `BudgetScope`. |
| `budget_alerting.will_alert` | Whether budget alerts are enabled. | None | Extension as `WillAlert`. | Default false only when nested object/field is absent. | governance | Yes / partial | Schema validated | No identified migration | Governance tile. Missing-vs-false default requires team review. |
| `budget_alerting.alert_recipients` | User logins receiving alerts. | None | Extension as `AlertRecipientsJson`. | Compact JSON array; no semantic aggregation. | governance | Yes / partial | JSON serialization validated | Actor dimensions are charge attribution, not alert recipients. | Restricted governance detail; contains user identifiers. |
| `consumed_amount` | Amount reported as consumed against the budget. | `BilledCost` / `EffectiveCost`: unsupported | Extension as `ConsumedAmount`. It is budget progress, not necessarily invoiced or effective cost, and currency/unit may vary. | Decimal(38,9), null preserved, no rounding. | usage quantity or financial budget progress; not authoritative charge | Yes / partial | Type validated; financial reconciliation not performed | Candidate to reconcile with future SKU Price/charge data, not migrate directly. | Budget progress only; risk of double accounting if summed with billing charges. |
| `user` | Login for a user-scoped budget. | None in 1.4 | Extension as `UserLogin`. | String copy; null preserved. | allocation | Yes / partial | Schema validated | Actor/identity dimensions are confirmed/core in 1.5; candidate for future migration after publication. | User allocation; privacy controls required. |
| Collector `organization` | Organization supplied to the API path. | `SubAccountName`: deferred | Extension as `Organization`; billing-account semantics are unverified. | Added from collection manifest. | allocation / lineage | Yes / no enterprise rollup | Collector validated | Future actor/allocation guidance may help. | Global filter; do not assume billing hierarchy. |
| Collector `collected_at_utc`, source path, schema version | Ingestion lineage metadata. | None | Extension; current names are grandfathered. | UTC timestamp and constants. | telemetry / lineage | Yes / yes | Validated | Observability-side identifiers are explicitly not 1.5 scope. | Freshness and troubleshooting. |

### Seat inventory

Source API: `GET /orgs/{org}/copilot/billing/seats`. GitHub describes these as seats for which the organization is currently billed. The endpoint is public preview. It does not return the authoritative monetary charge.
Organization availability: yes. Enterprise-level availability: not through the current endpoint/collector.

| GitHub source field | Source definition | Proposed FOCUS 1.4 column | Status and semantic justification | Transformation | Classification | Org / enterprise availability | Validation | FOCUS 1.5 note | Dashboard use / risks |
|---|---|---|---|---|---|---|---|---|---|
| `total_seats` | Number of current billed Copilot seats in the response. | `ConsumedQuantity`: deferred | Extension as `TotalSeats`; an inventory snapshot is not a charge-period quantity. | Maximum page value; zero retained. | usage quantity / licensing | Yes / no | Zero-seat E2E validated | SaaS commitment work is not confirmed for 1.5; candidate beyond current baseline. | License summary denominator. |
| `assignee.login` | Assigned user's login. | None in 1.4 | Extension as `UserLogin`. | String copy; null preserved. | allocation | Yes / no | E2E validated | Actor/identity is confirmed/core in 1.5; candidate for future migration. | Person-level utilization; personal data. |
| `assignee.id` | Provider-assigned user identifier. | `ResourceId`: unsupported | Extension as `UserId`; a user is not a FOCUS resource. | Int64 copy. | allocation | Yes / no | Schema validated | Actor identity is the relevant 1.5 direction. | Stable join key; avoid exposing unnecessarily. |
| `assignee.type` | GitHub assignee object type. | None | Extension as `AssigneeType`. | String copy. | allocation | Yes / no | Schema validated | Actor identity candidate. | Quality/filter field. |
| `assigning_team.slug/name` | Team through which the seat is assigned. | `Tags`: unsupported | Extension as `AssigningTeam`; a team is an allocation dimension, not automatically a charge tag. | Prefer slug, fallback to name. | allocation | Yes / no | Transformation validated | Shared-cost allocation is core/in flight for 1.5; future bridge candidate. | Team allocation; fallback may create key instability. |
| `pending_cancellation_date` | Date on which pending cancellation takes effect. | None | Extension as `PendingCancellationDate`. | Date currently stored as string; null preserved. | licensing / governance | Yes / no | Schema validated | SaaS contract work largely carries beyond 1.5. | Cancellation risk. Candidate type migration to date. |
| `last_activity_at` | Most recent Copilot activity known for the seat; IDE activity depends on telemetry being enabled. | None | Extension as `LastActivityAt`. | UTC datetime; null preserved. | telemetry | Yes / no | Schema validated | Observability identifiers are not 1.5 scope. | Recency; incomplete when IDE telemetry is disabled. |
| `last_activity_editor` | Editor associated with latest activity. | None | Extension as `LastActivityEditor`. | String copy. | telemetry | Yes / no | Schema validated | No direct 1.5 migration. | Adoption detail; not a billed SKU. |
| `last_authenticated_at` | Most recent authentication timestamp. | None | Extension as `LastAuthenticatedAt`. | UTC datetime; null preserved. | telemetry | Yes / no | Schema validated | No direct 1.5 migration. | Recency/supporting signal. |
| `created_at` | Seat creation timestamp. | `ChargePeriodStart`: unsupported | Extension as `CreatedAt`; seat creation is not charge-period start. | UTC datetime. | licensing | Yes / no | Schema validated | No direct 1.5 migration. | Seat age. |
| `plan_type` | Copilot plan type: business, enterprise, or unknown. | `SkuId` / `ServiceName`: unsupported | Extension as `PlanType`; plan family is not a charged SKU ID. | Enum copied. | licensing | Yes / no | Schema validated | SaaS pricing/commitment work is mostly future. | Plan filter. |
| Derived `RecordType=Snapshot` | Sentinel preserving a successful zero-seat collection. | None | Derived operational extension. | One row per collection; no fabricated user. | telemetry / lineage | Yes / future | Zero-seat E2E validated | No direct migration | Distinguishes zero from missing ingestion. |
| Collector organization/collection/source/schema | Collection scope and lineage. | None | Extensions; no billing hierarchy inferred. | Added from manifest/constants. | allocation / lineage | Yes / future | E2E validated | Observability identifiers not 1.5 scope. | Filtering and freshness. |

### User usage, adoption, and productivity telemetry

Source API: `GET /orgs/{org}/copilot/metrics/reports/users-28-day/latest`; the API returns signed report links. Organization and equivalent enterprise endpoints exist, but the current collector uses the organization endpoint. Metrics require the applicable Copilot usage-metrics policy and can have attribution gaps documented by GitHub.

| GitHub source field | Source definition | Proposed FOCUS 1.4 column | Status and semantic justification | Transformation | Classification | Org / enterprise availability | Validation | FOCUS 1.5 note | Dashboard use / risks |
|---|---|---|---|---|---|---|---|---|---|
| `report_start_day`, `report_end_day` | Bounds of the latest 28-day report. | `ChargePeriodStart/End`: unsupported | Extensions as `ReportStartDay`/`ReportEndDay`; report coverage is not a charge period. | Date parsed as UTC midnight; no rounding. | telemetry / lineage | Yes / equivalent endpoint exists | E2E validated | No direct migration | Report context; end-bound semantics differ from FOCUS exclusive charge end. |
| `day` | Activity day represented by the report row. | `ChargePeriodStart`: unsupported | Extension as `Day`; activity date is not a charge period without a charge record. | Date parsed as UTC midnight. | telemetry | Yes / yes through enterprise report | E2E validated | No direct migration | Time-series axis. |
| `organization_id` | GitHub organization identifier attributed to the row. | `SubAccountId`: deferred | Extension as `OrganizationId`; billing-subaccount equivalence is not established. | Int64 copy. | allocation | Yes / yes | Schema validated | Allocation guidance may enable future bridge. | Stable organization join. |
| `enterprise_id` | GitHub enterprise identifier attributed to the row, when present. | `BillingAccountId`: deferred | Extension as `EnterpriseId`; billing-account equivalence is not established. | Converted to string; missing preserved. | allocation | Possible / yes | Field observed; enterprise completeness not validated | Actor/allocation work may inform future bridge. | Enterprise filter when available. |
| `user_id`, `user_login` | User identity for the activity row. | None in 1.4 | Extensions as `UserId`/`UserLogin`. | Int64/string copy. | allocation | Yes / yes | E2E validated | Actor/identity dimensions confirmed/core in 1.5; migration candidate. | Person-level KPI; privacy and retention review required. |
| `user_initiated_interaction_count` | Count of user-initiated Copilot interactions. | `ConsumedQuantity`: unsupported | Extension as `Interactions`; interaction telemetry is not proven to be the billed meter. | Int64 copy; missing defaults to zero. | telemetry / usage quantity | Yes / yes | E2E validated | AI worked examples may guide a future charge linkage; not a direct migration. | Engagement KPI; source definition/version must be pinned. |
| `code_generation_activity_count` | Count of code-generation activities. | `ConsumedQuantity`: unsupported | Extension as `CodeGenerations`; product activity is not authoritative billed quantity. | Int64 copy; missing defaults to zero. | telemetry / productivity signal | Yes / yes | E2E validated | Model identity could enrich future telemetry but does not convert it to cost. | Generation KPI. |
| `code_acceptance_activity_count` | Count of code-acceptance activities. | `ConsumedQuantity`: unsupported | Extension as `CodeAcceptances`. | Int64 copy; missing defaults to zero. | telemetry / productivity signal | Yes / yes | E2E validated | No direct 1.5 migration. | Acceptance KPI; acceptance is not business value by itself. |
| `loc_suggested_to_add_sum`, `loc_suggested_to_delete_sum` | Lines suggested for addition/deletion. | None | Extensions as `LocSuggestedToAdd`/`LocSuggestedToDelete`. | Int64 sums copied; missing defaults to zero. | productivity signal | Yes / yes | Schema validated | No direct 1.5 migration. | Productivity context; language/tool behavior can bias comparisons. |
| `loc_added_sum`, `loc_deleted_sum` | Lines added/deleted in reported activity. | None | Extensions as `LocAdded`/`LocDeleted`. | Int64 sums copied; missing defaults to zero. | productivity signal | Yes / yes | Schema validated | No direct 1.5 migration. | Productivity context; must not be represented as financial benefit. |
| `used_agent`, `used_chat`, `used_cli`, `used_copilot_cloud_agent`, `used_copilot_coding_agent` | Whether the user used the named Copilot surface during the report period/day. | None | Extensions preserving feature adoption. | Boolean copy; missing defaults to false. | adoption | Yes / yes | Schema validated | Agent actor attribution in 1.5 concerns who drove spend; these booleans remain telemetry. | Adoption segmentation; missing-vs-false behavior requires source-contract review. |
| `ai_adoption_phase` | GitHub-provided adoption phase classification. | None | Extension as `AiAdoptionPhase`. | String copy; null preserved. | adoption | Yes / yes | Field observed; enum contract not pinned | No direct migration | Adoption funnel; provider methodology may change. |
| Derived `ActiveDays` | Distinct activity days where interactions, generations, or acceptances exceed zero. | None | Derived KPI extension. | `dcountif(Day, Interactions > 0 OR CodeGenerations > 0 OR CodeAcceptances > 0)`; unit days; integer; no currency; empty activity yields zero; authoritative only for ingested telemetry window. | telemetry / adoption | Yes / future enterprise | Kusto E2E validated | No direct migration | Activity KPI; does not prove productive outcome. |
| Derived `AcceptanceRate` | Accepted generation activities divided by generation activities. | None | Derived KPI extension. | `CodeAcceptances / CodeGenerations`; ratio; no currency; floating point; zero denominator yields null; telemetry-derived, not authoritative financial value. | productivity signal | Yes / future enterprise | Kusto E2E validated | No direct migration | KPI tile/table; counts may not be one-to-one suggestions. |
| Derived `HasUsage` / `UtilizationStatus` | Current project classification combining telemetry and seat assignment. | None | Derived operational extension. | Usage true when any interaction/generation/acceptance count is positive. Status: Active, Inactive, or Unassigned activity. Missing seat is false; zero-seat snapshot retained. | adoption / licensing | Yes / future enterprise | Zero-seat E2E validated | Actor and allocation work may support a future dimensional model. | License optimization; report-window and seat-snapshot times differ. |
| Derived `UtilizationRate` | Utilized assigned seats divided by total seats. | None | Derived KPI extension. | `UtilizedSeats / TotalSeats`; ratio; no currency; floating point; zero denominator yields null; current snapshot estimate of utilization, not a FOCUS cost metric. | adoption / licensing | Yes / future enterprise | Zero-seat E2E validated | No direct migration | Summary tile; temporal mismatch and telemetry gaps are risks. |

## Derived financial and unit-economic values

No financial or unit-economic value is currently derived. Specifically:

- `BudgetAmount` is not copied to `BilledCost`, `EffectiveCost`, `ListCost`, or `ContractedCost`.
- `ConsumedAmount` is not copied to a FOCUS cost column and must not be added to an authoritative billing total.
- Seat count multiplied by a public price is not implemented. If introduced, it must be named `x_EstimatedSeatCost`, include currency and price-source/version fields, define proration and rounding, and be labeled estimated in code and dashboards.
- Cost per active user, interaction, generation, acceptance, or LOC is not implemented. A future formula must use a reconciled authoritative cost numerator, a documented telemetry denominator over the same period and allocation scope, explicit currency, decimal precision/rounding, and null on missing or zero denominators.

## FOCUS 1.5 migration register

| Concept | 1.5 status reviewed | Current status | Migration note |
|---|---|---|---|
| Model identity and model publisher | Confirmed/core; model identity work is merged | Not implemented; current normalized schema omits `totals_by_language_model` and `totals_by_model_feature` | Candidate for future telemetry extension and, separately, future FOCUS charge mapping after 1.5 publication. Do not infer billed model from product telemetry. |
| AI billing worked examples | Confirmed/core, in review | Not implemented | Use to design the future GitHub billing-to-FOCUS view after publication. |
| Actor and identity dimensions on Cost and Usage | Confirmed/core, in review | User identity exists only as provider-specific telemetry/allocation fields | Candidate migration for charge attribution after publication and privacy review. |
| Shared-cost allocation guidance | Confirmed/core, in review | Team/user joins exist; no cost splitting | Candidate after enterprise user-team data and allocation policy are available. |
| SKU Price dataset | Confirmed/core, in review | No price catalog | Candidate for reconciling list/contracted prices; never reconstruct invoice amounts silently. |
| Cached vs fresh tokens | Champion/stretch, advancing | Not available from current GitHub sources | Not implemented; do not model as a published requirement. |
| Global vs regional serving | Champion/stretch, advancing | Not available | Not implemented. |
| AI committed capacity, context-window pricing, deeper AI/Agentic AI categories | Carries to 1.6 | Not available | Deferred; future migration candidate only. |
| Observability identifiers and token type as first-class columns | Explicitly not 1.5 | Provider telemetry remains extensions | No migration planned under 1.5. |

## Validation rules

1. Reject a proposed direct FOCUS mapping unless the source definition, FOCUS 1.4 definition, type, feature level, applicability, unit, time grain, and null behavior are all compatible.
2. Reject `BilledCost`, `EffectiveCost`, `ListCost`, or `ContractedCost` populated from budgets, seat counts, public-price estimates, or telemetry.
3. Preserve budget, seat, telemetry, adoption, productivity, allocation, lineage, and financial-charge classifications as separate columns/datasets.
4. Reconcile any future FOCUS charge dataset to the authoritative GitHub billing total by billing period and currency before publication.
5. Enforce one authoritative charge lineage key so telemetry joins cannot duplicate cost when expanded by user, team, feature, or day.
6. Label estimates with `x_Estimated...`, price source/version, currency, formula, period, rounding, and missing-data behavior.
7. Preserve successful empty snapshots. A zero-seat snapshot is valid data; a missing ingestion is not zero.
8. Validate organization and enterprise report attribution independently. Do not sum both levels without deduplication rules.
9. Treat signed report downloads and public-preview APIs as versioned external contracts; alert on field additions, removals, and enum changes.
10. Apply privacy and retention controls to user identifiers, team membership, activity timestamps, and alert recipients.

## Conflicts, assumptions, and open questions

| Item | Conflict or ambiguity | Least-destructive decision | Human review required |
|---|---|---|---|
| Existing extension naming | Existing provider fields use PascalCase without `x_`; the requested fallback convention is `x_`. | Preserve working v1.0 schemas. Require `x_` for new extensions and use a versioned migration for renames. | Approve naming policy and migration timing. |
| Budget amount unit | GitHub documents whole dollars generally but licenses for license-based products; current schema has no unit/currency column. | Keep as provider budget field and never aggregate it as money without product/unit context. | Decide whether schema v1.1 should add `x_BudgetUnit` and `x_BudgetCurrency`. |
| Consumed amount semantics | Reported against budget but not documented as invoice/effective/list cost. | Keep separate from FOCUS costs and authoritative billing totals. | Confirm source reconciliation behavior with GitHub billing owners. |
| Organization hierarchy | Organization resembles a subaccount but billing hierarchy is not proven. | Keep `Organization` as allocation/source scope. | Validate enterprise billing-account/subaccount model. |
| Seat billing | API says listed seats are currently billed, but returns no monetary charge period, rate, or currency. | Treat as license inventory only. | Confirm proration and billing feed join keys. |
| Telemetry defaults | Normalizer defaults absent counts/booleans to zero/false. Absence may represent schema drift rather than measured zero. | Preserve current behavior for compatibility and flag source-contract validation. | Decide fail-fast versus default policy for required metrics fields. |
| Temporal alignment | Latest 28-day telemetry and point-in-time seat snapshot do not share identical periods. | Label utilization as snapshot/telemetry-derived and not financial. | Define enterprise KPI period and attribution policy. |
| Enterprise availability | Equivalent enterprise metrics endpoints exist, but current collection is organization-scoped; seats and budgets need separate enterprise validation. | Mark enterprise mappings deferred/partial. | Provide enterprise access and confirm source-of-truth hierarchy. |
| FOCUS normative metadata retrieval | The interactive 1.4 Column Library did not expose all exact definitions/types/feature levels to static retrieval in this review. | No direct FOCUS mappings were implemented; candidate mappings remain deferred. | Validate against the published 1.4 specification artifact before building a FOCUS view. |

## Dashboard labeling requirements

- License tiles: label as seat inventory and telemetry-derived utilization.
- Activity tiles: label as GitHub Copilot telemetry, not billed usage or business value.
- Budget tiles: label as configured limit/progress; include unit context when known.
- Financial tiles: source only from the reconciled authoritative billing dataset and display currency.
- Estimated financial tiles: include `Estimated` in title, formula/source tooltip, currency, as-of time, and separate totals from authoritative cost.
- Do not combine organization and enterprise metrics without an attribution/deduplication rule.
