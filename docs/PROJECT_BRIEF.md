# Procrastinators: a two-pass, evidence-driven privacy firewall for Indian hospital records

**Track 3 · Secret Wards** · Members: Ayush Kumar Patra, Nandani Kumari · Repo: https://github.com/Nandani2024-tech/DevForge-26 · Commit measured: `579de09`

## 1. In one paragraph
Our firewall reads a messy multi-hospital dump (CSV/TSV/JSON/FHIR/text in English, Hindi and Hinglish) and writes a research release in which names, IDs, contacts and addresses are removed, medical values are kept exactly, and each patient carries one keyed pseudonym across files, hospitals and scripts. The core idea is **two passes**: Pass 1 harvests evidence from the whole input (names from structured name columns, ID cores, DOBs, relatives) and links records; Pass 2 cleans every channel using that run-time evidence, so a name first seen in a registration CSV is also removed from free-text notes, file names, JSON keys and base64 attachments. Everything is rule-based and explainable: no ML model, no LLM, one runtime dependency (`psutil`).

## 2. Architecture
```
input/ ─► Ingest ─────────────► Pass 1: evidence ──────► Linkage
          decode, detect JSON    name tokens, ID cores,   union-find + conflict guard
          by content, else       DOB, relatives           → HMAC pseudonym per cluster
          quarantine (reason)                                      │
   ┌───────────────────────────────────────────────────────────────┘
   └─► Pass 2: clean every channel ─────► Privacy layer ──────► Export to {output}/
       columns by meaning + value shape;   per-patient date      sanitized/
       ID/phone shapes; names in 3         shift, age bands,     report.json
       scripts; file names, headers,       tehsil/district,      records.jsonl
       keys, metadata, base64              PIN prefix
```

## 3. How it works
- **Ingestion** (`ingest.py`): decodes UTF-8, UTF-8-BOM, UTF-16 (with BOM) and cp1252; detects JSON by content (e.g. JSON behind a `.csv` name). Files we cannot process safely are quarantined with a reason code (`unsupported_format`, `invalid_json`, `invalid_csv`, `deep_json`, `empty_file`, `undecodable_text`) and are **never copied** to the output.
- **Detection** (`columns.py`, `patterns.py`, `names.py`, `channels.py`): structured columns and JSON keys are classified by meaning *and* by a capped vote over their values (ID shape, address cues, age shape, run-time names), so renamed headers (`Contact#`, `Gram/Mohalla`) still work. IDs and phones by shape in context (Devanagari digits normalised; Aadhaar Verhoeff only raises confidence, since 21% of dev Aadhaar values fail it). Names by labels, relations (S/o, D/o, W/o, C/O), honorifics and Hindi/Hinglish subject clues, plus the Pass 1 names. A protect mask keeps doctors, `C/O` complaints, `K/C/O`, `H/O`, doses (`1-0-1`), eponyms, wards and ASHA. Hidden channels: file and folder names, CSV headers, JSON keys, export metadata, FHIR `Reference.display`, and base64 attachments (decoded, cleaned, re-encoded in the same variant).
- **Linkage & pseudonyms** (`linkage.py`, `pseudo.py`): union-find over strong IDs (Aadhaar, ABHA, PAN, phone, UHID/IPD digit cores), name+DOB and name+relative edges. Names are normalised across case, honorifics, word order and script (own Devanagari→Latin table with schwa deletion). A conflict guard rejects clusters with two DOBs or two values of a lifelong ID and re-clusters them with weaker edges removed; weak evidence gives `patient: null`. Pseudonym = `PSN-` + HMAC-SHA256(`RAKSHA_SECRET`, canonical cluster key).
- **Privacy layer** (`dates.py`, `generalise.py`, `config/policy.yaml`): one secret per-patient date shift in ±[7, 180] days (format kept, intervals and stay length exact; DOB uses the same shift); ages to 5-year bands, top-coded 85+; village, house, locality and landmark removed, tehsil and district kept, PIN cut to its 3-digit prefix (`229***`).

## 4. USP
- **Run-time evidence instead of word lists:** names learnt from the input itself are applied to every channel, which is why dev Hindi and Hinglish leaks are 0.0% and canaries 0 of 4.
- **Cross-script linkage that refuses to over-merge:** transliterated name keys plus a conflict guard: 0 wrong merges on dev, renamed-dev and hidden_normal.
- **Built and measured for unseen formats:** column meaning by value shape, and every change re-measured on data we did not tune on (table below), with our own rehearsal, mutation and score-estimate tools in `tools/`; 132 automated tests pass.

## 5. Privacy–utility trade-off (measured, kit `check_dev.py` + our tools, commit `579de09`)

| Measure | dev (practice) | renamed dev | hidden_normal | hidden_chaos |
|---|---|---|---|---|
| personal data leaked (overall / Hindi / Hinglish) | 0.1% / 0.0% / 0.0% | 0.3% / 0.0% / 0.9% | 2.3% / 5.0% / 2.2% | 2.5% / 5.8% / 4.7% |
| canaries found / raw copies | 0 of 4 / 0 | 0 of 4 / 0 | 1 of 6 / 2 | 1 of 6 / 1 |
| medical values kept | 100.0% (4854/4855) | 100.0% | 99.5% | 99.5% |
| linking precision / recall / F0.5 (wrong merges) | 1.00 / 0.84 / 0.96 (0) | 1.00 / 0.84 / 0.96 (0) | 1.00 / 0.88 / 0.97 (0) | 0.99 / 0.79 / 0.94 (1) |
| re-identification (our local profile attacker, A4) | 45/48 (raw: 47/48) | – | 105/120 (raw: 119/120) | 133/150 (raw: 150/150) |
| run time / peak memory (whole tree) | 2.8 s / 39 MB | 2.7 s / 39 MB | 16.7 s / 182 MB | 19.3 s / 183 MB |
| our score estimate (not official) | 86.9 | 73.6 | 49.0 | 52.2 |

**Data we did not tune on.** *Renamed dev* is built by our `tools/mutate_dev.py`: 77 renamed headers, 258 renamed JSON keys, 933 rewritten dates, 125 invented names. *hidden_normal* (446 files, 120 patients) and *hidden_chaos* (523 files, 150 patients, unseen-format round) come from **our own independent seeded generator (swgen)**, written from the public docs, with new hospitals, name pools and formats that share no name token with dev (except one deliberate eponym trap, *Mary*). Leaks rise from 0.1% to 2.3–2.5% there; the score estimate drops mainly because of penalties (leaked unique IDs reach the −25 cap, plus raw copies), not because of medical utility, which stays at 99.5%.

**Why these settings.** Exact medical values, intervals and stay length are kept because utility scoring needs them; privacy therefore rests on removing direct identifiers, shifting absolute dates per patient, 5-year age bands and tehsil/district-level location. The cost is visible in the attacker row: the remaining quasi-identifiers (age band, sex, tehsil, district, PIN prefix, diagnosis, admission timing) still single out most patients, so profile re-identification is our weakest area.

## 6. Security design
- `RAKSHA_SECRET` is read only from the environment and never written; checked: 0 hits in output, stdout/stderr, TMPDIR and HOME across runs with random secrets. Another secret changes every pseudonym (0 of 681 equal on dev).
- Nothing is written outside `{output}`: no temp or spill files (TMPDIR/HOME 0 files after each run), no logs; stdout carries counts only. The input is never modified (its tree hash is unchanged after the run).
- Quarantined files are reported by SHA-256 with a reason and are not copied anywhere. `report.json` identifies inputs by hash, never by name.
- Output is deterministic: two runs with the same secret are byte-identical (194/194 dev files, 433/433 and 510/510 on the hidden-like sets). No network code in the run path.
- **Not built:** encryption at rest (AES-GCM) of intermediate data. Today all evidence stays in process memory and is never spilled to disk.

## 7. Known limitations (honest)
- **Rare-value protection is not built:** `policy.yaml` has `min_group_size` and `rare_action`, but no k-anonymity or rare-diagnosis coarsening step uses them yet, so the measured risk above is not reduced by suppression.
- **Gaps found on the hidden-like data:** FHIR narrative `text.div` keeps names (~40% of those leaks); village written after the district or after `Gram`/`r/o`; full-width, dotted and spaced phones; ordinal and Hindi-month DOBs; first names in prose (`<first name>'s father …`); a canary and two Devanagari names in file names; BOM-less UTF-16 text is decoded wrongly; Kruti Dev and mojibake text are copied instead of quarantined; one twin pair is merged (no first-name/sex veto).
- One patient can get several date shifts when its records are not all linked (dev recall 0.84), which weakens interval preservation across records.
- `report.json` lacks the `entities` field; 15 linked claims per hidden-like set (of 4,756 and 6,900) point to records where no pseudonym is written.
- Scores above are our estimates; the official attacker and evaluator are not public. We tested on Windows (Python 3.11); the Linux sandbox was not reproduced.
- **Next:** clean FHIR narrative, NFKC-normalise before ID detection, quarantine legacy-font/mojibake text, add the sex/first-name veto, then build k-anonymity coarsening.
