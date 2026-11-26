---
name: score-check
description: Re-measure the estimated official score on the practice data and the mutated (unseen-style) data, append the result to .hackathon/SCOREBOARD.md, update the open-fix statuses and flag regressions. Measurement only. Run after every commit.
disable-model-invocation: true
argument-hint: optional label for this run, e.g. "after N4 base64"
---

Input: `$ARGUMENTS` = a short label for this run (optional). If empty, use the subject of the latest commit.

Read ONLY: `.hackathon/SCOREBOARD.md` (the last Progress-log row, Open fixes, Open doubts), `tools/VERIFY.md` (the exact commands), `.hackathon/STATE.md`. Do NOT read or scan the rest of the repo.

## Rules
- Measurement only. Never edit `wards/`, `main.py`, `config/`, `tests/`, `raksha.toml` or anything under `tools/`. If a tool is broken, report it and stop; do not fix it here.
- Use the exact commands from `tools/VERIFY.md` (kit at `../Secret-Wards-ToolKit`, `RAKSHA_SECRET=practice`). Write all outputs under `out_score/` (gitignored by `out*/`). Delete `out_score/` before you start.
- Every number you write comes from a command you ran in this session. Label scores "estimate". Never copy a number from an older entry as if it were new.
- Never write patient values, dev names or IDs into SCOREBOARD.md. Counts, percentages, file paths of our own tools and commit hashes only.
- Never edit or delete earlier SCOREBOARD entries or rows. Only append, and only change the `status` cells of Open fixes / Open doubts.

## Preflight (stop with a one-line reason if any fails)
1. `../Secret-Wards-ToolKit/dev/input` exists with 200 files, and `dev/truth/truth.json` and `dev/attacker/` exist.
2. `tools/estimate_score.py`, `tools/mutate_dev.py`, `tools/rehearse_eval.py`, `tools/sw_common.py` and `tools/VERIFY.md` exist.
3. `RAKSHA_SECRET` is set or can be set for the run; record `git rev-parse --short HEAD` and whether the working tree is clean (`git status --short`, ignoring `.hackathon/` and `out*/`). A dirty tree is allowed, but the row must say `dirty`.

## Measure
1. Dev: run the pipeline on `dev/input`, then `validate_output.py`, `check_dev.py`, `estimate_score.py`. Record: CONTRACT OK, leak overall / latin / Hindi / Hinglish, leaks per hiding place, canaries, medical kept, precision / recall / F0.5 / wrong merges, raw copies, the per-category estimate and the total, and run time and peak memory from report.json.
2. Mutated: build the mutated set with `mutate_dev.py`, run the pipeline, `check_dev.py` and `estimate_score.py` on it. Record the leak overall, the five worst types and the estimated total.
3. Secret change: run once more with a different secret; record identical-date-token counts A vs B on dev and mutated (doubts D-b / D-c).

## Compare with the previous Progress-log row
Mark the verdict:
- `REGRESSION` if any of: estimated total (dev or mutated) down by more than 0.5; canaries up; wrong merges above 0; medical kept down by more than 0.1 point; CONTRACT not OK; any leak type up by more than 1 point; run time above 60 s or memory above 512 MB.
- `IMPROVED` if the dev or mutated total is up by more than 0.5 and there is no regression.
- `SAME` otherwise.
For every regression, log it in `.hackathon/MISTAKES.md` per the MISTAKES rule in `CLAUDE.md` (source `score-check`).

## Write to .hackathon/SCOREBOARD.md
1. Append one row to the Progress log table: date, short hash (add `dirty` if needed), label, est. dev, est. mutated, leak dev, leak mutated, canaries, F0.5 / wrong merges, medical kept, penalties, verdict.
2. Update the `status` of each Open fix: `DONE (<date>, <hash>)` when its metric now shows the fix (for example the base64 channel at 0% for #1), `PARTIAL` when it moved but is not done, otherwise leave it.
3. Find new issues. Sources, in this order:
   - the "top fixes" / weak-spot output of `estimate_score.py` (dev and mutated);
   - every leak type, hiding place or script that is above 0% in `check_dev.py` and not already covered by an Open fix;
   - `check_dev.py --show 10` examples: group them by cause (for example "names after a ward label"), never by value;
   - anything that got worse vs the previous row (also a REGRESSION);
   - the latest `.hackathon/REVIEW.md`, `COMPLEXITY.md` and `DRIFT.md` items that affect the score and are not yet listed;
   - anything surprising you noticed while measuring.
4. Before adding, check for duplicates: if an Open fix or doubt already covers the same cause, update that row (status, numbers) instead of adding a new one.
5. Append each new issue as the next numbered row:
   - Open fixes: `fix (cause, never values) | category | est. gain | effort | V1 item or "new" | OPEN`. Add issues of any size; mark gains under 1 point as `small`. Then re-rank only the OPEN rows by estimated points per hour (keep the numbers, change the order).
   - Open doubts: something unexplained or unverified that could change the score (for example "dates in format X not shifted?"), with `OPEN` and what would confirm it.
6. Update the status of each Open doubt you could answer, with the evidence in a few words. A doubt that turns out to be a real problem becomes an Open fix, and the doubt is marked `RESOLVED -> fix #<n>`.
7. Append a dated section `## <date> · <hash> · <label>` with: the score-estimate table (category | max | estimate | change vs previous), the dev and mutated leak summaries, the regressions (if any), `New issues added: fixes #.., doubts D-..` (or "none"), and what was not measured.

Also set `build.score-check: <total dev> / <total mutated> <verdict> @ <hash>` in `.hackathon/STATE.md`.

## Finish
Print, max 20 lines: the new Progress-log row, the per-category changes vs the previous row, any REGRESSION with its cause, the new fixes and doubts added this run, and the top 3 OPEN fixes. Do not commit.
End with one line:
- `REGRESSION`: `Next: fix the regression before anything else (paste the cause into /handoff-prompt)`
- otherwise: `Next: /clear, then /handoff-prompt <top OPEN fix>`
