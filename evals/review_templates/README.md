# Agent outputs → human reference labels → LLM judge evaluation

These are empty UTF-8 BOM CSV templates. **No responses, human judgments, judge results or scores have been invented.** This is separate from Golden Dataset V1, which continues to specify desired behavior before execution.

## Workflow and files

1. After agents are implemented and tested, run chosen queries and capture each orchestrator/specialist response in `agent_responses.csv`. Use a unique `response_id` for every response/repetition, even for the same case. Preserve the query, authorized context, actual retrieved passages/tool results, model/prompt versions, as-of clock and exact output artifact. New exploratory queries need a stable case ID and reviewed task description; do not label them as existing golden cases.
2. Review outputs independently using `human_reviews.csv`: one row per reviewer, response and criterion. Use pass/fail/inconclusive/not_applicable, a reason, supporting evidence and severity. Optional numerical scores require an explicit scale. Reviewers should not see the judge's score first.
3. Resolve disagreements into `adjudicated_labels.csv`: one active label per response + criterion + rubric/label version. Preserve original reviews and supersession links. A single reviewer can approve an undisputed label; record the same reviewer as adjudicator rather than inventing a second reviewer. A rubric change requires re-review or a documented label migration. Freeze reviewed labels before using them as judge ground truth.
4. Run the LLM judge on the **same response and evidence**, using the task, applicable rubric and expected task behavior. Record each response/criterion/repetition in `judge_evaluations.csv`. Do not provide human response labels, scores, reasons or adjudications to the judge during independent scoring. Errors are execution errors, not a pass/fail label.
5. Use `item_labels.csv` when measuring item-level task quality: separate human-reference annotations from agent-output or judge-output annotations. Predeclare the item universe and matching rules. Use stable activity/date pairs, offer IDs, passage IDs or required-field IDs; do not count arbitrary prose sentences as interchangeable items.
6. Calculate `metric_summaries.csv` from version-pinned inputs. Report judge reliability against human labels separately from agent performance against task labels. Save confusion counts, exclusions, coverage and denominators alongside ratios.

`schema.json` supplies ordered columns and enum values. The templates are a data contract; automated collection, adjudication UI, judge runner and metric calculator are future implementation work.

## Storage and keys

Copy templates to `data/runtime/evals/<run_id>/` for actual response/evidence/log collection. Keep sensitive live content and raw provider payloads out of Git. A sanitized reviewed benchmark may later be published as a versioned artifact under `evals/versions/`; this requires explicit review of provenance and privacy. None of these artifacts belongs in destination Chroma.

Use UTC ISO timestamps, decimal monetary strings, ISO currency codes, integer token counts/milliseconds, and opaque IDs. Blank means not supplied/unavailable, never zero. Ref fields point to immutable local artifacts or authorized trace locations; semicolon-separated IDs are sufficient for review cells, with authoritative arrays in companion artifacts if needed.

- `response_sha256`: SHA-256 of exact UTF-8 model-visible output text bytes (or the agreed authoritative output artifact bytes). Choose one canonical representation in the run manifest and keep it consistent; preserve redacted display copies separately.
- `evidence_sha256`: hash of the exact immutable evidence bundle shown during review/judging, including fixture/provider mode and dates. Redact secrets before creating the canonical bundle. If output itself contains a secret, quarantine it and use a redacted review artifact; bind labels to that artifact and record the redaction without publishing the secret.
- Each review/label/judge row must resolve to the same response and evidence hashes. A modified answer or changed evidence requires a new response version and review; do not silently reuse old labels.
- `criterion_id` references a versioned rubric. `reference_label` records human-adjudicated judgment of that response on that criterion, not the expected answer to every future query.
- `response_status` describes the agent outcome (complete/partial/clarification/error); it does not determine evaluation pass/fail. Correct clarification can pass.
- `supporting_evidence_ids` must resolve to the captured bundle; unsupported labels remain inconclusive until reviewed.
- `review_status` tracks reviewer submissions; `label_status=frozen` identifies eligible judge-reference labels. Draft labels cannot be reported as authoritative ground truth.
- `scenario_family_id` groups related outputs across repetitions, paraphrases and agent versions so calibration and held-out cases do not leak into each other.
- `item_universe_ref` defines all gradeable items, including expected items missing from an agent answer. Human reference and predictions must use this same universe. Rank is 1-based for retrieval results; `k` defines the cutoff.

## Reusing human ground truth correctly

A frozen collection of reviewed outputs is a reusable **judge benchmark**. Each new judge model/prompt can score those same outputs again and be compared with the frozen human labels. Calibration examples may be shown to the judge; label them calibration and keep them outside independent judge-holdout measurements.

When an agent changes and produces a new response, its old response-level human label does not transfer automatically. Re-review the new output to measure judge reliability on it. A calibrated judge may score new outputs for monitoring, but those are judge-estimated agent scores, not newly human-validated precision/recall. Continue independent human sampling, especially for disagreements and critical failures. Repeatedly tuned holdout cases become regression coverage and need replacement.

## Metric definitions

### Judge reliability

Default positive class is **failure**. For eligible frozen human pass/fail labels:

- TP: human fail, judge fail.
- FP: human pass, judge fail.
- FN: human fail, judge pass.
- TN: human pass, judge pass.

Precision = TP/(TP+FP); recall = TP/(TP+FN); F1 = 2TP/(2TP+FP+FN); accuracy/agreement for this binary slice = (TP+TN)/(TP+FP+FN+TN).

Compute binary confusion counts only when both judgments are binary. Report judge inconclusive/not_applicable on a human-eligible row as an abstention, and execution errors separately; never silently treat either as correct. Human-inconclusive, non-applicable and unreviewed rows are separately excluded from binary reference counts. `required_count` is the human-binary eligible population; `scored_count` is TP+FP+FN+TN. `coverage=scored_count/required_count`. Publish failure-detection coverage across *all* human failures as an additional named metric when abstentions occur; binary recall alone can hide unjudged failures. Unsupported N/A judgments must not evade critical failure reporting.

### Agent task quality

Use task-specific human labels instead of human pass/fail labels for the judge:

- Weather: positive is an expected conflict for an activity/date. Grade unknown coverage as a separate class; never collapse unknown into safe. Report confusion for known binary cases plus unknown-state accuracy and coverage.
- Pricing: compare eligible offer IDs within a fixed candidate universe. A shortlist of one or two may intentionally omit eligible options; report shortlist precision and selection-constraint success, and do not impose full eligible-set recall unless the task asks for exhaustive enumeration.
- Orchestrator: expected missing-field IDs or required decisions can be compared with returned fields/decisions. Arithmetic stays deterministic.
- Retrieval: precision@k is relevant retrieved items divided by k, with fewer than k returned items counted as empty slots; recall@k is retrieved relevant items divided by all labeled relevant items in the frozen candidate corpus. State the candidate pool and deduplicate IDs. No-relevant-item cases use abstention metrics, not fabricated recall values. Also report retrieved count.
- Itinerary usefulness/clarity/pace: use anchored rubric means and distributions; do not convert 1–5 scores into precision/recall without a separately reviewed binary definition.

A metric row must declare `evaluation_target`, item type, positive class, population, split, agent, criterion and aggregation. Micro metrics sum confusion counts across comparable decisions; macro metrics average per-task/class metrics and explicitly report how undefined classes are treated. Do not average incompatible retrieval, weather and judge metrics into one F1. Store these as separate rows; extended named metrics may live in a companion report rather than repurposing columns.

Undefined divisions produce blank/null plus an entry in `undefined_metrics`, never automatic 0 or 1. A zero numerator with a positive denominator is correctly zero. For micro F1 use the direct count formula above, which is defined when 2TP+FP+FN > 0 even if precision is undefined. Ordinal human/judge agreement can additionally use weighted kappa or score error in a companion report; binary agreement alone does not establish calibrated quality.

Keep critical deterministic failures visible regardless of judge scores. Aggregate by agent/criterion and declared repetition protocol; report every stochastic run, not the best run. No metric is computed until enough actual labeled observations exist; sample size and uncertainty limit reliability claims.

## Implementation validation to add later

Reject duplicate IDs, missing foreign keys, hash mismatches, unknown criteria, incompatible rubric versions, multiple active adjudications, out-of-range scores, incomplete evidence and calibration/holdout leakage. Require empty judge-label fields on failed executions. Metric tests should cover perfect/inverted classifiers, all-positive/all-negative references, zero denominators, abstentions/errors, unknown weather, retrieval with fewer than k results, repeated outputs and changed-response hashes. Never pass answer-key labels to the agent or held-out human verdicts to the judge.
