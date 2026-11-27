# Secret Wards: Team Procrastinators

**Track 3 · Secret Wards** · Members: Ayush Kumar Patra, Nandani Kumari

An offline, CPU-only privacy firewall for messy multi-hospital Indian clinical records (CSV, TSV,
JSON, FHIR R4 and free text, in English, Hindi and Hinglish). It removes names, IDs, contacts and
addresses, keeps medical values exactly, and gives each patient one keyed pseudonym across files,
hospitals and scripts.

The 2-page Project Brief with all measured numbers is in [`docs/brief.pdf`](docs/brief.pdf)
(source: [`docs/PROJECT_BRIEF.md`](docs/PROJECT_BRIEF.md)).

## Setup

Targets Python 3.10–3.12 (no 3.11+-only features used); developed and tested only on Python 3.11, Windows 11.

```bash
pip install -r requirements.txt          # runtime: psutil only
pip install -r requirements-dev.txt      # tests: pytest, fhir.resources
```

## Run

```bash
RAKSHA_SECRET=<secret> python main.py --input <input_dir> --output <output_dir>
```

On Windows PowerShell: `$env:RAKSHA_SECRET="practice"` first. This is the same command as in
[`raksha.toml`](raksha.toml), where the evaluator fills in `{input}` and `{output}`. The secret is
read from the environment only. No network access is needed. The program writes only into
`<output_dir>`:

```
<output_dir>/
├── sanitized/      cleaned mirror of the input (same folders, formats; files renamed only if the name holds PII)
├── report.json     every input file by SHA-256, its status, honest counts, timing, peak memory
└── records.jsonl   one line per record: input locator + pseudonym (or null when evidence is weak)
```

Exit code 0 means the release is complete; a missing secret or an invalid policy exits non-zero.

## Architecture

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

The key idea is **two passes**. Pass 1 reads the whole input and collects evidence (names from
structured name columns, ID cores, DOBs, relatives) and links records. Pass 2 cleans every channel
with that run-time evidence, so a name first seen in a registration CSV is also removed from
free-text notes, file names, JSON keys and base64 attachments.

## How each part works

| Part | Module(s) | What it does |
|---|---|---|
| Ingestion | `wards/ingest.py` | Decodes UTF-8, UTF-8-BOM, UTF-16 (with BOM) and cp1252; detects JSON by content (e.g. JSON behind a `.csv` name). Files we cannot process safely are quarantined with a reason code (`unsupported_format`, `invalid_json`, `invalid_csv`, `deep_json`, `empty_file`, `undecodable_text`) and never copied to the output. |
| Structured detection | `wards/columns.py`, `wards/slots.py` | Classifies CSV columns and JSON keys by meaning *and* by a capped vote over their values (ID shape, address cues, age shape, run-time names), so renamed headers such as `Contact#` or `Gram/Mohalla` still work. Finds the patient-ID slot where the pseudonym is written. |
| Identifiers | `wards/patterns.py` | Aadhaar (masked too), ABHA number/address, PAN, UHID/MRN/IPD, insurance IDs, emails and phones by shape in context; Devanagari digits are normalised. The Aadhaar Verhoeff checksum only raises confidence (21% of practice Aadhaar values fail it). |
| Names (3 scripts) | `wards/names.py` | Labels, relations (S/o, D/o, W/o, C/O), honorifics and Hindi/Hinglish subject clues in Latin and Devanagari, plus the Pass 1 names. A protect mask keeps doctors, `C/O` complaints, `K/C/O`, `H/O`, doses such as `1-0-1`, eponyms, wards and ASHA workers. |
| Hidden channels | `wards/channels.py`, `wards/pipeline.py` | File and folder names (renames are mapped in `report.json`), CSV headers, JSON keys, export metadata, FHIR `Reference.display`, and base64 attachments (decoded, cleaned, re-encoded in the same variant). |
| Linkage & pseudonyms | `wards/linkage.py`, `wards/pseudo.py` | Union-find over strong IDs (Aadhaar, ABHA, PAN, phone, UHID/IPD digit cores), name+DOB and name+relative edges. Names are normalised across case, honorifics, word order and script (own Devanagari→Latin table with schwa deletion). A conflict guard rejects clusters with two DOBs or two values of a lifelong ID; weak evidence gives `patient: null`. Pseudonym = `PSN-` + HMAC-SHA256(`RAKSHA_SECRET`, canonical cluster key). |
| Privacy layer | `wards/dates.py`, `wards/generalise.py` | One secret per-patient date shift in ±[7, 180] days, format kept, intervals and stay length exact. Ages to 5-year bands (top-coded 85+). Village, house, locality and landmark removed; tehsil and district kept; PIN cut to its 3-digit prefix. |
| Policy | `config/policy.yaml`, `wards/config.py` | All privacy settings in one file; a missing or invalid policy fails closed (non-zero exit). |
| Export & report | `wards/writers.py`, `wards/resources.py` | Deterministic UTF-8 writers; peak memory measured over the whole process tree with `psutil`. |

## Security design

- `RAKSHA_SECRET` comes only from the environment and is never written to the output, logs,
  stdout/stderr or temp folders (checked with random secrets in our rehearsal tool).
- Pseudonyms and date shifts are keyed HMAC-SHA256, not plain hashes; a different secret changes
  every pseudonym and shift.
- Nothing is written outside the output folder: no temp or spill files, no logs. stdout prints
  counts only. The input is never modified.
- `report.json` identifies inputs by SHA-256, never by file name. Quarantined files are listed with
  a reason and are not copied anywhere.
- Output is deterministic: the same input and secret give byte-identical `sanitized/` and
  `records.jsonl`. No network code in the run path.
- **Not built:** encryption at rest (AES-GCM) of intermediate data. All evidence stays in process
  memory and is never written to disk.

## Models

**No machine-learning models and no LLMs are used.** Detection and linkage are rule-based. The only
runtime dependency is `psutil` (memory measurement).

## Measured results

Measured on commit `579de09` with the kit's `check_dev.py` and our tools (details in the brief):

| | dev (practice) | renamed dev | hidden_normal | hidden_chaos |
|---|---|---|---|---|
| personal data leaked | 0.1% | 0.3% | 2.3% | 2.5% |
| canaries found | 0 of 4 | 0 of 4 | 1 of 6 | 1 of 6 |
| medical values kept | 100.0% | 100.0% | 99.5% | 99.5% |
| linking F0.5 (wrong merges) | 0.96 (0) | 0.96 (0) | 0.97 (0) | 0.94 (1) |
| run time / peak memory | 2.8 s / 39 MB | 2.7 s / 39 MB | 16.7 s / 182 MB | 19.3 s / 183 MB |

*Renamed dev* comes from `tools/mutate_dev.py` (renamed headers and keys, rewritten dates, invented
names). *hidden_normal* and *hidden_chaos* come from our own independent seeded generator, written
from the public docs, with new hospitals, names and formats: data we did not tune on.

## Tests and measurement tools

The kit (`Secret-Wards-ToolKit`) must sit next to this repository; some tests use it.

```bash
python -m pytest tests                        # 132 tests
python ../Secret-Wards-ToolKit/validate_output.py --input <input_dir> --output <output_dir>
python ../Secret-Wards-ToolKit/check_dev.py --output <output_dir>
```

`tools/` holds measurement-only scripts (not used by `main.py`): `rehearse_eval.py` (fresh-clone
rehearsal of the evaluator's 3 runs), `estimate_score.py` (our score estimate), `mutate_dev.py`
(renamed-format copy of the practice data). See [`tools/VERIFY.md`](tools/VERIFY.md).

## Known limitations

- **Rare-value protection is not built.** `policy.yaml` has `min_group_size` and `rare_action`, but no
  k-anonymity or rare-diagnosis step uses them yet. Our local profile attacker still re-identifies
  most patients from age band, sex, tehsil, district, PIN prefix and diagnosis.
- On the hidden-like data: names in FHIR narrative `text.div`; villages after the district or after
  `Gram`/`r/o`; full-width, dotted and spaced phones; ordinal and Hindi-month DOBs; first names in
  prose; a canary and Devanagari names in file names; BOM-less UTF-16 text decoded wrongly; Kruti Dev
  and mojibake text copied instead of quarantined; one twin pair merged.
- A patient whose records are not all linked can get more than one date shift.
- `report.json` has no `entities` field yet.
- All scores are our own estimates; tested on Windows only, not in the Linux sandbox.
