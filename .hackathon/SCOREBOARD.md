# SCOREBOARD (estimated official score, newest last)

Purpose: the running record of how our submission scores against the organisers' published rules.
Every row comes from a real run of the tools in `tools/` (see `tools/VERIFY.md`). All scores are
ESTIMATES: the official evaluator and attacker are not public.

How to update: run `/score-check <label>` after every commit. It re-measures, appends one row to the
Progress log, adds a dated entry below, updates the status column of "Open fixes", and flags any
regression. It also appends new issues it finds (as new Open fixes or Open doubts, de-duplicated by
cause) and turns answered doubts into fixes. You or a teammate may add a row to Open fixes / Open
doubts by hand at any time (next number, status OPEN). Never edit old dated entries; a correction
is a new entry.

Reference points (kit README): starter ~8 · delete everything ~20 · organisers' solid firewall ~79 on
practice data, ~50 on an unseen-format dataset.

## Progress log

| date | commit | label | est. dev | est. mutated | leak dev | leak mutated | canaries | F0.5 / wrong merges | medical kept | penalties | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-27 | 6319c85 | baseline after V0 | 56.5 | 51.0 | 1.3% | 7.2% | 1 of 4 | 0.96 / 0 | 100.0% | −28 | BASELINE |
| 2026-11-27 | 74d4590 | after N4 base64 | 73.8 | 53.9 | 0.4% | 6.9% | 0 of 4 | 0.96 / 0 | 100.0% | −11 (mutated −25) | IMPROVED |
| 2026-11-27 | d15a3c6 | after fix 3 column shape | 74.4 | 63.5 | 0.4% | 1.0% | 0 of 4 | 0.96 / 0 | 100.0% | −11 (mutated −19) | IMPROVED |

## Open fixes (ranked by estimated points per hour)

| # | fix | category | est. gain | effort | V1 item | status |
|---|---|---|---|---|---|---|
| 2 | Catch the remaining nursing/prescription note names (11 full names). Pays off only after #1, because the penalty cap hides it today | penalties, A1, detection | ~+9 | 3 h | N1 | OPEN (2026-11-27 d15a3c6: dev 11 full names (notes 10, prescriptions 1); mutated 19 incl. 7 inside FHIR base64, see D-f) |
| 4 | Coarser risky fields: drop tehsil and the PIN prefix, DOB to a year band (local test: A4 45/48 -> 30/48 re-identified) | privacy | ~+2.5 net | 2 h | N3 | OPEN |
| 6 | Add the `entities` field to report.json | integrity | ~+0.1 | 10 min | - | OPEN (report_quality still 0.917) |
| 9 | Hospital-ward preserve rule keeps a municipal 'Ward <n>' written as an address locality in discharge text (LOCALITY 2/103 dev, both this cause) | detection, privacy | small | 1 h | new | OPEN |
| 5 | One date shift per true patient: link more records or key the shift on stronger evidence (18 of 48 patients get more than one shift; interval preservation only 0.40) | utility (temporal), identity | ~+1.8 | 4 h | N2 | OPEN |
| 7 | README with all required sections + model declaration ("no ML models, no LLMs") | checklist items 9-10 | required | 1 h | N8 | OPEN |
| 8 | 2-page Project Brief PDF with measured numbers | checklist item 11 | required | 1-2 h | N8 | OPEN |

## Resolved fixes

| # | issue | how it was fixed | commit | evidence | date |
|---|---|---|---|---|---|
| 3 | Renamed headers and keys hid PII: a recognised but weak header word (or an unknown one) skipped the value check, so renamed ID and address columns were kept as they were | D12-D14: a capped per-column vote over value shape, address cues, age shape and run-time name evidence; an ID-shaped column overrides a facility-style header when its values are non-medical and high-cardinality, decided once per column/key (tie at half -> ID); no new word lists. Commit: feat(R5,R8): classify columns by value shape when headers are renamed | d15a3c6 | mutated: MRN 54 -> 0, HOUSE 54 -> 0, LOCALITY 36 -> 0 (registration), LANDMARK 26 -> 0; leak 6.9% -> 1.0%; estimate 53.9 -> 63.5 (dev 73.8 -> 74.4) | 2026-11-27 |
| 1 | Base64 payloads (FHIR attachment data, base64 form fields) were never decoded, so names, UHIDs and phones inside them leaked, including one canary | D11: explicit base64 (FHIR Attachment, data: URIs) is decoded, cleaned by the same text and JSON cleaners plus run-time name evidence, and re-encoded in its own variant; a guessed decode runs only after normal cleaning, so it can only add redactions. Vocab lock and redaction invariant tests added as guardrails (368a08c). Commit: feat(R9,R4,R8): decode, clean and re-encode base64 attachments | 74d4590 | base64 channel 100% -> 0.0%; canaries 1 -> 0 of 4; dev estimate 56.5 -> 73.8 | 2026-11-27 |

## Open doubts (resolve, then mark RESOLVED with the date)

| # | doubt | status |
|---|---|---|
| D-a | check_submission says "PDF found", but the file is the gitignored problem-statement PDF (.hackathon/ps/overview.pdf). Do not trust that line until our own brief exists. | OPEN |
| D-c | Dev: 73 date tokens stay identical between secrets A and B. Find out which dates are left unshifted and why. | OPEN (2026-11-27 d15a3c6: 70 of 1,333 equal on dev; mutated also 70, so the rest is not format-related) |
| D-d | Privacy is the least reliable estimate: the local A4 re-identifies 45/48 (raw data 47/48) and may be stronger than the official attacker. The mutated set's privacy number is not comparable (the registry keeps the original names). | OPEN |
| D-e | Memory: 38 MB measured (includes the cmd.exe shell) vs 25.8 MB in report.json. Both far under the limits. | INFO |
| D-f | Mutated base64 channel leaks 70% (7 FHIR attachment names) while dev is 0%. tools/mutate_dev.py leaves base64 payloads with their original names but renames them elsewhere, so run-time name evidence cannot match: likely a tool artefact. Confirm by letting mutate_dev rewrite names inside base64 (tool change, own task) and re-measuring. | OPEN |
| D-g | Mutated set: RELATIVE_NAME leaks 14 times in lab files vs about 1 on dev. Cause unknown (renamed keys or invented-name shapes). Confirm by grouping those leaks by key path. | OPEN |
| D-h | Dev privacy: the local A5 attacker reports a recovered global shift (−47) and 1 decoy claim on our output; unclear whether shifts are recoverable for unlinked records. Confirm from out_score/dev/estimate.json A5 details. | OPEN (2026-11-27 d15a3c6: A5 recovers a global shift of −29 on dev, −62 on mutated; decoy claims 0) |

## Resolved doubts

| doubt | answer | evidence | date |
|---|---|---|---|
| D-b: re-formatted dates (dd-Mon-yyyy, dd.mm.yyyy) on the mutated set left unshifted? | yes for dd.mm.yyyy: the 4-digit-year date pattern did not accept '.', fixed in d15a3c6 (date separators [-/.]) | mutated date tokens equal between secrets A and B: 234 -> 70 of 1,333 (dev level, 70) | 2026-11-27 |

---

## 2026-11-27 · 6319c85 · baseline after V0

Run by Claude with the measurement tools (no code, tests, config or raksha.toml changed). New files:
`tools/rehearse_eval.py`, `tools/estimate_score.py`, `tools/mutate_dev.py`, `tools/sw_common.py`,
`tools/VERIFY.md`.

### Checklist (kit START_HERE section 8)

| # | item | evidence | verdict |
|---|---|---|---|
| 1 | check_submission --run | READY TO SUBMIT (1 warning: README 62 words) | PASS (1 warning) |
| 2 | raksha.toml at the root | name Procrastinators; setup `pip install -r requirements.txt`; run `python main.py --input {input} --output {output}` | PASS |
| 3 | setup installs everything; run needs no internet | fresh clone of 6319c85, .venv + setup in 16.3 s, exit 0, installs only psutil==7.2.2; no network imports or calls in main.py or wards/ | PASS; Wi-Fi-off run NEEDS USER |
| 4 | validate_output | CONTRACT OK | PASS |
| 5 | same secret -> identical; different secret -> different | A vs A: 194/194 files and records.jsonl byte-identical. A vs B: 0/681 records keep the same pseudonym, 0/1,259 shifted dates land on the same value | PASS |
| 6 | nothing personal in stdout, stderr, logs, temp files or report | 0 hits in all 7 side channels (scanner finds 1,099 lines in raw input, so it is not blind) | PASS |
| 7 | secret never written | 0 hits (UTF-8 and UTF-16, contents and file names) | PASS |
| 8 | time and memory | 2.3 s wall, 38 MB peak tree RSS vs 60 s / 512 MB and 900 s / 4 GB | PASS |
| 9 | no LLM or large model | runtime needs psutil only (pytest for tests); README does not yet state "no models" | PASS on deps; README line NEEDS USER |
| 10 | README sections | 62 words, only Setup/Run/Test headings | FAIL / NEEDS USER |
| 11 | 2-page Brief PDF | none in the repo (see doubt D-a) | FAIL / NEEDS USER |
| 12 | data we didn't tune on | header/key renames and invented names exact; date-format changes approximate. Leak 1.3% -> 7.2%, linking unchanged (F0.5 0.96), estimate 56.5 -> 51.0 | PASS (ran); shows weak spots |

Other results: pytest 84 passed (installed pytest 9.0.2 vs pin 9.2.0).

### check_dev on dev/input

- 41 of 3,230 pieces leaked (1.3%): PATIENT_NAME 29, MRN 9, LOCALITY 2, PHONE 1.
- By hiding place: base64 channel leaks 100%; content 1.0%; filename, metadata, key, header 0%.
- By language: latin 1.4%, Hindi 0.0%, Hinglish 0.0%.
- Canaries: 1 of 4. Medical values kept: 4,854 of 4,855 (100.0%).
- Linking: precision 1.00, recall 0.84, F0.5 0.96, 0 wrong merges. Raw copies: 0.

### check_dev on the mutated set (unseen-data proxy)

| type | leaked |
|---|---|
| HOUSE | 39.7% |
| LOCALITY | 36.9% |
| LANDMARK | 40.6% |
| MRN | 7.4% |
| Hinglish names | 12.6% |

Not testable on Windows: network namespace, tmpfs masks, CPU affinity, hidden /proc
(tools/VERIFY.md has the WSL / GitHub Actions commands for each).

### Score estimate (all estimates)

| category | max | estimate | confidence | not computed exactly |
|---|---|---|---|---|
| Privacy | 25 | 13.6 | low | A1-A7 re-implemented from ATTACKS.md; name matching, profile joining and raw baseline are our interpretation; transliteration uses our own function. A4 re-identifies 45/48 (raw 47/48) vs 16.7% for their reference: our attacker may be stronger. |
| Detection | 20 | 19.8 | medium | leak counting follows SCORING.md; trap groups mapped from truth "preserve" kinds; precision 1.0 probably optimistic |
| Utility | 20 | 18.0 | medium | dates matched by order within each record; free-text age fields not scored; lab medians approximated |
| Identity | 15 | 13.3 | high | matches check_dev (P 1.00 / R 0.84 / F0.5 0.96); trap sets from truth.json |
| Integrity | 10 | 9.9 | medium | FHIR check is our own structural validator |
| Performance | 10 | 10.0 | high | timed on Windows; 2.3 s vs 15 s good-time on the "small" profile |
| Penalties | - | −28 | medium-high | leaked IDs and names hit the 25-point cap (18 IDs + 18 full names = 36); 1 canary −3 |
| **Total** | 100 | **56.5** (mutated **51.0**) | | most of the gap to 79 is the −28 penalties |

Scorer bugs fixed during this run (numbers above are after the fixes): document-level JSON fields
not looked up; Devanagari gender/district values counted as lost; the attacker invented a −1-day
global shift on raw data.

Logged: 2 lines in MISTAKES.md (renamed-header leaks; date intervals). Note appended to PROGRESS.md.

---

## 2026-11-27 · 74d4590 · after N4 base64

Measured with tools/rehearse_eval.py (clone of the local repo at 74d4590; origin/main is one
commit behind), tools/mutate_dev.py, kit check_dev.py and tools/estimate_score.py. Outputs in
out_score/. Tree clean apart from .hackathon/.

### Score estimate (all estimates)

| category | max | dev estimate | change vs 6319c85 | mutated estimate |
|---|---|---|---|---|
| Privacy | 25 | 13.73 | +0.17 | 9.30 |
| Detection | 20 | 19.93 | +0.18 | 18.90 |
| Utility | 20 | 17.94 | −0.01 | 17.51 |
| Identity | 15 | 13.31 | 0.00 | 13.29 |
| Integrity | 10 | 9.91 | 0.00 | 9.91 |
| Performance | 10 | 10.00 | 0.00 | 10.00 |
| Penalties | - | −11.00 | +17.00 | −25.00 (cap) |
| **Total** | 100 | **73.81** | **+17.33** | **53.91** (was 50.98, +2.93) |

Mutated per-category numbers were not recorded for 6319c85, so only its total is compared.

### Dev (check_dev)
- 13 of 3,230 pieces leaked (0.4%): PATIENT_NAME 11, LOCALITY 2; every other type 0%.
- By hiding place: content 0.4%; filename, base64, metadata, key, header 0.0%. Latin 0.4%, Hindi 0.0%, Hinglish 0.0%.
- Canaries 0 of 4. Medical kept 4,854 of 4,855. Precision 1.00, recall 0.84, F0.5 0.96, 0 wrong merges. Raw copies 0.
- CONTRACT OK; READY TO CONNECT: yes (all rehearsal checks PASS, 4 not testable on Windows).
- Run A1 2.66 s, peak 37.9 MB; A vs B: 0 of 681 pseudonyms equal; 75 of 1,333 date tokens equal.
- Penalties: 0 unique leaked IDs, 11 full names, 0 canaries.

### Mutated (check_dev)
- 222 of 3,230 leaked (6.9%, was 7.2%): HOUSE 39.7%, LANDMARK 40.6%, LOCALITY 36.9%, MRN 6.4% (was 7.4%), RELATIVE_NAME 6.0%, PATIENT_NAME 3.5%.
- By hiding place: content 6.9%, base64 70.0% (see D-f), others 0%. Hinglish 12.6%.
- By folder: registration carries MRN 54, HOUSE 54, LOCALITY 36, LANDMARK 26, names 17 (fix #3); lab RELATIVE_NAME 14 (D-g); notes names 10 (fix #2); FHIR base64 names 7 (D-f).
- 234 of 1,333 date tokens equal between secrets A and B (unchanged).

Regressions: none.
Fixed: #1 base64 payloads never decoded, so their names, IDs and one canary leaked -> decode, clean and re-encode explicit base64; a guessed decode only after normal cleaning (D11) (74d4590, base64 channel 100% -> 0.0%, canaries 1 -> 0, estimate 56.5 -> 73.8)
New issues added: fix #9; doubts D-f, D-g, D-h.
Not measured: official evaluator and attacker; Linux and Python 3.10/3.12; network-off run.

---

## 2026-11-27 · d15a3c6 · after fix 3 column shape

Measured with tools/rehearse_eval.py (clone of the local repo at d15a3c6; origin is behind),
tools/mutate_dev.py, kit validate_output.py and check_dev.py, and tools/estimate_score.py.
Outputs in out_score/. Tree clean apart from .hackathon/.

### Score estimate (all estimates)

| category | max | dev estimate | change vs 74d4590 | mutated estimate | change vs 74d4590 |
|---|---|---|---|---|---|
| Privacy | 25 | 14.28 | +0.55 | 11.81 | +2.51 |
| Detection | 20 | 19.93 | 0.00 | 19.55 | +0.65 |
| Utility | 20 | 17.96 | +0.02 | 17.92 | +0.41 |
| Identity | 15 | 13.31 | 0.00 | 13.31 | +0.02 |
| Integrity | 10 | 9.91 | 0.00 | 9.91 | 0.00 |
| Performance | 10 | 10.00 | 0.00 | 10.00 | 0.00 |
| Penalties | - | −11.00 | 0.00 | −19.00 | +6.00 |
| **Total** | 100 | **74.39** | **+0.58** | **63.49** | **+9.58** |

### Dev (check_dev)
- 13 of 3,230 leaked (0.4%): PATIENT_NAME 11 (notes 10, prescriptions 1), LOCALITY 2 (discharge); every other type 0%.
- By hiding place: content 0.4%, all others 0.0%. Latin 0.4%, Hindi 0.0%, Hinglish 0.0%.
- Canaries 0 of 4. Medical kept 4,854 of 4,855. Precision 1.00, recall 0.84, F0.5 0.96, 0 wrong merges. Raw copies 0. CONTRACT OK; READY TO CONNECT: yes.
- Run A1 2.99 s, peak 38.6 MB (report.json: 2.42 s, 25.9 MB). Determinism 194/194 files identical. A vs B: 0 of 681 pseudonyms equal; 70 of 1,333 date tokens equal.
- Penalties: 0 unique leaked IDs, 11 full names, 0 canaries.

### Mutated (check_dev)
- 33 of 3,230 leaked (1.0%, was 6.9%). Worst types: RELATIVE_NAME 6.0% (14, lab, Hinglish, D-g), LOCALITY 1.9% (2, discharge, fix #9), PATIENT_NAME 1.8% (17: notes 10, fix #2; FHIR base64 7, D-f); MRN, HOUSE, LANDMARK, AADHAAR, DOB 0.0%.
- By hiding place: content 0.8%, base64 70.0% (D-f), others 0%. Hinglish 12.6%.
- Registration leaks (MRN 54, HOUSE 54, LOCALITY 36, LANDMARK 26 at 74d4590) are all 0.
- A vs B: 70 of 1,333 date tokens equal (was 234).

Regressions: none.
Fixed: #3 renamed headers and keys hid PII -> per-column value-shape vote and cardinality-gated ID override, decided once per column/key, no new word lists (D12-D14) (d15a3c6, mutated leak 6.9% -> 1.0%, estimate 53.9 -> 63.5)
Resolved: D-b re-formatted dates unshifted on the mutated set -> yes for dd.mm.yyyy, fixed by the [-/.] date separator in d15a3c6 (234 -> 70 equal date tokens)
New issues added: none (every leak above 0% maps to fix #2, #9 or doubts D-f, D-g; the 10k-row CSV slowdown in COMPLEXITY.md does not affect the small-profile performance score).
Not measured: official evaluator and attacker; Linux and Python 3.10/3.12; network-off run.
