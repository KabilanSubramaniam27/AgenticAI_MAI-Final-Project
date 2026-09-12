# TripRadar Golden Dataset V1

**Version: 1.0-draft — pending user review; agents have not been evaluated.**

There are **80 unique scenarios: 20 per agent**. All scenarios are AI-authored synthetic drafts. Four archived Wikivoyage passages are included as real source evidence for selected itinerary cases. No scenario represents observed production behavior, a current travel quote, or a real forecast.

## Files

| Review file | Cases |
| --- | ---: |
| [Golden_Dataset_V1.csv](Golden_Dataset_V1.csv) — canonical combined answer key | 80 |
| [Golden_Dataset_V1_Orchestrator.csv](Golden_Dataset_V1_Orchestrator.csv) | 20 |
| [Golden_Dataset_V1_Itinerary_Builder.csv](Golden_Dataset_V1_Itinerary_Builder.csv) | 20 |
| [Golden_Dataset_V1_Price_Watcher.csv](Golden_Dataset_V1_Price_Watcher.csv) | 20 |
| [Golden_Dataset_V1_Weather_Risk.csv](Golden_Dataset_V1_Weather_Risk.csv) | 20 |

The per-agent files are exact filtered views of the master, not additional cases. Review either view, then reconcile accepted edits into the master and regenerate the filtered views before freezing; do not maintain conflicting answer keys. CSV files use UTF-8 BOM for Excel and contain exactly the six requested fields:

1. `scenario`: stable ID and scenario name.
2. `user_input`: task or user request.
3. `expected_behavior`: required observable outcome.
4. `success_criteria`: measurable acceptance conditions.
5. `tools_context`: supplied evidence, constraints, fixed clock and synthetic fixture facts.
6. `failure_edge_cases`: unacceptable behavior and relevant edge conditions.

`Golden_Dataset_V1_case_details.json` records agent ownership, provenance, review/execution status, and candidate requirement links separately from the six-column sheet. These links identify applicable requirement families; review case-level coverage before the answer-key freeze. `Golden_Dataset_V1_manifest.json` records counts, format, version, scope and artifact checksums.

## How to review and use the cases

- Each row is one V1 task/outcome case. Do not require a specific internal graph, tool-call sequence or exact final wording; V2 will add intermediate trace assertions.
- Read `tools_context` as fixture setup. Explicit row overrides supersede that row's default trip/forecast fields. No unrelated facts from other rows should be assumed.
- Pricing fixtures cover the specified flight/hotel scope, not automatically the full trip budget. Orchestrator ledger cases explicitly list amounts and included categories.
- Destination dates are inclusive; hotel checkout is exclusive. October 10–19 means ten destination dates and nine hotel nights. Prices marked total-for-stay or total-for-group must not be multiplied again.
- `delta = budget - total`. Unknown required costs yield null complete total/delta and unknown fit, unless a known lower bound already establishes over-budget. Test data and accepted allowances must remain labeled.
- Weather defaults use a fixed October 9 clock so the October 10 forecast is within the supplied fixture window. Horizon/staleness cases override the clock/coverage explicitly. Unknown weather is not safe weather. The 60% rain threshold and case-specific heat threshold are proposed planning policies requiring review, not official weather warnings.
- For manual grading, all mandatory acceptance conditions must hold. A correct clarification, abstention or partial answer can pass. Record candidate answers and execution scores separately from these files.
- Structured inputs for all 80 cases are now linked through `fixtures/index.json` and the companion case metadata. See [fixture documentation](fixtures/README.md). Fixtures and offline integrity checks are available; an agent evaluation runner and live provider contract tests are not implemented. The CSV alone is not an executable agent baseline.
- No model calls, live travel APIs, agent implementation, or agent evaluation were run to create this dataset. Structural checks do not establish label quality or agent accuracy.

## Guide evidence and attribution

[fixtures/guides/passages.json](fixtures/guides/passages.json) preserves exact text of four chunks from the existing local published Chroma collection, with chunk IDs, revision URLs, source timestamps, attribution, license, and a text SHA-256 checksum. `G-LIS`, `G-PAR`, `G-LON`, and `G-NYC` are convenient fixture aliases; final references should resolve to the actual chunk/revision records. Local machine paths were omitted; passage text was not modified by this export.

The source is English Wikivoyage, by Wikivoyage contributors, licensed [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Each record retains its page, revision/history and license links plus the existing ingestion modification notice. Review attribution and share-alike obligations when redistributing adaptations. Archived facts do not prove present-day prices, opening hours, accessibility, service availability, or safety.

Other `G-*`, `F-*`, hotel and activity identifiers appearing with explicitly synthetic facts are fictional test identifiers, not real provider IDs or Wikivoyage citations. Do not publish them as real destination recommendations. The small real passage set supports focused evidence-consumption tests; it is not enough to measure full corpus retrieval recall or ten-day itinerary usefulness.

## Coverage and review status

The four suites cover clarification, constrained planning, grounding, wrong-city/irrelevant evidence, occupancy/tax arithmetic, quote eligibility, forecast boundaries, missing data, date corrections, service failures and injected instructions.

This requested delivery covers four agent suites only. The implementation plan's additional 20 separate end-to-end scenarios remain future work. Cases have no assigned split and no frozen labels. Since this review pool is visible, it is not a protected release holdout; collect independent unseen cases for a release test. Keep related numerical boundary variants and paraphrases together when assigning development/calibration splits.

Before freezing V1, review every label and policy, add missing realistic inputs and full runner fixtures, record reviewers and decisions, verify coverage against the implementation plan, and snapshot the accepted version. Do not change correct labels just to fit observed model output. Dataset changes require a new version and regenerated checksums; preserve prior snapshots and run results.
