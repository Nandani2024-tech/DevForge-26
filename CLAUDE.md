# Hackathon workflow
- Start every session by reading `.hackathon/STATE.md`. Do not scan the whole repo: use `git diff`, `git log`, `git ls-files` and the files the task names.
- `01-ps.md` and `04-idea-scope.md` are locked. Change them only through `/pivot-check`, with the user's approval.
- Antigravity writes the feature code. Claude plans, reviews, tests and commits. Do not write feature code unless the user asks.
- Commit only through `/ship`, after its gates pass. Never push, never `--no-verify`, never `--amend`, never `git add -A`.
- `.hackathon/` is never staged by `/ship` and is not gitignored (Antigravity must be able to `@`-mention it). Ignore it in every `git status` cleanliness check. The user commits it once at the end if they want.
- Never hardcode, special-case or patch to make something pass. Find and fix the root cause. Prefer an existing library over custom code (see `.hackathon/03-prior-art.md`).
- Report honestly: say `NOT RUN` or `unverified` when something could not be checked.

## MISTAKES rule (applies to every skill and every gate)
Whenever any check catches a problem (a gate FAIL or WARN finding, a failing test that is a code bug, a scope violation, drift, a stuck loop, a failed commit), log it in `.hackathon/MISTAKES.md`. Do not wait for the user to ask.
- If the file is missing, create it with:
  `# MISTAKES (read before every task)` and the header row `date | source | R-id | symptom | root cause | rule to prevent it | seen`
- One line per root cause: `<YYYY-MM-DD HH:MM> | <skill or gate> | <R-id or -> | <symptom> | <root cause> | <rule> | 1`
- Before appending, look for a line with the same root cause. If found, do not add a duplicate: increase its `seen` count and update its date. A `seen` of 2 or more means the rule is being ignored: say so in the report and recommend `/unstick`.
- Preventive entries (from research skills) use `(preventive)` as the symptom.
- Never delete or rewrite other entries.

## DECISIONS rule (approach changes)
Whenever an approach, algorithm, library, data model or architecture that was already chosen or built is replaced by a better one, append an entry to `.hackathon/DECISIONS.md` (create it with the header `# DECISIONS (approach changes, newest last)` if missing). Never edit old entries; a reversal is a new entry.
~~~
### D<n> | <YYYY-MM-DD HH:MM> | <R-ids> | <short title>
- Was: <old approach> (commit <hash> or "not built")
- Now: <new approach>
- Why: <evidence: test result, measurement, drift, blocker, judge feedback>
- Trigger: <skill that found it: pivot-check / unstick / reuse-check / ship / user>
- Obsolete: <files or code to remove, or "none">
- Lesson: <one line>
~~~
Superseded approaches listed here must not be reintroduced. `/handoff-prompt` passes them to Antigravity as "do not use".
