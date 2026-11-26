---
name: complexity-audit
description: "Audit changed code against the Big-O and performance targets in the spec: static analysis of the diff plus a scaled-input measurement where possible. Flags only misses, with a fix prompt. Read-only."
disable-model-invocation: true
---

Input: `$ARGUMENTS` (optional: a feature, R-ids, a commit range, or `WORKTREE`). If `$ARGUMENTS` is `WORKTREE` (set by /ship), the change set is the uncommitted work: `git diff HEAD` plus untracked non-ignored files (`git ls-files --others --exclude-standard`), excluding `.hackathon/`; treat every line of an untracked file as added. Otherwise the default range is `HEAD~1..HEAD`.

Read ONLY: the complexity and performance targets in `.hackathon/04-idea-scope.md`, the quality targets in `01-ps.md` (section 6), `02-domain.md` section 4 (expected complexity per method), the run and test commands in `00-rules.md`, and the changed files in the range. Do NOT scan the repo. Do NOT edit project code.

Steps:
1. **List functions touched** that handle collections, DB, files, network, or recursion. Ignore trivial code.
2. **Static analysis, per function:** time and space complexity with the reasoning in one line. Check specifically for: nested loops over input-sized data, queries or API calls inside loops (N+1), repeated sorting or full scans where an index, hash or heap would do, quadratic string or list building, loading everything into memory, missing pagination or streaming, unbounded caches, repeated recomputation (missing memoization), blocking IO in a hot path, and missing DB indexes for queried fields.
3. **Compare to targets:** each function vs the target for its R-id. Verdict: `meets`, `unknown`, `misses`.
4. **Measure (when it can run):** in a scratch directory (`.hackathon/bench/`, never in project source), write a small script that calls the real function or endpoint at 3 input sizes (e.g. 1x, 10x, 100x of the expected size from the PS, capped to something that finishes in about a minute). Use realistic data (the PS dataset or generated data with the real shape). Record time and, if cheap, peak memory. Estimate the growth rate from the three points: ~linear, n log n, quadratic, worse. If it cannot run, write `not measured` and why.
5. **Judge:** the static estimate and the measurement must agree. If they disagree, say so and trust the measurement.

Rules:
- Flag only misses and `unknown` on MUST paths. Do not nitpick micro-optimizations or small constant factors.
- Do not recommend premature optimization: if the input size from the PS makes the current approach fine, say `meets` and why.
- Prefer fixes with an existing library, data structure or index over custom algorithms.
- Be honest about what was and was not measured.

Write `.hackathon/COMPLEXITY.md` (overwrite, max 40 lines):
- Header: range, date, verdict `PASS` / `WARN` / `FAIL` (FAIL if a MUST path misses a target).
- Table: `function (file:line) | R-id | time | space | target | measured | verdict`.
- Findings: for each miss: cause, root-cause fix (data structure, index, batching, pagination, library), expected new complexity.
- If WARN or FAIL: a paste-ready **Antigravity fix prompt** (read-first line, the function, the problem, the required complexity, the fix approach, "keep behavior and tests identical, add a scale test, no special-casing").
- Last line: what was not verified.

Also: log every `misses` finding in `.hackathon/MISTAKES.md` per the MISTAKES rule in `CLAUDE.md` (source `complexity-audit`; dedupe by root cause, bump `seen`).

Finish:
1. Set `build.complexity-audit: <verdict> @ <short hash>` in `.hackathon/STATE.md`.
2. Print the verdict, the table, and the fix prompt if any.
3. End with: `Next: paste the fix prompt into Antigravity, then re-run /complexity-audit` (WARN/FAIL), else `Next: /feature-log`