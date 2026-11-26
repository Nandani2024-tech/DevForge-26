---
name: ps-breakdown
description: Turn a hackathon problem statement into a locked, testable spec (requirements with acceptance tests, data contracts, edge cases, targets, traps) plus a short brief for the coding agent. Run first, once.
disable-model-invocation: true
---

Input: `$ARGUMENTS` (the problem statement; may include links or files). If empty, ask the user to paste it in one message, then stop.

Rules:
- Time box: 10 minutes. Create `.hackathon/` if missing.
- Open every link, file or dataset the PS references. Record the real schema, fields, formats and limits. Never guess them. If unreachable, write `UNKNOWN` and add it to section 10.
- Everything must come from the PS or be labelled `(assumed)`. Never present an invented requirement, number or example as given.
- Do NOT interrogate. Record assumptions instead. Ask a question only if every reading of the PS would be invalid without the answer (max 1).
- Every requirement needs an observable acceptance test that a person can run or demo and see pass/fail. "Works well" is not acceptable.
- Terse bullets, no intro prose.

Write TWO files.

## File 1: `.hackathon/01-ps.md` (for Claude, max 90 lines)
First line: `LOCKED CONTRACT: edit only with explicit user approval.`

1. **Problem definition (5 lines):** L1 target user, L2 core pain, L3 required action, L4 demo success metric, L5 differentiator hook.
2. **Requirements:** numbered R1..Rn. Each: `Rn | the system shall <behavior> | input -> output | acceptance test | source: PS or (assumed)`. Cover every explicit ask in the PS, nothing else.
3. **Core user flow:** the happy path, one step per line, from the user's first action to the visible result.
4. **Data and interfaces:** inputs, outputs, formats, schemas, provided datasets, required APIs. Real values only, else `UNKNOWN`.
5. **Hard constraints:** mandated tech, time, data, rules, submission format.
6. **Quality targets:** scale, latency, accuracy, size. Each tagged `(PS)` or `(assumed)`. If the PS gives none, set sensible targets and tag them `(assumed)`.
7. **Edge cases and failure modes:** bad input, empty input, huge input, API down, partial data, concurrent use. One line each, with the expected behavior.
8. **Judging:** rubric weights if given, plus unspoken expectations (live demo over slides, real data over mocks).
9. **Non-goals:** 3-5 things we explicitly will not build.
10. **Assumptions and open questions (max 4):** `Assumed X because PS says/omits Y. Flip if: Z.`
11. **Traps:** 4-6 likely wrong turns for THIS PS (building the wrong thing, mocking the core, overfitting to sample data, ignoring a constraint, over-engineering).
12. **Definition of done:** a demo checklist that, when all ticked, means the PS is satisfied.

## File 2: `.hackathon/01-brief.md` (for Antigravity, max 25 lines, self-contained)
- **Goal:** one sentence.
- **Build:** the R-ids with a one-line behavior each.
- **Do not build:** the non-goals.
- **Data and interfaces:** only what the coder needs.
- **Quality bar:** the targets from section 6.
- **Traps to avoid:** the traps from section 11.
- **Scope:** `TBD (filled by /build-rules after /idea-and-scope)`.
- **Rules:** `Follow .hackathon/00-rules.md. Read .hackathon/MISTAKES.md before each task.`

Finish:
1. Create `.hackathon/STATE.md` if missing. Set `phase0.ps-breakdown: done, <one-line result>`.
2. Print in chat only: the 5-line definition, the requirement list (id + behavior only), and sections 10 and 11.
3. End with: `Next: /domain-primer`