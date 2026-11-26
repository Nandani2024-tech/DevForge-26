---
name: test-from-codebase
description: Write tests for a just-built feature in the repo's own test style, driven by the spec's acceptance tests and the domain's known-answer cases, then run them and report honestly. Never edits source code.
disable-model-invocation: true
---

Input: `$ARGUMENTS` = feature name and R-ids (e.g. `R2 search endpoint`). If empty, use `build.current-task` from `.hackathon/STATE.md`; if that is also empty, ask in one line.

Read ONLY: the acceptance tests and edge cases for those R-ids in `.hackathon/01-ps.md`, `02-domain.md` section 5 (test oracles), the test command and testing rules in `00-rules.md`, the files changed for the feature (`git diff --name-only <range>`, default `HEAD~1..HEAD`; if the input includes the token `WORKTREE`, which `/ship` sets, use the uncommitted change set instead: `git diff HEAD --name-only` plus `git ls-files --others --exclude-standard`, excluding `.hackathon/`), and 1-2 existing test files plus the test config to learn the framework, folder layout, naming and fixtures. If the repo has no tests yet, pick the standard framework for the stack (prefer what the Reuse Stack or stack already implies), install it, and say so.

Rules:
- Do NOT edit source code, only test files and test config. If the code is wrong, report it; the fix goes to Antigravity.
- Match the repo's style exactly: framework, folder, naming, fixtures, assertions.
- Expected values come from the spec, the domain oracles, or hand-derived arithmetic shown in a comment. NEVER copy the implementation's output as the expected value.
- Test behavior through the public interface. Do not mock the thing under test. Mock only true external boundaries (network, clock, third-party APIs) and keep at least one test hitting the real path where it is feasible.
- Coverage per R-id: the acceptance test, each listed edge case, at least one failure case (bad, empty or missing input, dependency down) asserting the specified error behavior, and a scale/regression case if `04-idea-scope.md` has a target for it.
- No skipped tests, no tests without assertions, no tautologies, no `assert True`.
- Each test name states the behavior and the R-id.
- Re-runs: if tests for these R-ids already exist (search test names for the R-id), update or extend them. Never add duplicates.
- Run the full relevant suite with the command from `00-rules.md`. Record the real counts and failing test names. If it cannot run, write `NOT RUN` and why.

If tests fail:
1. Classify each failure: `code bug`, `spec/oracle mismatch`, `test bug`, `environment`.
2. Fix only `test bug` and `environment` failures. For `code bug`, do not weaken or delete the test.
3. Print an Antigravity fix prompt for code bugs: the failing test, expected vs actual, the suspected root cause, "fix the root cause, no special-casing, re-run the tests".
4. For `spec/oracle mismatch`, say which source is wrong and mark it `NEEDS USER APPROVAL`.

Also:
- Log every `code bug` failure in `.hackathon/MISTAKES.md` per the MISTAKES rule in `CLAUDE.md` (source `test-from-codebase`; dedupe by root cause, bump `seen`).

Finish:
1. Set `build.test-from-codebase: <pass>/<total> for <R-ids> @ <short hash>` in `.hackathon/STATE.md`.
2. Print: files written, a table of R-id | tests added | pass/fail, failing tests with classification, and the fix prompt if any.
3. End with: `Next: /hardcode-check` (all pass) or `Next: paste the fix prompt into Antigravity, then re-run /test-from-codebase`