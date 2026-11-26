---
name: drift-check
description: Check, from git and the progress log, whether the work still serves the locked spec and MUST list. Flags scope creep, missing MUST items, contradictions with non-goals, repeated mistakes and unmet switch triggers. Read-only.
disable-model-invocation: true
---

Input: `$ARGUMENTS` (optional: a commit range). Default range: the `checked:` hash in `.hackathon/DRIFT.md` to HEAD; if `DRIFT.md` does not exist, the first commit (`git rev-list --max-parents=0 HEAD`) to HEAD.

Read ONLY: `.hackathon/01-ps.md`, `04-idea-scope.md` (Decision, spike, MUST/NICE/DROP, targets, Kill list), `PROGRESS.md`, `MISTAKES.md`, `STATE.md`, `DECISIONS.md` (if present), and the previous `DRIFT.md`. Use `git log --oneline --stat <range>` and `git diff --stat <range>`; open diffs only for files you cannot classify from names and messages. Do NOT scan the repo. Do NOT edit anything except `DRIFT.md`, `STATE.md` and `MISTAKES.md` (append only).

Checks:
1. **R-id coverage:** for each commit and changed file in the range, map it to an R-id or to `none`. Work mapping to `none` is unplanned: list it with the lines changed.
2. **Priority balance:** what share of effort went to MUST vs NICE vs DROP vs unmapped. Flag NICE work done while any MUST is not started or only `partial`.
3. **Spec contradictions:** anything built that conflicts with Non-goals, the Kill list, a Hard constraint, or a quality target in `01-ps.md`.
4. **Core flow:** is the end-to-end Core user flow working? List which steps work and which don't. A working thin slice beats polished parts.
5. **Spike:** has the riskiest-assumption spike been run? What was the result? If never run while other work is underway, flag it.
6. **Approach and switch trigger:** is the code still the chosen approach, or has it silently turned into Plan B or something else? An approach change recorded in `DECISIONS.md` is approved, not drift. A change visible in git but missing from `DECISIONS.md` is a silent approach change: flag it and list it under corrective actions as "record with /decision". Evaluate the switch trigger from `04-idea-scope.md` against the evidence. State `fired`, `not fired` or `can't tell`.
7. **Stuck signals:** same files reverted or rewritten 3+ times, churn ratio rising, entries in `MISTAKES.md` repeating the same root cause, `hardcode-check` failing repeatedly.
8. **Quality gates:** latest `hardcode-check`, `test-from-codebase` and `feature-log` keys in `STATE.md`: did they run for the current HEAD?
9. **Honest progress:** MUST done-verified / MUST total, copied from `PROGRESS.md`. If `PROGRESS.md` is missing, say features are unlogged.

Verdict:
- `ON TRACK`: no unplanned work beyond trivial, no MUST starved, no contradictions.
- `DRIFTING`: unplanned work, NICE before MUST, an unrun spike, or rising churn.
- `OFF COURSE`: contradicts the spec, the switch trigger fired, or the core flow is broken with no path to fix it.
Be honest. Do not soften a verdict to be reassuring, and do not invent drift.

Write `.hackathon/DRIFT.md` (overwrite, max 40 lines):
- Line 1: `checked: <HEAD hash> | <date> | verdict: <verdict>`
- Coverage table: `R-id | priority | status | evidence`
- Unplanned work: `file or commit | lines | why it is out of scope | revert or fold into R-id`
- Contradictions, spike status, switch-trigger status, stuck signals, gate status
- Corrective actions: max 3, specific, ordered. Examples: "stop X, resume R3", "revert commit abc", "run the spike".
- Last line: what you could not verify.

Also: if the verdict is DRIFTING or OFF COURSE, log each cause in `.hackathon/MISTAKES.md` per the MISTAKES rule in `CLAUDE.md` (source `drift-check`).

Finish:
1. Set `build.drift-check: <verdict> @ <short hash>` in `.hackathon/STATE.md`.
2. Print the verdict, the coverage table, unplanned work, and the corrective actions.
3. End with: `Next: /pivot-check` (DRIFTING with structural causes, or OFF COURSE), else `Next: /handoff-prompt` (follow the corrective actions first).