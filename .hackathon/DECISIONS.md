# DECISIONS (approach changes, newest last)
~~~
### D1 | 2026-11-26 16:57 | R1,R2,R3,R15,R16,R19,R20,R21 | modular wards/ package instead of starter single-file main.py
- Was: kit starter single-file main.py (not built in this repo)
- Now: thin main.py -> wards/ package (config, pseudo, resources, ingest, slots, writers, pipeline, cli)
- Why: separates config, HMAC pseudonyms, psutil tree-RSS sampling, safe ingest/quarantine, slot replacement and writers for Tasks 2 and 3 (Antigravity report); stays within LOCKED Decision B
- Trigger: ship
- Obsolete: none
- Lesson: keep the single entry point thin; one module per concern
~~~
~~~
### D2 | 2026-11-26 17:20 | R3,R15,R22 | slot column chosen by meaning tokens + value-shape vote
- Was: exact header-name sets in wards/slots.py (built, never committed)
- Now: generic ID-meaning tokens (uhid/mrn, patient|pt + id|no|ref, reg|ipd|opd|adm + id|no) plus a per-column value-shape vote
- Why: hardcode-check and scope FAIL (Kill list: dev header list in code); renamed-header tests now pass (tests/test_slots_generic.py)
- Trigger: ship
- Obsolete: none (old sets already removed)
- Lesson: never classify columns by a list of full header names
~~~
~~~
### D3 | 2026-11-26 17:50 | R5,R6 | column/key meaning classifier + R6 pattern engine replace starter regexes
- Was: starter 5-regex clean_text in wards/pipeline.py (commit 21ffd7e)
- Now: wards/columns.py (header/key meaning tokens + per-column value-shape vote) and wards/patterns.py (Devanagari-digit-aware ID/phone regexes with typed placeholders)
- Why: check_dev leak 62.7% -> 16.0%, AADHAAR/ABHA/PAN/INSURANCE/EMAIL/DOB/VILLAGE/PIN 0%, medical kept 100%, F0.5 0.95 (Antigravity report, reproduced by verify-commit)
- Trigger: ship
- Obsolete: _BASELINE_PATTERNS in wards/pipeline.py (already removed)
- Lesson: classify by meaning + value shape, and keep span bookkeeping linear
~~~
~~~
### D4 | 2026-11-26 19:28 | R9 (R5,R6,R7) | two-pass pipeline: Pass 1 harvests name tokens and MRN cores, Pass 2 cleans channels
- Was: single-pass run_pipeline (commit b03b767)
- Now: Pass 1 parses every file and keeps only ChannelEvidence (PATIENT_NAME/RELATIVE tokens and phrases, >=5-digit MRN cores); Pass 2 re-reads, cleans content + file/folder names, headers, keys and path metadata, with a deterministic rename map
- Why: unlabelled names and MRN tails in file names, headers and keys can't be told apart from clinical words without run-time content evidence; measured on an LF copy of dev/input: filename 0/48, header 0/8, key 0/12, metadata 0/40 leaked (was 100%)
- Trigger: ship
- Obsolete: none
- Lesson: hidden-channel detection uses evidence harvested from the same run, never word lists from the practice data
~~~
~~~
### D5 | 2026-11-26 19:37 | R15,R17,R9 | records.jsonl loc uses the cleaned key under a PII top-level key
- Was: SPEC sec 6 reading: loc = raw input locator, so the JSON pointer carries the original key even when that key holds PII (not built)
- Now: when a top-level key holding a record list contains PII, loc is written with the cleaned key (current pipeline.py behaviour, kept)
- Why: user decision. SPEC sec 7 scans records.jsonl for PII; a leak there costs a penalty and channel hygiene, while an unmatched loc only loses linking credit on those rare records (0 dev records affected)
- Trigger: user
- Obsolete: none
- Lesson: when contract fidelity and PII hygiene conflict, keep the output PII-free and accept the smaller scoring loss
~~~
~~~
### D6 | 2026-11-26 19:55 | R22,R9 | R22 guard: AST vocabulary-overlap ratchet against a reviewed allowlist
- Was: tests/test_no_dev_strings.py only (truth PII surfaces of 6+ chars; returns early when truth.json is missing) (commit bacdc86)
- Now: it is kept and fails when its fixture is missing. A new test, tests/test_r22_vocab_overlap.py, pulls word tokens from the non-docstring string literals in main.py, wards/ and config/. Any token that is a dev file-name token or appears in 1-3 dev input files must have a (word, file, owner) line in tests/r22_vocab_allowlist.txt naming a non-dev source. The allowlist is seeded in review (218 entries; 51 dev-tuned uses left out) and only Claude or the user edits it; the hardcode gate flags any other edit.
- Why: /unstick on R22 (seen 5). 45 of 646 word literals in wards/ were dev file-name tokens and the old guard passed; CHANNEL_SAFE_WORDS (42/110) and NON_MRN_CHANNEL_PREFIXES (14/24) came from dev file names
- Trigger: unstick
- Obsolete: NON_MRN_CHANNEL_PREFIXES; the dev-tuned entries of CHANNEL_SAFE_WORDS; dengue in CLINICAL_HEAD_NOUNS; the early return in test_no_dev_strings.py
- Lesson: guard against dev tuning with a reviewed ratchet on vocabulary, not a check for PII values only. The behavioural token-swap test (route C) is deferred to N7 (V1), see the 04-idea-scope change log
~~~
~~~
### D7 | 2026-11-26 20:49 | R9,R22 | <letters>-<year> channel tokens: allow-rule on ID meaning instead of a deny-list
- Was: NON_MRN_CHANNEL_PREFIXES deny-list of dev file-name words skipped "<word>-<19xx|20xx>" as MRN (not committed)
- Now: in channel mode such a token is an MRN only when its letters are an ID-meaning token (CHANNEL_ID_PREFIXES = the columns.py ID vocabulary) or its digits are a harvested MRN core
- Why: the deny-list kept "dengue-2026" but redacted the unseen "malaria-2026" (test_r9_r22_condition_year_filename_is_not_an_mrn); 57/57 tests pass and filename leak stays 0/48 on dev
- Trigger: ship
- Obsolete: NON_MRN_CHANNEL_PREFIXES (removed)
- Lesson: decide by meaning that applies to unseen words (allow-rule), never by excluding the words the practice data happens to use
~~~
~~~
### D8 | 2026-11-26 21:40 | R10,R11,R12,R13 | cluster-key pseudonyms + per-patient date shift and QI generalisation replace the scaffold slot key and DOB/PIN placeholders
- Was: per-record slot key `slot:<normalised ID>` (wards/pseudo.py slot_patient_key, commit 21ffd7e) and Task 2 DOB/PIN placeholders (commit bacdc86)
- Now: Pass 1 RecordEvidence -> union-find over strong IDs, name+DOB and name+relative with a conflict guard -> canonical cluster key -> HMAC PSN (wards/linkage.py); per-patient HMAC date offset with format-preserving rewrite (wards/dates.py); age bands with top-code, district kept, PIN prefix (wards/generalise.py)
- Why: 04-idea-scope Design decisions (a)/(b) and Task 3. Measured in the working tree (not committed, /verify-commit BLOCKED): check_submission READY TO SUBMIT with keyed outputs, but check_dev F0.5 0.95 -> 0.35, PIN leak 0% -> 17.6%, MRN 1.1% -> 3.5%, so the approach stands and its conflict guard and detector hand-offs need fixing
- Trigger: ship
- Obsolete: slot_patient_key (already removed); PLACEHOLDERS["DOB"]/["PIN"] use for structured DOB/PIN fields
- Lesson: when a new stage takes over from a detector, measure the old detector's channel before and after
~~~
~~~
### D9 | 2026-11-26 22:30 | R10,R11 | conflict guard on lifelong IDs + DOB only, in edge tiers; per-issuer IDs keyed by digit core
- Was: any two values of one strong-ID type in a cluster are a conflict (02-domain sec 4 R10 wording; working tree of D8, not committed); per-issuer IDs keyed by letters+digits
- Now: only lifelong IDs (Aadhaar, ABHA, PAN; config.LINK_LIFELONG_ID_TYPES) and DOB conflict. A conflicting component is re-clustered in stages that drop weak name edges, then contact handles (config.LINK_CONTACT_ID_TYPES), then per-issuer IDs; the canonical key uses only the stage's edge types, so split groups never share a key. MRN/UHID/IPD/insurance key on their digit core. Visit/bill/sample columns and keys (slots.is_non_patient_id_key) are never patient evidence
- Why: check_dev F0.5 0.35 -> 0.96 (recall 0.10 -> 0.84), precision 1.00, wrong merges 0; one patient has different MRNs at different hospitals, so a same-type MRN rule split every cross-hospital cluster
- Trigger: user (fixes applied in review, user-approved)
- Obsolete: _LIFELONG_STRONG_TYPES and the 3-stage hand-written split in link_records (removed)
- Lesson: only identifiers that are one-per-person may veto a merge; per-issuer IDs are evidence, never a veto
~~~
~~~
### D10 | 2026-11-26 21:47 | R12,R13 | text date order from run-wide evidence; invalid ages get the placeholder
- Was: infer_date_order voted only inside one text file and fell back to day-first; an age above MAX_VALID_AGE was left raw, a negative one banded (commit 1f885cf)
- Now: a text file's own votes decide first; with none, the certain dates of records linked to the same patient pick the reading of its ambiguous dates; then the files of the same export family (same folder, same name with digit runs masked); day-first only without evidence (pipeline._decide_text_date_orders, dates.resolve_date_order). Ages outside [MIN_VALID_AGE, MAX_VALID_AGE] become [AGE]
- Why: R12 acceptance 338/339 -> 339/339 records with exact intervals, shifts outside policy 2 -> 0; R13 1/448 -> 0/447 bands excluding the true age; check_dev numbers unchanged
- Trigger: user (fix round after the post-commit acceptance measurement)
- Obsolete: per-file-only order decision for text in Pass 2; .hackathon/bench/acc_r11_r13.py is superseded by tests/test_acceptance_r11_r13.py
- Lesson: an ambiguous value is decided by the strongest evidence in the run, not by a default
~~~
~~~
### D11 | 2026-11-27 02:56 | R9,R4,R6,R7,R8 | base64 decode-clean-re-encode: raw-first cleaning, structural Attachment, run-time names
- Was: base64 left opaque to every cleaner (commit 6319c85); in the uncommitted first N4 round, guessed base64 replaced raw-text cleaning, any FHIR 'data' key counted as an attachment, and "Referral" was added to NAME_LABELS to catch the consent-form name (not committed)
- Now: explicit base64 (Attachment = 'data' with a contentType sibling or an attachment parent; RFC 2397 data: URIs) is decoded, cleaned by the same text/JSON cleaners plus Pass 1 run-time name evidence, and re-encoded in its own variant; binary or unverifiable payloads become base64 of a placeholder with a reason code. A guessed plain-JSON decode runs only after raw-text cleaning, so it can only add redactions
- Why: check_dev base64 channel 100% -> 0.0%, canaries 1/4 -> 0/4, leak 1.3% -> 0.4%, medical kept 4854/4855; 19/19 bundles R4B-valid with 0 unresolved references; the review found a bare Aadhaar leak (20/1,019 generated values) from the decode-first ordering and a dev-driven word addition, both fixed and guarded by tests/test_redaction_invariants.py and tests/test_vocab_lock.py
- Trigger: ship
- Obsolete: "Referral" in NAME_LABELS; is_fhir as an Attachment signal (both removed before commit)
- Lesson: a decoding path may add redactions, never replace the detectors on the raw value
~~~
~~~
### D12 | 2026-11-27 04:10 | R5 (R10,R12) | column meaning: header tokens no longer short-circuit the value-shape vote; address/age/run-time-name votes; adjacency promotion
- Was: classify_csv_columns returned the header class whenever classify_header_tokens matched and voted only R6 ID shapes + PIN; "hospital" headers always PRESERVE_EXACT; JSON name parts only under parent_key == "name"; DD.MM.YYYY not parsed (commit fff7ed4)
- Now: per-column vote over a capped sample (COLUMN_VOTE_SAMPLE_CAP) with R6 shapes, address-cue shapes, age shape and Pass 1 name evidence; "hospital" + ID suffix deferred to the vote; FREE_TEXT columns next to an address/PIN/district column promoted to HOUSE/LOCALITY/LANDMARK by shape; unknown-header MRN-shaped columns that vary per patient excluded as non-patient IDs (find_non_patient_mrn_cols); name parts under any name-token parent; [-/.] date separators
- Why: mutated dev set (tools/mutate_dev.py) MRN 6.4% -> 0.0%, HOUSE 39.7% -> 0.0%, LOCALITY 36.9% -> 1.9%, LANDMARK 40.6% -> 0.0%, all 7 R5 types <= 2%; dev numbers unchanged (leak 0.4%, F0.5 0.96). NOT committed: /verify-commit BLOCKED on 3 over-redaction test failures (modifier-only names, cue-word addresses in notes)
- Trigger: ship
- Obsolete: the header-match early return in classify_csv_columns (removed in the working tree)
- Lesson: let value shape overrule a weak header, but never let one cue word decide a value's meaning in free text
~~~
~~~
### D13 | 2026-11-27 04:55 | R5,R22 | facility-word IDs and house abbreviations by value shape, not new word lists
- Was: HOSPITAL_ID_ISSUER_WORDS {'hospital'} + is_hospital_id_tokens and HOUSE_ABBR_WORDS ('h.no.', ...) in wards/config.py (working tree of D12, not committed)
- Now: a PRESERVE_EXACT header is overruled by the strict R6 ID vote when the cells are non-medical (is_r8_medical_value) and high-cardinality (COLUMN_ID_MIN_CARDINALITY_RATIO); "H.No."-style cues match a letter + next token whose join is in the locked _HOUSE_TOKENS ('hno')
- Why: user decision 2026-11-27: no new word lists in config.py; both words came from the renamed practice set and the vocab lock flagged them. Mutated set unchanged (7 R5 types <= 2%), dev unchanged. NOT committed: /verify-commit BLOCKED (per-leaf vote with one value, 25x slowdown on large CSVs)
- Trigger: user
- Obsolete: HOSPITAL_ID_ISSUER_WORDS, is_hospital_id_tokens, HOUSE_ABBR_WORDS (already removed)
- Lesson: when a fix needs a new word, look for the value shape or an already-locked word first
~~~
~~~
### D14 | 2026-11-27 05:45 | R5,R20 | ID override decided once per column/key with a min-values + distinct-count rule
- Was: the PRESERVE_EXACT -> ID vote ran per JSON leaf / per CSV row on one value (always 1 distinct of 1), and Pass 1 re-voted the 200-cell sample on every row (working tree of D13, not committed)
- Now: decided once per column/key over all its values: needs >= COLUMN_ID_MIN_VALUES (2) values and distinct share >= COLUMN_ID_MIN_CARDINALITY_RATIO (0.5) or >= COLUMN_ID_MIN_DISTINCT (10) distinct values; a lone value keeps its header meaning; ties at exactly half go to the ID (privacy-first, user decision 2026-11-27, test_r5_tie_break_...). CSV slot priorities and non-evidence columns computed before the row loop
- Why: JSON facility codes were redacted as MRN; 10k-row CSV 29.67 s -> 1.55 s (74d4590 1.10 s); tests 127/127; dev unchanged; mutated MRN 6.4% -> 0.0%, all 7 R5 types <= 2%. D12 and D13 ship in the same commit
- Trigger: user
- Obsolete: single-value resolve_id_slot_override calls in pipeline.py and slots.py (removed)
- Lesson: a decision about a column is never made from one of its values
~~~
~~~
### D15 | 2026-11-27 | R7,R9,R8 | run-time name evidence on plain-text documents, inside the R8 protect mask
- Was: _process_text cleaned .txt documents with clean_text only; redact_known_names_in_text (D4 evidence) protected only placeholders and doctors; ASHA always protected (commit 357b571)
- Now: _process_text takes the Pass 1 ChannelEvidence (required) and applies redact_known_names_in_text after clean_text; that function skips every build_protect_mask span; single-token evidence only in documents with a patient (active PSN), multi-token phrases elsewhere; ASHA stays protected except right after a person label or before a capitalised non-stop token
- Why: 11 full names left in nursing notes/prescriptions (−11 penalty); dev PATIENT_NAME 11/962 -> 0/962, leak 0.4% -> 0.1%, medical kept 4854/4855 unchanged; mutated leak 1.0% -> 0.3%; tests 132/132; a simulation without the mask and the patient gate lost a protected term on dev and a clean-document term on the mutated set
- Trigger: ship
- Obsolete: the local PROTECTED_TOKEN_RE + doctor-span mask in redact_known_names_in_text (replaced by build_protect_mask)
- Lesson: run-time evidence is safe in prose only inside the same protect mask the rule-based detectors use
~~~
