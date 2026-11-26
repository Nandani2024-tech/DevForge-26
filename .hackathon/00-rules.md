# 00-rules (Secret Wards, team Procrastinators). Imperative, one rule per line.
Stack: Python 3.10-3.12, pip, pytest. Run: `python main.py --input <dir> --output <dir>` with RAKSHA_SECRET set. Test: `python -m pytest` (pytest in requirements-dev.txt). Lint: none (README names pyflakes/pycodestyle, which are not in the manifest or Reuse Stack). Kit: ../Secret-Wards-ToolKit.
## 1. Before every task
- Read .hackathon/01-brief.md, 00-rules.md, MISTAKES.md, DECISIONS.md (if present) and the task's handoff prompt.
- State in 3 lines what you will do and which R-ids it serves.
## 2. Scope
- Build only what serves a MUST R-id (R1-R3, R5-R13, R15-R17, R19-R21, R23) in the current task. Anything else: stop and ask.
- No new features or dependencies unprompted. NICE items (R4, R14, R18, R22, R24, R25, N1-N9) wait for their own task.
## 3. Reuse
- Use only the Reuse Stack: stdlib, psutil 7.2.2, cryptography 50.0.2, rapidfuzz 3.14.5, jellyfish 1.2.1 (runtime); fhir.resources 8.3.0, Faker 40.63.0, pytest 9.2.0 (requirements-dev.txt only).
- Before writing more than 30 lines of generic code, check whether the stdlib or the Reuse Stack already does it. When adding a dependency, say why and wait for approval.
- Pin only releases with cp310 and cp312 wheels. No tomllib, no ExceptionGroup/except*, no other 3.11+-only stdlib.
## 4. Real implementation
- No hardcoded outputs, no special-casing of dev or test inputs, no stubs that return fake success. Every function uses its inputs.
- Never put dev names, IDs, header names or file names in code or config. Detect by context, column meaning and value shape (R22).
- Every word in a code or config word list needs a non-dev source (language, standard or schema, clinical vocabulary, OS). Never add a word because check_dev showed a leak or a false positive.
- Fix a false positive or a miss by changing the rule (shape, context or run-time evidence), and add a test with an invented word, absent from dev/input, that proves the rule generalises.
- Only Claude or the user, in review, edits tests/r22_vocab_allowlist.txt and the swap-test fixtures.
- Word lists are frozen by tests/vocab_lock.json. Only Claude or the user changes the lock, in review, with a non-dev source for each word.
- A guard test fails when its fixture is missing; it never returns early.
- Read RAKSHA_SECRET only from the environment. If it is missing, exit non-zero. Never write, print, log or hash-and-store it.
- Policy values come from config/policy.yaml. Other constants are named and live in one module.
- Paths via pathlib only. Never build paths with string concatenation or '\\'.
- Never modify the input folder. Open inputs read-only.
## 5. No patches
- State the root cause in one line before changing code.
- Forbidden: bare or swallowed exceptions, sleep for timing, commented-out failing code, disabled or weakened tests, duplicated code to dodge a refactor, workaround flags, raising the recursion limit to parse deep JSON.
## 6. Failure handling and privacy of logs
- A file that cannot be safely processed is quarantined with a content-free reason code. Never copy it into sanitized/.
- stdout, stderr, logs/ and report.json carry counts and reason codes only: never record values, file names, paths from the input, or exception messages that may echo content.
- Exit 0 only when sanitized/, report.json and records.jsonl are complete. Otherwise exit non-zero.
- Never fall back to fake or demo data.
## 7. Complexity and determinism
- State the Big-O of any function that touches collections or IO.
- Targets (04-idea-scope): per-file processing O(bytes) with precompiled regexes; linkage O(R·α(R)) via dict index + union-find; date shift O(dates); dev run < 20 s and peak tree RSS < 512 MB; hard limits 900 s / 4 GB / 2 CPU.
- No nested loops over records or files. Pass 1 keeps only evidence tuples, never whole files.
- Deterministic: iterate in sorted order, never iterate a set or dict for output order without sorting, no unseeded randomness, no time-based values in outputs, no multiprocessing or threads in the output path (the RSS sampler thread only reads).
- No network calls in the run path. Gazetteers and tables are vendored files.
## 8. Testing
- Every feature ships with pytest tests: happy path, edge cases (empty, truncated, deep JSON, wrong extension, encodings) and failure cases.
- Test oracles are the hand-derived cases in 02-domain.md sec 5 or new hand-derived ones. Never copy expected values from dev/truth.
- Integration tests run the pipeline on ../Secret-Wards-ToolKit/dev/input into a temp dir with RAKSHA_SECRET=practice, then call the kit's validate_output.py (must print CONTRACT OK), check_dev.py (assert the numbers meet the task target) and check_submission.py --run.
- Run the tests and show the output before declaring done. Never claim "tests pass" without running them.
## 9. UI
- No UI in the run path. The views are CLI outputs: counts only, no placeholder text.
- The optional demo view (N9, tools/ only, after the V0 gate) reads the output folder and shows loading, empty and error states from real data.
## 10. Stuck protocol
- After 2 failed attempts at the same problem, stop. Do not edit .hackathon/.
- Add a `STUCK:` section to your final report (symptom, what was tried, hypothesis) and propose 2 alternatives: an existing library and a simpler approach.
## 11. Deviation protocol
- If the spec or plan looks wrong or impossible, stop, name the R-id and the reason, and wait for a decision.
## 12. After each feature
- Do NOT commit or push. Leave all changes in the working tree; Claude verifies and commits.
- List the files changed and any shortcut taken (expected: none).
- If you replaced an approach, algorithm or library already in place, add `APPROACH CHANGED:` (was / now / why). Never reintroduce anything superseded in DECISIONS.md.
## 13. Allowed exceptions
- Only the user adds entries; each needs what, why, where and a removal plan.
- E1 (user-approved 2026-11-26): what: wards/cli.py strips one pair of outer single quotes from --input/--output, only when os.name == "nt" | why: the kit's check_submission.py uses POSIX shlex.quote with shell=True, so cmd.exe passes literal quotes on Windows dev machines | where: wards/cli.py, one function | removal: delete it once check_submission runs under WSL/Linux only.
