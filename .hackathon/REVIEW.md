# REVIEW (hardcode-check) | range WORKTREE on fff7ed4 | 2026-11-27 05:45 | verdict WARN

id | file:line | check | snippet | why | root-cause fix | severity
H1 | wards/slots.py csv_slot_priorities, wards/pipeline.py:618, wards/columns.py classify_csv_columns | H | `[row[i].strip() for row in sampled ... if i < len(row) and row[i].strip()]` | the capped column sample is built separately in 3 places | one helper (e.g. columns.sample_column_values) computed once per file and passed to each decision | WARN

Resolved since the last review: per-leaf single-value votes removed (decided once per key/column, COLUMN_ID_MIN_VALUES); inline "PIN" comparison, slot priorities 0/2 and "MRN" replaced by include_pin / SLOT_PRIORITY_* / PRIMARY_ID_TYPE; "div" special case removed; _FAST_PROTECT_RE restored unchanged (reviewed words keep their owner); HOSPITAL_ID_ISSUER_WORDS and HOUSE_ABBR_WORDS gone (D13). No new word lists; tests/vocab_lock.json, tests/r22_vocab_allowlist.txt and the R22 guard tests unchanged; no new dependencies.
Fixture edits made in review (user-approved): invented name replaces a dev name; MRN-shaped mixed-column value expected redacted; JSON facility fixture extended to the CSV's 6 rows; new tie-break test.
Not verified: Python 3.10/3.12; the sample cap (first 200 rows) on files whose PII starts later.
