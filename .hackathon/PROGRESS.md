# PROGRESS
base: d15a3c6

R-id | priority | status | evidence
R1 | MUST | done-verified | validate_output CONTRACT OK, 0 WARN (test_kit_contract)
R2 | MUST | done-verified | check_dev RAW COPIES 0; exit 0; quarantine edge tests
R3 | MUST | done-verified | row/column/key-path/line diff vs input = 0 except PII-only renames (test_kit_contract)
R5 | MUST | done-verified | @ d15a3c6: dev PATIENT_NAME 1.1%, PHONE/MRN/AADHAAR/DOB/VILLAGE/PIN 0.0%; renamed-header set (tools/mutate_dev.py) PATIENT_NAME 1.8%, MRN/AADHAAR/DOB/PHONE/VILLAGE/PIN 0.0% (all <= 2%)
R6 | MUST | done-verified | check_dev @ 74d4590: every R6 type 0.0% (PHONE 0/308, MRN 0/850); medical kept 4854/4855; generated-ID invariants 12/12 (tests/test_redaction_invariants.py)
R7 | MUST | done-verified | check_dev @ 74d4590: latin 0.4%, deva 0.0%, hinglish 0.0%; CANARIES 0 of 4
R8 | MUST | done-verified | MEDICAL DATA KEPT 4854/4855 (100.0%); R8 oracles pass
R9 | MUST | done-verified | check_dev @ 74d4590: content 0.4%, filename/base64/metadata/key/header 0.0%
R10 | MUST | done-verified | check_dev precision 1.00, recall 0.84, F0.5 0.96, wrong merges 0
R11 | MUST | done-verified | 681/681 non-null claims found in their record; check_submission "different secret -> different output"
R12 | MUST | done-verified | 339/339 multi-date records keep exact intervals; 0 shifts outside policy (tests/test_acceptance_r11_r13.py); 31/48 patients share one offset (rest unlinked, per-record fallback)
R13 | MUST | done-verified | 0/447 age bands exclude the true age; invalid ages -> [AGE] (tests/test_acceptance_r11_r13.py)
R15 | MUST | done-verified | 0 WARN; counts equal exported files/records; >= 95% of claims found in their record
R16 | MUST | done-unverified | non-zero on missing secret/policy tested; kill-test not run
R17 | MUST | done-unverified | stdout/stderr 0 truth surfaces; report/records paths cleaned (R9); TMP/HOME grep not run
R19 | MUST | done-verified | two runs byte-identical (check_submission, own diff)
R20 | MUST | done-unverified | dev 1.67 s, 24.89 MB peak RSS; network-off and Linux runs not done
R21 | MUST | done-verified | input tree hash unchanged (test_r21, check_submission)
R23 | MUST | partial | runtime deps = psutil only; README has no model section yet
R22 | NICE | partial | truth-surface guard + vocabulary ratchet (D6) + vocab lock (tests/vocab_lock.json); token-swap test deferred to N7
R4 | NICE | partial | 19/19 sanitized bundles parse with fhir.resources R4B, 0 unresolved references, 9/9 attachments decode; own Bundle.type value-set check not built
R14, R18, R24, R25 | NICE | not started | -

Honest progress: MUST 15/19 done-verified (79%); NICE 0/6 (0%).
Time: 17h26m since first commit (2026-11-26 11:42 -> 2026-11-27 05:08).
Health: churn 0.04 overall (714 deleted / 16560 added), 0.09 this range (109 / 1155); 0 reverts; open issues 4; hardcode-check WARN @ d15a3c6 (non-blocking).
Verdict: on track - R5 holds on renamed headers (every R5 type <= 2%) with dev numbers unchanged; R16/R17/R20/R23 unverified stand between the build and the V0 gate.

### scaffold | R1 R2 R3 R15 R16 R19 R20 R21 R23 | 2026-11-26 | commits 21ffd7e..21ffd7e
- Built: CLI + raksha.toml run contract; multi-encoding ingest with reason-coded quarantine; same-shape writers; ID-slot HMAC pseudonym spike; fail-closed policy; psutil tree-RSS sampler; honest report/records
- Evidence: tests 21/21 pass; CONTRACT OK; check_dev leak 62.7%, canaries 4/4, medical 100.0%, F0.5 0.95, 0 wrong merges, raw copies 0
- Reverted / removed: none in git (exact dev header sets replaced before commit, D2)
- Rewritten after earlier logging: none
- Unplanned work: none in this commit (workflow tooling went in f2fe07c)
- Time: single commit
- Shortcuts / debt: "trip"/"ticket" tokens and a patient_ref comment echo dev data (hardcode WARN); Windows quote stripping (exception E1); Python 3.10/3.12 and Linux not run
- Open issues: R16 kill-test, R20 network-off run, R23 README model section

### detection 2a | R5 R6 R17 R22 | 2026-11-26 | commits bacdc86..bacdc86
- Built: header/key meaning classifier + value-shape vote; R6 ID/phone regexes with Devanagari digits; FHIR Reference.display by resolved target; content-free processing_error quarantine; slots.py dev tokens removed
- Evidence: tests 36/36 pass; CONTRACT OK; check_dev leak 16.0%, canaries 3/4, medical 100.0%, F0.5 0.95, 0 wrong merges; redact linear (0.007/0.071/0.685 s at 1x/10x/100x)
- Reverted / removed: starter _BASELINE_PATTERNS (D3)
- Rewritten after earlier logging: wards/pipeline.py (158 lines changed of the scaffold file), wards/slots.py (6 lines)
- Unplanned work: none
- Time: one verify round blocked (2 code bugs + quadratic spans), fixed, committed 17:59
- Shortcuts / debt: structured DOB/VILLAGE/PIN use placeholders until Task 3; output file paths still carry PII (R9); Hinglish meaning tokens unverified beyond dev
- Open issues: R16 kill-test, R20 network-off/Linux, R23 README model section, R17 path leaks (R9)

### detection 2b | R7 R8 (R5 R22) | 2026-11-26 | commits b03b767..b03b767
- Built: wards/names.py label/relation/honorific/subject rules in 3 scripts with bounded span extraction; R8 protect mask; NFC matching with verbatim output; FHIR leaves by parent element; repo guard against dev truth surfaces
- Evidence: tests 46/46 pass; CONTRACT OK; READY TO SUBMIT; check_dev leak 4.9% (latin 5.3, deva 0.0, hinglish 0.0), PATIENT_NAME 7.9%, RELATIVE 0.0%, canaries 1/4, medical 100.0%, F0.5 0.95, 0 wrong merges; linear at 1x/10x/100x (lines and one long line)
- Reverted / removed: none in git
- Rewritten after earlier logging: tests/test_patterns.py, test_run_contract.py, test_side_channels.py (dev values replaced by invented ones); wards/columns.py, pipeline.py (FHIR classification)
- Unplanned work: none
- Time: one verify round blocked (3 code bugs, single-line quadratic, dev-copied fixtures), fixed, committed 18:58
- Shortcuts / debt: 80-char windows and some word lists inline in names.py; dev-truth guard passes silently without the kit; latin names 5.3% and 1 canary left (N1 gazetteer)
- Open issues: R16 kill-test, R20 network-off/Linux, R23 README model section, R17 path leaks (R9), R7 latin + canary

### hidden channels 2c | R9 R22 | 2026-11-26 | commits 298367b..298367b
- Built: Pass 1 evidence harvest + Pass 2 cleaning of file/folder names, headers, JSON keys, path/URL metadata (FHIR meta.source); linear collision suffixes; shared JSON walker; R22 vocabulary ratchet + reviewed allowlist
- Evidence: tests 57/57; check_dev leak 1.3%, filename/header/key/metadata 0%, medical 100.0%, F0.5 0.95, 0 wrong merges; CONTRACT OK; READY TO SUBMIT
- Reverted / removed: NON_MRN_CHANNEL_PREFIXES and dev-tuned CHANNEL_SAFE_WORDS entries (never committed; D6, D7)
- Rewritten after earlier logging: wards/pipeline.py (two-pass), wards/names.py and wards/patterns.py (exposed detectors, bounded regexes)
- Unplanned work: .claude/skills/hardcode-check/SKILL.md check K left uncommitted for a separate chore commit
- Time: one fix round after a blocked verify (19:28 -> 20:49)
- Shortcuts / debt: function-local import of CHANNEL_ID_PREFIXES (hardcode WARN); base64 channel 100% (N4)
- Open issues: R5 PATIENT_NAME 3.0%, R6 PHONE 1 + MRN 9, canaries 1/4, R16 kill-test, R20 network-off/Linux

### linkage-privacy 3 | R10 R11 R12 R13 | 2026-11-26 | commits 1f885cf..1f885cf
- Built: Pass 1 RecordEvidence + union-find with a staged conflict guard (lifelong IDs + DOB veto); cluster HMAC PSN in the ID slot (placeholder when null); per-patient format-preserving date shift; age bands with top-code, district kept, PIN prefix
- Evidence: tests 78/78; CONTRACT OK; READY TO SUBMIT; check_dev leak 1.3%, F0.5 0.96, 0 wrong merges, medical 100.0%; R11 681/681 claims in record; R12 338/339 records exact; R13 447/448 bands truthful
- Reverted / removed: slot_patient_key spike helper, DOB/PIN placeholders for structured fields (D8); same-type conflict rule (D9)
- Rewritten after earlier logging: wards/pipeline.py (762 lines changed), wards/slots.py (137), wards/patterns.py (50)
- Unplanned work: none (tooling edit committed separately as 39ca495)
- Time: two verify rounds blocked (regressed linking/PIN/MRN, then R22 allowlist approval), fixed in review, committed 21:47
- Shortcuts / debt: slots name-word set inline (hardcode WARN); names.py protect regex copy; early log timestamps in MISTAKES/DECISIONS/SHIP were written ahead of the clock (22:30-23:20; real time 21:47)
- Open issues: R12 month-first text docs without a day > 12; R13 negative age banded; R16 kill-test, R17 TMP grep, R20 network-off/Linux, R23 README model section

### date-age-fixes | R12 R13 | 2026-11-26 | commits dc168be..dc168be
- Built: text date order from own dates, then linked records' certain dates, then the export family, day-first only without evidence; invalid ages -> [AGE]; R11-R13 acceptance as a pytest test against dev truth
- Evidence: tests 84/84; R11 681/681, R12 339/339 exact and 0 shifts out of policy, R13 0/447 bands wrong; check_dev unchanged (leak 1.3%, F0.5 0.96, 0 wrong merges); records.jsonl byte-identical
- Reverted / removed: per-file-only text date order (D10)
- Rewritten after earlier logging: wards/pipeline.py (+82), wards/dates.py (+59), wards/generalise.py (40 lines)
- Unplanned work: none
- Time: one round, committed 22:01
- Shortcuts / debt: 'dmy'/'mdy' vote keys inline in pipeline (hardcode WARN); "45-50" age range written as "45-49-50"
- Open issues: R5/R6/R7 partial; R16 kill-test, R17 TMP grep, R20 network-off/Linux, R23 README model section

### Score estimate 2026-11-27 | measurement only | commit 6319c85 (no code changed)
- How: tools/rehearse_eval.py (fresh clone of origin/main, .venv + setup 16.3 s, read-only input copy, 3 runs A/A/B with fresh TMP/HOME), tools/estimate_score.py (SCORING.md + ATTACKS.md re-implemented), tools/mutate_dev.py (renamed headers/keys + invented names exact, date formats approximate). Commands: tools/VERIFY.md. All numbers are ESTIMATES.
- Checklist: READY TO SUBMIT (1 warning, README 62 words); CONTRACT OK; A1 == A2 byte-identical (194/194 + records.jsonl); A vs B 0/681 same PSN, 0/1259 shifted dates equal; secret never written; TMP/HOME empty; 0 PII hits in all 7 side channels (scanner finds 1,099 lines in raw input); wall 2.3 s, peak tree RSS 38 MB; no network code; pytest 84 passed (pytest 9.0.2 installed vs 9.2.0 pinned). FAIL: README sections, Brief PDF (check_submission's "PDF found" is the gitignored problem statement).
- Estimate dev: total 56.5 = privacy 13.6/25 + detection 19.8/20 + utility 18.0/20 + identity 13.3/15 + integrity 9.9/10 + performance 10/10 - penalties 28 (leaked ids/names capped 25: 9 MRN + 9 phone + 18 full names; canary 1/4 = 3). Mutated: 51.0 (leak 1.3% -> 7.2%).
- Weak spots (measured): (1) FHIR base64 attachments not cleaned: name + UHID + phone in 9/19 bundles, plus the 1 leaked canary (misc/scanned_consent_form.json) -> most of the -28 penalties (N4). (2) Nursing-note names: 10 full + 4 partial patient-name mentions (N1). (3) A4 profile attack re-identifies 45/48 patients (raw 47/48): kept tehsil, PIN prefix and DOB year (shifted <= 180 d keeps the year) narrow 240 registry people to one; dropping all three -> 30/48 (N3). (4) A5 targeted 11/14 targets, rare condition kept next to band + district (N3). (5) Interval preservation 0.404: 18/48 patients have > 1 shift because unlinked records are shifted separately; identity recall 0.84, fragmented trap 0.35 (N2). (6) Renamed headers leak HOUSE/LOCALITY/LANDMARK ~40% and MRN 7.4% (N7). (7) report.json has no `entities` field (report quality 0.92). (8) village field fully redacted (generalisation village 0.0; tehsil would give 0.8 but costs privacy).

### N4 slice 1 base64 | R9 R4 R8 (R6 R7) | 2026-11-27 | commits 6319c85..74d4590
- Built: base64 decode-clean-re-encode for FHIR Attachment data, data: URIs and plain-JSON base64 (variant-preserving, depth cap 3, binary/invalid -> placeholder + reason code); run-time name evidence inside decoded payloads; vocab lock and redaction invariant guards (368a08c)
- Evidence: tests 110/110; check_dev base64 0.0%, leak 0.4%, canaries 0/4, medical 4854/4855, F0.5 0.96, 0 wrong merges; CONTRACT OK; READY TO SUBMIT; 19/19 bundles R4B-valid; byte-identical reruns
- Reverted / removed: none in git ("Referral" label and decode-first ordering removed before commit, D11)
- Rewritten after earlier logging: wards/channels.py, wards/pipeline.py (extended, not reverted)
- Unplanned work: d0a360a score tools + /score-check skill (measurement tooling, own commit); tests/test_channels.py timing helper
- Time: 4h50m (22:06 -> 02:56)
- Shortcuts / debt: BASE64_MIME_LINE_WIDTH in runtime config used only by tests (hardcode WARN)
- Open issues: R5 renamed-column MRN leak; R16 kill-test, R17 TMP/HOME grep, R20 network-off/Linux, R23 README model section

### R5 slice 1 column-shape | R5 R8 | 2026-11-27 | commits fff7ed4..d15a3c6
- Built: per-column value-shape/address/age/run-time-name vote for unknown headers; adjacent address-part promotion; ID override of facility-style headers by non-medical, high-cardinality values (once per column/key, tie at half -> ID); non-patient ID columns by per-patient variation; DD.MM.YYYY dates
- Evidence: tests 127/127; dev leak 0.4%, canaries 0/4, medical 4854/4855, F0.5 0.96, 0 wrong merges; renamed-header set leak 6.9% -> 1.0%, MRN 6.4% -> 0.0%, HOUSE/LOCALITY/LANDMARK 39.7/36.9/40.6% -> 0.0/1.9/0.0%; CONTRACT OK; READY TO SUBMIT
- Reverted / removed: none in git (word lists HOSPITAL_ID_ISSUER_WORDS/HOUSE_ABBR_WORDS dropped before commit, D13)
- Rewritten after earlier logging: wards/columns.py (414 lines), wards/slots.py (164), wards/pipeline.py (137)
- Unplanned work: none (dates.py dot-date fix serves the renamed-set DOB acceptance)
- Time: 3 verify rounds (2 blocked: over-redaction, word lists, per-value vote + 25x slowdown), committed 05:08
- Shortcuts / debt: capped column sample built in 3 places (hardcode WARN); 10k-row CSV 1.55 s vs 1.10 s before (more ID columns found)
- Open issues: renamed set RELATIVE_NAME 6.0% (hinglish 12.6%) in forwarded-message texts (R7/N1); R16 kill-test, R17 TMP/HOME grep, R20 network-off/Linux, R23 README model section
