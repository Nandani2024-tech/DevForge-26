---
name: build-rules
description: Write the standing rules file the coding agent must follow (no hardcoding, no patches, reuse libraries, complexity targets, tests, stuck protocol) and set up the mistakes log. Run once after idea-and-scope; rerun after any pivot.
disable-model-invocation: true
---

Input: `$ARGUMENTS` (optional: extra rules from the user). Read ONLY `.hackathon/01-ps.md`, the Reuse Stack in `.hackathon/03-prior-art.md`, and the decision, MUST list and targets in `.hackathon/04-idea-scope.md`. If any is missing, say which and stop.

Tailor, don't paste blindly. From the repo and the Reuse Stack, fill in the real commands (run, test, lint) and the languages and libraries in use. If the repo is empty, write `TBD after scaffold` for the commands.

Write `.hackathon/00-rules.md` (max 60 lines, imperative, one rule per line) with these sections:

1. **Before every task:** read `01-brief.md`, `00-rules.md`, `MISTAKES.md`, `DECISIONS.md` (if present) and the task's handoff prompt. State in 3 lines what you will do and which R-id it serves.
2. **Scope:** build only what serves a MUST R-id. Anything else: stop and ask. No new features or dependencies unprompted.
3. **Reuse:** use the Reuse Stack. Before writing more than 30 lines of generic code (parsing, auth, validation, queues, charts, caching), check whether a library exists. When adding a dependency, say why.
4. **Real implementation:** no hardcoded outputs. No sample data standing in for real inputs. No special-casing test or demo inputs. No stubs that return fake success. Every function must use its inputs. Data flows from the real source. Config and secrets come from env or config files. Constants are named and live in one place.
5. **No patches:** state the root cause in one line before changing code. Forbidden: empty or swallowed exceptions, sleep to fix timing, commented-out failing code, disabled or weakened tests, duplicated code to dodge a refactor, workaround flags.
6. **Failure handling:** errors are logged and shown to the user. Never silently fall back to fake or demo data.
7. **Complexity:** state the Big-O of any function touching collections, DB or IO. Meet the targets from `04-idea-scope.md` (list the actual ones here). No nested loops over large inputs. No queries inside loops. Paginate or stream big data.
8. **Testing:** every feature ships with tests in the existing framework covering happy path, edge cases and failure cases. Run them and show the output before declaring done. Never claim "tests pass" without running them.
9. **UI:** loading, empty and error states on every screen. No lorem or placeholder text. All displayed values come from real data.
10. **Stuck protocol:** after 2 failed attempts at the same problem, stop. Do not edit `.hackathon/`; instead put a `STUCK:` section in your final report (symptom, what was tried, hypothesis), which Claude logs in `MISTAKES.md`. Propose 2 alternatives, including an existing library and a simpler approach. Do not keep patching.
11. **Deviation protocol:** if the spec or plan looks wrong or impossible, stop and name the R-id and the reason. Wait for a decision.
12. **After each feature:** do NOT commit or push. Leave all changes in the working tree; Claude verifies and commits. List files changed. List any shortcut taken (the answer should be none). If you replaced an approach, algorithm or library that was already in place, say so in an `APPROACH CHANGED:` line (was / now / why). Never reintroduce anything listed as superseded in `DECISIONS.md`.
13. **Allowed exceptions:** `(none)`. Only the user adds entries. Each needs: what, why, where, removal plan.

Also:
- Create `.hackathon/MISTAKES.md` if missing, using the header from the MISTAKES rule in `CLAUDE.md`.
- Replace the `Scope` line in `.hackathon/01-brief.md` with the MUST / NICE / DROP lists (R-ids only) and the complexity targets.

Finish:
1. Set `phase0.build-rules: done` in `.hackathon/STATE.md`.
2. Print only the section headings of `00-rules.md` and any rule you tailored beyond the defaults.
3. End with: `Next: /handoff-prompt`