# hardcode-check | WORKTREE @ 1f885cf | 2026-11-26 22:01 | verdict WARN
id | file:line | check | snippet | why | root-cause fix | severity
H6 | wards/pipeline.py:1024,1032 | G | `{"dmy": own[0], "mdy": own[1]}`, `fam["dmy"]` | date-order names inlined instead of dates.DATE_ORDER_DMY / DATE_ORDER_MDY (MISTAKES line 32, seen 5) | key the family Counter by the DATE_ORDER_* constants | WARN
Fixed since 1f885cf: slots name words now columns.NAME_KEY_TOKENS; names.py protect regex reuses patterns.PROTECTED_TOKEN_RE.
No A-F or K findings: no fake data, fallbacks to success, dev-value branches or broad excepts; allowlist and guard tests untouched; new acceptance test fails (never skips) without the kit; it reads truth.json only to measure.
Not verified: word literals beyond the R22 ratchet.
