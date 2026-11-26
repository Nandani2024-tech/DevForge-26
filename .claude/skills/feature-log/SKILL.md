---
name: feature-log
description: After each feature, record what was actually built, what was reverted or churned, evidence it works, and honest progress against the MUST list. Use argument `status` for the dashboard only.
disable-model-invocation: true
---

Input: `$ARGUMENTS` = the feature name and R-ids (e.g. `R2 search endpoint`), or `status`.

Read ONLY: `.hackathon/PROGRESS.md` (if it exists), the MUST list and Build order hint in `.hackathon/04-idea-scope.md`, the acceptance tests for those R-ids in `.hackathon/01-ps.md`, and the test command in `.hackathon/00-rules.md`.

## Mode `status`
Print the dashboard from `PROGRESS.md` (recompute it first, see below). Do not add an entry. Stop.

## Mode feature
1. `git status --short -- . ':(exclude).hackathon'` (`.hackathon/` is never committed, so ignore it). If there are uncommitted changes, stop and tell the user to run `/verify-commit` (or commit first). When called from `/verify-commit` the commit already exists and the tree is clean.
2. Set `base` = the `base:` hash in `PROGRESS.md`. If none, use the first commit (`git rev-list --max-parents=0 HEAD`).
3. Gather facts (git only, no repo scan):
   - `git log --oneline --format="%h %ad %s" --date=iso <base>..HEAD`
   - `git diff --numstat <base>..HEAD`
   - commits whose message contains "revert" (case-insensitive)
   - files deleted or renamed in the range (`--diff-filter=DR`)
   - files from earlier logged features that were modified again in this range
4. If called from `/verify-commit`, the test results are supplied: use them and do not re-run the tests. Otherwise run the project's test command. Record pass/fail counts and failing test names. If you cannot run it, write `tests: NOT RUN` and why. Never claim they passed without running them.
5. Check the acceptance test of each R-id by running it or reading its test output. Status per R-id: `done-verified` (acceptance evidence seen), `done-unverified` (code exists, no evidence), `partial`, `reverted`, `not started`. Never mark `done-verified` without evidence.
6. Compare with the scope: files touched vs the R-ids and Build order hint in `04-idea-scope.md`; unplanned files touched; elapsed time from first to last commit of this feature.
7. Revert accounting, exact and factual:
   - what was reverted or deleted (commit hash, files, roughly how many lines)
   - why, taken from the commit message. If unknown, write `reason unknown, ask user`.
   - what was rewritten after being logged earlier (a regression signal)
   - churn ratio = lines deleted / lines added for the range

Append this entry to `.hackathon/PROGRESS.md` (max 15 lines):

~~~
### <feature> | R-ids | <date> | commits <first..last hash>
- Built: <what actually works, one line per item>
- Evidence: <tests X/Y pass, acceptance run result>
- Reverted / removed: <items with hash, or "none">
- Rewritten after earlier logging: <files, or "none">
- Unplanned work: <files and why, or "none">
- Time: <elapsed, first to last commit>
- Shortcuts / debt: <anything hardcoded, stubbed or skipped, or "none">
- Open issues: <failing tests, known bugs>
~~~

Then recompute the dashboard at the TOP of `PROGRESS.md` (replace the old one, and update `base:` to the current HEAD hash):

- `base: <HEAD hash>`
- Requirement table: `R-id | priority (MUST/NICE) | status | evidence`.
- **Honest progress:** `MUST done-verified / MUST total` as a fraction and percent. Count only `done-verified`. Also show NICE the same way.
- Time: elapsed since the first commit.
- Health: total churn ratio, number of reverts, open issues, whether `/hardcode-check` has passed for the latest commit (read `STATE.md`).
- **Verdict:** `ahead` / `on track` / `behind`, with one line why.

If `PROGRESS.md` exceeds 200 lines, collapse older entries to one line each.

Finish:
1. Set `build.feature-log: <R-ids> logged @ <hash>` in `.hackathon/STATE.md`.
2. Print the dashboard and the new entry's Built, Reverted and Debt lines.
3. If `/hardcode-check` has not passed for HEAD, say so. End with: `Next: /hardcode-check` (if not run), else `Next: next task, or /drift-check if it has been 60+ min`.