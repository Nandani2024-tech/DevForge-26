# COMPLEXITY | range WORKTREE on fff7ed4 | 2026-11-27 05:45 | verdict PASS

function (file:line) | R-id | time | space | target | measured | verdict
CSV Pass 1 + Pass 2 (pipeline._harvest_parsed_evidence, _process_csv) | R5,R20 | O(cap*C + R*C): per-column decisions once before the row loop | O(cap*C) | O(bytes) per file; dev < 20 s | 4-col CSV 1k/10k/50k rows: 0.20/1.55/12.46 s (74d4590: 0.21/1.10/8.78 s); linear; previous round 3.38/29.67/146.6 s | meets
resolve_preserve_exact_override (columns.py) | R5 | O(cells) | O(cells) | per column, not per row | call count equal at 50 and 2,000 rows (test_r5_r20_column_decisions_are_made_once_per_column_not_per_row) | meets
classify_csv_columns, csv_slot_priorities, find_non_patient_mrn_cols | R5 | O(min(R,cap)*C) | O(cap*C) | O(bytes) | included above | meets
whole pipeline scale test | R5,R20 | - | - | ratio bounds | 500/2,000/8,000 rows within 1.6x of linear (test_r5_r20_whole_pipeline_csv_scales_linearly) | meets
dev run | R20 | - | - | < 20 s | 2.5 s (check_submission) | meets

Note: 10k rows cost about 1.4x 74d4590; the cProfile shows the extra spread over the normal cleaners (more columns now detected as IDs), no per-row re-vote.
Not verified: peak RSS at 50k rows; collect_list_preserve_overrides runs up to 3x per JSON list (O(cap) each, not measured separately).
