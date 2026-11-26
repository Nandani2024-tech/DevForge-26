STATUS: LOCKED (changes only via /pivot-check)
# 04-idea-scope (solo V0 in 3 Antigravity tasks; team continues from .hackathon/ + .claude/)
## Approaches and scores
- A Off-the-shelf: Presidio + spaCy rule NER + splink + pycanon around the starter. Covers R1-R3, R6, R15-R21 (Latin only). Libs: presidio, spacy, splink, pycanon. Custom ~10 h. Core: NER pass O(tokens), F-S EM O(blocked pairs). Riskiest: English NER finds Hindi/Hinglish names and relatives (PS says it doesn't).
- B Simple custom core: the starter skeleton + two passes (pass 1 evidence -> union-find on strong keys, pass 2 rule redaction by column semantics + context rules + per-patient HMAC shift/bands). Covers every MUST. Libs: stdlib, psutil, later rapidfuzz/jellyfish. Custom ~25 h. Core: regex/rules O(bytes) + union-find O(R·α(R)). Riskiest: an ID or name slot exists in every record type to carry the pseudonym without changing shape.
- C Ambitious: self-trained CRF token tagger (Faker-synthesised training data) + F-S with EM + Mondrian global k-anonymity. Covers R5-R7, R10, R14 strongly. Libs: sklearn-crfsuite, numpy. Custom ~60 h. Core: CRF O(tokens·labels²), Mondrian O(n log n). Riskiest: synthetic training transfers to hidden formats, inside 3-4 tasks.
- D Reframe "allowlist-first": in patient-bearing free text keep only tokens proven clinical (drug/unit/ICD/vital/lab patterns, the clean/ vocabulary, section labels) and redact the rest; same linkage as B. Covers R5-R9 conservatively. Custom ~30 h. Core: token classification O(tokens). Riskiest: complaint/history wording survives (clinical probes, token retention, F2 precision).

| | Feas x3 | Judging x3 | Demo x2 | Diff x2 | Reuse x1 | Total /55 |
|---|---|---|---|---|---|---|
| A | 3 | 2 | 2 | 1 | 5 | 26 |
| B | 5 | 4 | 4 | 3 | 3 | 44 |
| C | 2 | 4 | 4 | 5 | 2 | 38 |
| D | 3 | 3 | 3 | 4 | 2 | 34 |
- A Diff 1: the PS says wrapping off-the-shelf PII tools scores poorly. A Reuse 5: almost all library. B Feas 5: grows from the working starter, measurable after each task with kit tools. C Feas 2: CRF + EM + Mondrian won't fit 3-4 tasks, so C is ineligible. C Diff 5: the only learned, generalising detector.
## Decision
- Chosen: B. Highest total, Feasibility 5, deterministic and explainable in the viva, and every R-id is reachable with the Reuse Stack (stdlib + psutil now; rapidfuzz/jellyfish in V1).
- Plan B: D (C is ineligible at Feasibility 2). D reuses B's ingest, linkage and privacy layer and swaps only the free-text detector.
- Switch trigger: if after the Task 2 /ship check_dev still shows > 25% of PII visible overall or 4/4 canaries, switch the free-text detector to D's allowlist mode for patient-bearing text fields.
## Riskiest assumption and spike
- Assumption: every patient-bearing record type (CSV/TSV row, JSON record, text note, FHIR Bundle) has an existing ID or name slot. Writing the pseudonym there keeps header, column count, key paths, value types and line count (R3) and makes the claim visible (R11).
- 15-minute test (inside Task 1 "scaffold"): with a dummy record-level key, write PSN-XXXXXX into the first ID-like column/key/label line of each record. Run validate_output, check_dev, and a script that checks each records.jsonl claim against its exported record.
- Pass: CONTRACT OK, all check_dev numbers still computed, >= 95% of non-null claims found inside their record (assumed), and 0 shape diffs vs input (R3 script).
## MVP cut line (by R-id)
- MUST (V0): R1, R2, R3, R5, R6, R7 (V0 level: Latin labels, relations, honorifics, plus labelled Devanagari `नाम:`), R8, R9 (V0 level: the same cleaner on headers, JSON keys, export metadata and file names, with renames mapped in report), R10 (V0 level: strong-key links + name+DOB, null otherwise), R11, R12, R13, R15, R16, R17, R19, R20 (measured with psutil; R15 needs peak_rss_mb), R21, R23 (no LLM deps; checked by check_submission).
- V0 exit gate: validate_output CONTRACT OK; check_dev beats the starter on every number except the base64 channel (user-approved; base64 waits for N4) (leak 84.1%, deva 100%, hinglish 100%, each channel 100%, canaries 4/4, F0.5 0; medical kept stays >= 97%); check_submission --run READY TO SUBMIT (needs a stub README.md).
- NICE (V1 roadmap, priority order, one task each; target from 01-ps sec 6):
  - N1 extends R7: run-time gazetteer harvested from the input's structured name columns + custom Devanagari->Latin map with schwa rules. Target: leak <= 3% overall, deva <= 5%, hinglish <= 5%, canaries 0.
  - N2 extends R10: scored cross-script linkage (rapidfuzz + jellyfish blocking) with a conflict guard. Target: precision >= 0.95, F0.5 >= 0.85, 0 wrong merges.
  - N3 R14: k-anonymity on (age band, gender, district, admit month, rare dx) with measured risk. Target: unique share < 10% (assumed, R14); the number goes in the README.
  - N4 extends R9: hidden channels in full (base64 decode-clean-re-encode, \u and entity escapes, FHIR narrative/meta.source). Target: every check_dev channel 0%.
  - N5 R4: FHIR R4B parse + own value-set and reference check. Target: 19/19 pass.
  - N6 R18: AES-GCM spill files, key in memory. Target: no plaintext PII in TMPDIR during or after the run.
  - N7 R22: mutation harness (renamed columns, Faker names, new date formats). Target: leak within +5 points of dev.
  - N8 R24 + R25: full README + 2-page brief with measured numbers. Target: README >= 300 words with all sections; PDF = 2 pages.
  - N9 demo view under tools/ (offline, static HTML via stdlib, reads the output folder only). Target: none in sec 6; must not change run outputs (determinism digest unchanged).
- NICE R-ids: R4, R14, R18, R22, R24, R25 (PS-sourced; APPROVED by user 2026-11-26). DROP: none.
## Complexity and performance targets
- R2/R3/R5-R9: dev 200 files (~0.3 MB); hidden larger with a bulk export (assumed <= 10x). O(bytes) per file with precompiled regexes; one dict lookup per column. Measured by report.timing.
- R10/R11: records 815 dev (assumed <= 10k hidden). Index each strong key in a dict to its first record, then union-find with path compression, O(R·α(R)). Pass 1 keeps only evidence tuples, so memory is O(evidence), not O(data).
- R12/R13: O(dates) with datetime arithmetic; the shift comes from a cached HMAC per cluster.
- R15/R19/R20: whole dev run < 60 s and peak tree RSS < 512 MB (tightened to < 20 s on dev, assumed). Byte-identical outputs across 2 runs (check_submission digest). psutil sampler thread at 50 ms.
## Design decisions (requested)
- (a) Pseudonym source: canonical cluster key = the minimum, in sorted order, of the members' strong keys as `type:normalised_value` (UHID/IPD digit core, Aadhaar, ABHA, phone, PAN, insurance). With no strong ID but a name+corroborator link, key = `nm:` + normalised name key + `|` + the corroborator (ISO DOB, or the relative-name key) taken from the lowest-sorted member. With neither, patient = null, nothing is written into the record, and dates get a per-record HMAC shift keyed on input path + loc (internal only, never output). PSN = HMAC-SHA256(SECRET, key) in Crockford base32 (starter helper).
- (b) What carries the privacy. Stay length and intervals are fixed by utility, so the defence sits on the absolute dates and the QIs:
  - per-patient shift in [-180, +180] days with |shift| >= 7, so the A5 known-date match fails and the global shift can't be recovered;
  - DOB shifted by the same offset (still <= 1 year, score 0.9);
  - age as a 5-year band, top-coded 85+;
  - village, house, locality and landmark removed; location kept at district; PIN cut to its 3-digit prefix;
  - rare diagnosis kept (clinical probes), but in V1 (N3) its record's QIs are coarsened when a condition is shared by <= 3 profiles: age to a 20-year band, district dropped. Suppression is the fallback only if measured risk stays high.
- config/policy.yaml defaults:
  - age_band_years: 5
  - age_top_code: 85
  - date_shift_max_days: 180
  - date_shift_min_abs_days: 7
  - location_level: district
  - pin_prefix_digits: 3
  - min_group_size: 5
  - rare_condition_max_profiles: 3
  - rare_action: coarsen
## Screens and UX (no UI; the views are terminal outputs)
- V1 CLI run: `python main.py --input --output`. Action: run. Shows counts only.
- V2 check_dev summary. Action: read the leak / kept / linking numbers vs the starter.
- V3 validate_output + check_submission. Action: confirm CONTRACT OK and READY TO SUBMIT.
- V4 before/after diff of one input vs sanitized file (`git diff --no-index`). Action: show the judges a redaction. UI kit: none (stdlib; N9 later).
## Build order hint (exactly 3 tasks, each one /handoff-prompt + one /ship)
1. scaffold (spike): starter-based package, raksha.toml (name Procrastinators), requirements.txt + requirements-dev.txt, policy.yaml defaults, .gitignore, psutil RSS, Python 3.10-safe, hardened ingest/quarantine, honest report/records, exit codes, pytest over kit tools + 02-domain oracles, stub README, ID-slot PSN spike. Covers R1-R3, R15, R16, R19-R21, R23.
2. detection: column-semantics classifier (header words + value shape), ID/phone digit-core regexes with Devanagari digits, label/relation/honorific name rules, preserve rules (Dr., doses, 1-0-1, C/O complaint, K/C/O), applied to content, headers, keys, metadata and file names; PII-free logging. Covers R5-R9, R17.
3. linkage + privacy: pass-1 evidence, strong-key union-find + name+DOB with a conflict guard, canonical key and PSN in the ID slot + records.jsonl, format-preserving per-patient date shift (per-record fallback), DOB shift, age bands, district + PIN prefix. Covers R10-R13; then the V0 exit gate.
## Kill list
- 01-ps non-goals: UI in the run path; OCR/parsing of PDF/JPG/XML; a ZKP pipeline; LLMs, large models, model training.
- Drift: Presidio/spaCy/splink/pycanon/dateparser; CRF training; Mondrian; surrogate fake names; adding a new pseudonym column (breaks schema); multiprocessing (determinism); raising the recursion limit; any dev name, header or file list in code; V1 items before the V0 gate passes.
## Proposed spec changes
- none to 01-ps.md. Resolved 2026-11-26 (user): (1) R4, R14, R18, R22, R24, R25 in NICE: APPROVED. (2) V0 gate excludes the base64 channel until N4; Task 2 unchanged: ACCEPTED. (3) R20 and R23 in MUST: APPROVED.
