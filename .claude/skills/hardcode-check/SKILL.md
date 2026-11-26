---
name: hardcode-check
description: Audit the recent git diff for hardcoding, static fake data, patches and band-aids instead of real root-cause solutions. Read-only. Run after every feature and before the freeze.
disable-model-invocation: true
---

Input: `$ARGUMENTS` (optional: a commit range, a feature name, or `WORKTREE`). If `$ARGUMENTS` is `WORKTREE` (set by /ship), the change set is the uncommitted work: `git diff HEAD` plus untracked non-ignored files (`git ls-files --others --exclude-standard`), excluding `.hackathon/`; treat every line of an untracked file as added. Otherwise the default range is: `base` from `.hackathon/PROGRESS.md` to HEAD; if there is no `base` or that range is empty, `HEAD~1..HEAD`. Read `.hackathon/00-rules.md` (including Allowed exceptions) and the R-ids in `.hackathon/01-ps.md` for the feature. Do NOT scan the whole repo. Do NOT edit any code.

Method:
1. `git diff <range>` (added lines only) for first-pass pattern search, then read only the flagged hunks and their surrounding function for judgment.
2. Treat each item below as a check. A match is a finding only if it replaces real behavior. Constants in a config or constants file, enums, test fixtures inside test folders, and Allowed exceptions are NOT findings.

Checks (severity in brackets):
- **A. Fake data:** functions returning literals, lists or dicts that should come from an API, DB, file or user input. UI values, charts or tables with static numbers. [BLOCKER]
- **B. Silent fallback:** on failure, code quietly serves mock or demo data or a default success. [BLOCKER]
- **C. Special-casing:** `if input == "<sample>"`, branches keyed on demo or test values, outputs tailored to the example in the PS. [BLOCKER]
- **D. Ignored inputs:** functions or endpoints whose parameters are unused or whose output is the same regardless of input. [BLOCKER]
- **E. Patches:** empty or broad try/except, `sleep` or retry loops hiding a race, commented-out failing code, `TODO`/`FIXME`/`pass`/`NotImplemented` left in delivered paths, flags that bypass a bug. [BLOCKER if in a MUST path, else WARN]
- **F. Test dishonesty:** skipped or disabled tests, tests with no assertions, assertions copied from the implementation's output, mocks that mock the thing under test, deleted failing tests. [BLOCKER]
- **G. Hardcoded config:** URLs, keys, ports, paths, model names, thresholds, magic numbers inline instead of config or named constants. Secrets in code are always a BLOCKER. [WARN, BLOCKER for secrets]
- **H. Duplication:** copy-pasted logic that should be one function. [WARN]
- **I. Reinvented wheel:** more than 30 new lines of generic logic that a library from the Reuse Stack (or a well-known one) already provides. [WARN]
- **J. Complexity smell:** nested loops over unbounded input, queries inside loops, loading everything into memory. [WARN, BLOCKER if it breaks a stated target]

Write `.hackathon/REVIEW.md` (overwrite, max 40 lines):
- Header: range, date, verdict `PASS` / `WARN` / `FAIL` (FAIL if any BLOCKER).
- Findings table: `id | file:line | check letter | short snippet | why it is a patch or hardcode | root-cause fix | severity`.
- If FAIL or WARN: an **Antigravity fix prompt**, ready to paste. It must name each finding, demand the root-cause fix, forbid new workarounds, and ask for a re-run of the tests.
- If PASS: one line saying what was checked. Do not invent findings to look thorough.

Also:
- Log every BLOCKER and WARN finding in `.hackathon/MISTAKES.md` per the MISTAKES rule in `CLAUDE.md` (source `hardcode-check`; dedupe by root cause, bump `seen`).
- Set `build.hardcode-check: <verdict> @ <short commit hash>` in `.hackathon/STATE.md`.
- Be honest: a pattern search can miss things. In the last line of the review, say what you could not verify.

Finish: print the verdict, the table, and the fix prompt. End with: `Next: paste the fix prompt into Antigravity, then re-run /hardcode-check` (on FAIL) or `Next: /feature-log` (on PASS/WARN).