---
name: handoff-prompt
description: Print a paste-ready, self-contained prompt for Antigravity for the next build task (an R-id or free text), built from the spec, domain notes, Reuse Stack and past mistakes. Prints only; changes no code.
disable-model-invocation: true
---

Input: `$ARGUMENTS` = an R-id (e.g. `R2`), R-ids plus a label (e.g. `R2 search endpoint`), or free text for a small task. If empty, pick the next task (see below).

Read ONLY: `.hackathon/01-ps.md`, `01-brief.md`, `02-domain.md` (sections 4-6), `03-prior-art.md` (Reuse Stack, Integration notes), `04-idea-scope.md`, `00-rules.md`, `MISTAKES.md`, `DECISIONS.md` (if present), and the dashboard at the top of `PROGRESS.md` if it exists. If `01-ps.md`, `00-rules.md` or `04-idea-scope.md` is missing, say which and stop. Do NOT scan the repo, except `git ls-files` (names only) to name real files.

Picking the next task when no argument is given:
1. If the riskiest-assumption spike in `04-idea-scope.md` is not logged as done in `PROGRESS.md`, the task is the spike.
2. Otherwise follow the Build order hint, taking the first MUST R-id that is not `done-verified` in `PROGRESS.md`.
3. If everything MUST is done-verified, say so and recommend `/drift-check`, then NICE items. Stop.
State your pick and why in one line, and let the user override.

Task size: one prompt = one R-id or one thin slice of it. If the R-id is too big to finish and verify in one sitting, split it into 2-3 slices, hand off only the first, and list the rest.

Output: print ONE fenced block for the user to paste into Antigravity (max 60 lines, self-contained, no references to this chat). Contents, in order:
1. `Read first: @.hackathon/00-rules.md @.hackathon/01-brief.md @.hackathon/MISTAKES.md @.hackathon/DECISIONS.md` (drop the last one if the file does not exist)
2. **Task:** the R-id, the behavior from `01-ps.md` (`input -> output`), and why it matters in the Core user flow.
3. **Acceptance test:** copied from `01-ps.md`, plus the edge cases for this R-id from section 7.
4. **Data and interfaces:** only the schemas and formats this task touches.
5. **Use these libraries:** the Reuse Stack rows for this R-id (name, version, install command), plus the relevant Integration notes. "Do not add other dependencies without asking."
6. **Domain notes:** the matching items from `02-domain.md` section 4 (method, complexity, tricky parts) and section 6 (pitfalls), plus the known-answer cases from section 5 to test against.
7. **Complexity target:** from `04-idea-scope.md`, with the input size to design for.
8. **Files:** likely files to create or edit (from `git ls-files` or `04-idea-scope.md`, otherwise "choose minimal structure and name it first"). Do not touch: `.hackathon/`, unrelated modules, and existing tests unrelated to this task.
9. **UI** (only if the task has a UI): the screen name, its single primary action, and loading/empty/error states required.
10. **Past mistakes to avoid:** the 5-8 most relevant lines from `MISTAKES.md` (highest `seen` first), plus every `Was:` approach from `DECISIONS.md` for these R-ids under the heading "Superseded, do not use".
11. **Definition of done:** run the code on real input, write and run tests with output shown, no hardcoding, stubs or fake data, do NOT commit or push (leave all changes in the working tree; Claude verifies and commits through `/ship`), then report files changed, test output, any shortcut taken (expected: none), an `APPROACH CHANGED:` line if you replaced an existing approach or library, and a `STUCK:` section if you hit the stuck protocol.
12. **Stop and ask if:** the spec looks wrong, a needed library is missing, the same problem fails twice, or the task needs a new dependency or scope.

After the block, print one line: what to run next. Normal sequence: when Antigravity finishes, run `/ship <R-ids>` and paste Antigravity's final report after the R-ids if it has `APPROACH CHANGED:` or `STUCK:` lines. It runs the gates, commits, and logs progress.

Finish: set `build.current-task: <R-id + label>` in `.hackathon/STATE.md`. End with: `Next: paste into Antigravity, then /ship <R-ids>`