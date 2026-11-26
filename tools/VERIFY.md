# VERIFY: reproduce the checklist proof and the score estimate

Measured 2026-11-27 on commit `6319c85` (origin/main), Windows 11, system Python 3.11.0
(no venv active; pytest 9.0.2 installed vs 9.2.0 pinned in requirements-dev.txt).
All scripts in `tools/` are measurement only: they are not imported by `main.py` or `wards/`
and add no runtime dependency (they use the stdlib + psutil, which is already pinned).
Every score below is an **ESTIMATE**: the organisers' evaluator is not published.

Run everything from the repo root in PowerShell:

```powershell
cd C:\Devforge
$KIT = "..\Secret-Wards-ToolKit"
$env:PYTHONIOENCODING = "utf-8"          # the kit prints emoji; cp1252 consoles crash without it
$W  = "$env:TEMP\sw_rehearsal"           # rehearsal on dev/input
$M  = "$env:TEMP\sw_mutated"             # mutated copy of dev/input + truth
$WM = "$env:TEMP\sw_rehearsal_mut"       # rehearsal on the mutated copy
```

---

## Step 0: preflight (read-only)

```powershell
(Get-ChildItem -Recurse -File "$KIT\dev\input").Count
```
Expected: `200`

```powershell
"dev\truth\truth.json","dev\attacker\registry.csv","dev\attacker\known_facts.jsonl","validate_output.py","check_dev.py","check_submission.py","docs\SCORING.md","docs\ATTACKS.md","docs\SANDBOX.md","scoring.toml" | % { "{0,-32} {1}" -f $_, (Test-Path "$KIT\$_") }
```
Expected: every line ends in `True`. (registry.csv has 241 lines = header + 240 people; known_facts 18 lines.)

```powershell
git -C $KIT config core.autocrlf
```
Expected: `false` (or empty output; empty means not set, which on this machine also means no conversion).

```powershell
python -c "import json,hashlib,pathlib;t=json.load(open(r'$KIT\dev\truth\truth.json',encoding='utf-8'));print(sum(hashlib.sha256((pathlib.Path(r'$KIT\dev\input')/p).read_bytes()).hexdigest()==f['sha256'] for p,f in t['files'].items()),'of',len(t['files']))"
```
Expected: `200 of 200`

```powershell
python --version; python -c "import sys;print(sys.prefix==sys.base_prefix)"; python -m pip show psutil pytest | Select-String "^(Name|Version)"
```
Expected: `Python 3.11.0`, `True` (= no venv), psutil `7.2.2`, pytest `9.0.2` (pin says 9.2.0: noted, not changed).

```powershell
git log -1 --format="%h %ci %s"; git status -sb; git ls-remote origin main
```
Expected: `6319c85 ...`, `## main...origin/main` plus `?? docs/` and `?? tools/` (both untracked by choice), remote `6319c85c...`.

---

## Step 1: checklist (START_HERE.md section 8)

### Item 1: check_submission prints READY TO SUBMIT
```powershell
python "$KIT\check_submission.py" --repo . --input "$KIT\dev\input" --run
```
Expected: `READY TO SUBMIT (check the 1 ⚠️ notes)`. The one warning is `README.md found (62 words)`.
Caveat: it also prints `✅ Project Brief PDF found: .hackathon\ps\overview.pdf`. That file is the
organisers' problem statement and is gitignored (`git check-ignore -v .hackathon/ps/overview.pdf`
prints `.gitignore:1:.hackathon/ps/*.pdf`), so it is a false positive: we have no Brief PDF.

### Item 2: raksha.toml at the root
```powershell
Get-Content raksha.toml
```
Expected:
```
[submission]
name  = "Procrastinators"
setup = "pip install -r requirements.txt"
run   = "python main.py --input {input} --output {output}"
```

### Items 3-8: fresh-clone rehearsal (setup, 3 runs, every side channel)
```powershell
python tools\rehearse_eval.py --kit $KIT --work $W
```
What it does (see the docstring): `git clone --depth 1` of origin/main into `$W\repo` (never the
working tree) -> `python -m venv .venv` -> the raksha.toml `setup` command with `.venv\Scripts`
first on PATH (timed, 30-min limit) -> copies dev/input to `$W\input` and sets every file
read-only -> for runs A1, A2 (same secret) and B (other random secret): fresh empty
`out_*`, `tmp_*` (TMP/TEMP/TMPDIR) and `home_*` (HOME/USERPROFILE), only the SPEC env vars
(`RAKSHA_SECRET/INPUT/OUTPUT`, `RAKSHA_CPUS=2`, `OMP/MKL/OPENBLAS/NUMEXPR_NUM_THREADS`,
`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`) plus the minimum Windows needs (SYSTEMROOT,
COMSPEC, PATH...), runs the raksha.toml `run` command through the shell with a 50 ms
whole-process-tree RSS sampler.

Expected key lines:
```
clone 6319c85  setup 16.3 s exit 0
run A1: exit 0 ok wall 2.27 s  peak 38.3 MB  tmp/home files 0  stdout: ['files 200 sanitized 194 quarantined 6 records 823 linked 681']
run A2: exit 0 ok wall 1.98 s  peak 36.9 MB ...
run B: exit 0 ok wall 2.07 s  peak 37.5 MB ...
determinism: {'sanitized_files': 194, 'identical': 194, 'only_in_one': 0, 'records_identical': True, 'share': 1.0}
A vs B: 0/681 same PSN; 73/1333 date tokens equal
side channels: {'report.json': 0, 'records.jsonl': 0, 'logs/': 0, 'other_output_files': 0, 'stdout/stderr': 0, 'TMPDIR/HOME': 0, 'output_file_names': 0}
validate_output: ['CONTRACT OK']
report honesty: {... 'files_sanitized': 194, 'files_quarantined': 6, 'records_processed': 823, 'records_linked': 681} vs {same}
network scan hits: []
READY TO CONNECT: yes
```
(timings vary by a few tenths of a second). The 73 equal date tokens are dates that are left
unshifted in both runs (for example clean documents and non-patient dates); among dates that
were actually shifted, 0 of 1,259 are equal across secrets (see the estimate, A7).

Details are in `$W\rehearsal.json`. Useful one-liners:
```powershell
python -c "import json;r=json.load(open(r'$W\rehearsal.json'));print(r['setup']);print(r['unlinkability']['examples']);print(r['unlinkability']['date_pair'])"
```
Expected: `{'exit': 0, 'seconds': 16.3, ..., 'freeze': ['psutil==7.2.2']}`, three records with
different A/B PSNs (e.g. `arogya_claims.csv row:0  PSN-CPG22T vs PSN-7JXQV1`; your PSNs differ
because the secrets are random per rehearsal), and one date pair from `lab/bulk_lab_export.json`.

Positive control (proves the PII scanner is not blind: it must find PII in the RAW input):
```powershell
python -c "import sys;sys.path.insert(0,'tools');import sw_common as C,pathlib;k=pathlib.Path(r'$KIT');s=C.SideChannelScanner(C.load_truth(k));print(sum(len(s.scan_text(C.read_any(p),'x')) for p in (k/'dev/input').rglob('*') if p.is_file()))"
```
Expected: `1099` (lines with a direct identifier or full name in the raw input). Our outputs' side channels: 0.

Network: static scan of the run path (`main.py`, `wards/*.py`) for socket/urllib/http/requests/ssl/
asyncio/... imports or calls:
```powershell
Select-String -Path main.py,wards\*.py -Pattern '^\s*(import|from)\s+(socket|urllib|http|requests|ftplib|smtplib|ssl|asyncio|xmlrpc|telnetlib|websocket|aiohttp|httpx|urllib3)\b','socket\.','urlopen\('
```
Expected: no output.

### Item 4 standalone (validate_output)
```powershell
python "$KIT\validate_output.py" --input "$W\input" --output "$W\out_A1"
```
Expected: `CONTRACT OK`

### Item 7 standalone (secret never written)
The rehearsal searched every file under `out_*`, `tmp_*`, `home_*` and the captured
stdout/stderr for the random secret (UTF-8 and UTF-16) and in file names. Expected in
`rehearsal.json`: `"secret_hits": []`.

### Item 9: no LLM / no model > 50M parameters
```powershell
Get-Content requirements.txt; Get-Content requirements-dev.txt
```
Expected: `psutil==7.2.2` only (runtime, process-memory measurement); dev adds `pytest==9.2.0`.
No model files, no ML packages. README does **not** yet state "no models are used" (R23 open).

### Item 10: README sections
```powershell
(Get-Content README.md -Raw).Split(" `n`t",[StringSplitOptions]::RemoveEmptyEntries).Count; Select-String -Path README.md -Pattern '^#'
```
Expected: `62` words; headings `## Setup`, `## Run`, `## Test` only. Missing: architecture
diagram, how each part works, security design, known limitations, model declaration -> FAIL.

### Item 11: 2-page Project Brief PDF
```powershell
git ls-files "*.pdf"; Get-ChildItem -Recurse -Filter *.pdf -File | ? { $_.FullName -notmatch '\\.hackathon\\ps\\' }
```
Expected: no output -> FAIL / NEEDS USER.

### Item 12: data we did not tune on (mutated copy)
```powershell
python tools\mutate_dev.py --kit $KIT --out $M
python tools\rehearse_eval.py --kit $KIT --work $WM --input "$M\input" --truth "$M\truth\truth.json"
python "$KIT\check_dev.py" --output "$WM\out_A1" --truth "$M\truth\truth.json"
python tools\estimate_score.py --kit $KIT --work $WM --input "$M\input" --truth "$M\truth\truth.json"
```
Expected: `mutated set: {'files': 200, 'renamed_headers': 77, 'renamed_keys': 258, 'dates_rewritten': 933, 'renamed_files': 9, 'unchanged_files': 8} | invented names: 125 | name replacements: 5931`,
`READY TO CONNECT: yes`, check_dev `234 of 3230 pieces still visible (7.2% leaked)`,
`PATIENT LINKING: precision 1.00, recall 0.84, F0.5 0.96`, estimate `TOTAL ESTIMATE 50.98`.

### Tests and check_dev on dev/input
```powershell
python -m pytest -q
python "$KIT\check_dev.py" --output "$W\out_A1" --show 10
```
Expected: `84 passed`; check_dev `41 of 3230 pieces still visible (1.3% leaked)`,
`CANARIES: 1 of 4`, `MEDICAL DATA KEPT: 4854 of 4855`, `precision 1.00, recall 0.84, F0.5 0.96`
(`wrongly merge: 0`), `RAW COPIES: 0`. (`--show 10` prints the leaked text itself; do not paste it anywhere.)

---

## Step 2: score estimate
```powershell
python tools\estimate_score.py --kit $KIT --work $W --json "$W\estimate.json"
```
Expected last lines:
```
  privacy                25   13.56   (score 0.542)
  detection              20   19.75   (score 0.987)
  utility                20   17.95   (score 0.897)
  identity_resolution    15   13.31   (score 0.887)
  integrity              10    9.91   (score 0.991)
  performance            10   10.00   (score 1.000)
  penalties            -    -28.00
  TOTAL ESTIMATE            56.48
```
Every intermediate number (per-type recall, trap groups, attack results per release, penalty
counts) is printed above that table and saved in `$W\estimate.json`; the interpretive choices
are in its `assumptions` list.

---

## NEEDS USER

1. **Wi-Fi-off run (item 3).** Turn Wi-Fi off (and unplug Ethernet), then:
   ```powershell
   $env:RAKSHA_SECRET = "practice"
   Remove-Item -Recurse -Force "$env:TEMP\sw_offline" -ErrorAction SilentlyContinue
   python main.py --input "$KIT\dev\input" --output "$env:TEMP\sw_offline"; "exit $LASTEXITCODE"
   python "$KIT\validate_output.py" --input "$KIT\dev\input" --output "$env:TEMP\sw_offline"
   ```
   Expected: `files 200 sanitized 194 quarantined 6 records 823 linked 681`, `exit 0`, `CONTRACT OK`.
   Then turn the network back on.
2. **README (item 10)**: add architecture diagram, how each part works, security design, known
   limitations, and the line "no models are used" (R23).
3. **Project Brief PDF (item 11)**: 2 pages from `$KIT\brief\`, with today's check_dev numbers
   (1.3% leaked, 1/4 canaries, 4854/4855 medical values, F0.5 0.96, 0 raw copies).

## NOT TESTABLE HERE (Linux-only sandbox) and how to test each

| Check | How to test |
|---|---|
| network namespace (connections fail) | WSL Ubuntu: `RAKSHA_SECRET=practice unshare --user --map-root-user --net python3 main.py --input ../Secret-Wards-ToolKit/dev/input --output /tmp/o && echo ok` |
| tmpfs masks hide truth / other folders | WSL: `unshare --user --map-root-user --mount --net sh -c 'mount -t tmpfs none ../Secret-Wards-ToolKit/dev/truth && mount -t tmpfs none ../Secret-Wards-ToolKit/dev/attacker && RAKSHA_SECRET=practice python3 main.py --input ../Secret-Wards-ToolKit/dev/input --output /tmp/o2'` (our code never reads truth, so the run must still succeed) |
| CPU affinity 2 cores | WSL: `taskset -c 0,1 env RAKSHA_CPUS=2 RAKSHA_SECRET=practice python3 main.py ...` and compare wall time |
| /proc hidden (`--pid --fork --mount-proc`) | WSL: `unshare --user --map-root-user --pid --fork --mount-proc --net python3 main.py ...` |
| all of the above at once (organisers' "full" level) | WSL or a GitHub Actions `ubuntu-latest` job: `unshare --user --map-root-user --net --mount --pid --fork --mount-proc` around the run command; on Ubuntu 24.04+ first `sudo sysctl kernel.apparmor_restrict_unprivileged_userns=0` |
| read-only input enforced by a read-only mount | WSL: `chmod -R a-w` on a copy of the input, run, then `sha256sum` before/after (Windows used the read-only attribute) |
