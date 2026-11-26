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

## Open fixes (ranked by estimated points per hour)

| # | fix | category | est. gain | effort | V1 item | status |
|---|---|---|---|---|---|---|
| 1 | Decode, clean and re-encode base64 attachments (9 FHIR bundles with name + UHID + phone; the leaked canary in misc/scanned_consent_form.json) | penalties, privacy A1 | ~+17 | 2-3 h | N4 | OPEN |
| 2 | Catch the remaining nursing/prescription note names (11 full names). Pays off only after #1, because the penalty cap hides it today | penalties, A1, detection | ~+9 | 3 h | N1 | OPEN |
| 3 | Classify columns by value shape as well as header name (fixes ~40% address and 7% MRN leaks on renamed headers) | detection, penalties (unseen data) | ~+5 on hidden data | 3 h | N7 (+R5) | OPEN |
| 4 | Coarser risky fields: drop tehsil and the PIN prefix, DOB to a year band (local test: A4 45/48 -> 30/48 re-identified) | privacy | ~+2.5 net | 2 h | N3 | OPEN |
| 5 | One date shift per true patient: link more records or key the shift on stronger evidence (18 of 48 patients get more than one shift; interval preservation only 0.40) | utility (temporal), identity | ~+1.8 | 4 h | N2 | OPEN |
| 6 | Add the `entities` field to report.json | integrity | ~+0.1 | 10 min | - | OPEN |
| 7 | README with all required sections + model declaration ("no ML models, no LLMs") | checklist items 9-10 | required | 1 h | N8 | OPEN |
| 8 | 2-page Project Brief PDF with measured numbers | checklist item 11 | required | 1-2 h | N8 | OPEN |

## Open doubts (resolve, then mark RESOLVED with the date)

| # | doubt | status |
|---|---|---|
| D-a | check_submission says "PDF found", but the file is the gitignored problem-statement PDF (.hackathon/ps/overview.pdf). Do not trust that line until our own brief exists. | OPEN |
| D-b | Mutated set: 234 of 1,333 date tokens are identical between secrets A and B (dev: 73). Some re-formatted dates (dd-Mon-yyyy, dd.mm.yyyy) may not be shifted, which would expose true visit dates. Unverified which ones. | OPEN |
| D-c | Dev: 73 date tokens stay identical between secrets A and B. Find out which dates are left unshifted and why. | OPEN |
| D-d | Privacy is the least reliable estimate: the local A4 re-identifies 45/48 (raw data 47/48) and may be stronger than the official attacker. The mutated set's privacy number is not comparable (the registry keeps the original names). | OPEN |
| D-e | Memory: 38 MB measured (includes the cmd.exe shell) vs 25.8 MB in report.json. Both far under the limits. | INFO |

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
