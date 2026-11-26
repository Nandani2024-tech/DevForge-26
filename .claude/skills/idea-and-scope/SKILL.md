---
name: idea-and-scope
description: Generate 4 deliberately different approaches, score them, pick one with a fallback and a switch trigger, set the MVP cut line by requirement id with complexity targets, and name the riskiest assumption to test first. Run after prior-art-scan.
disable-model-invocation: true
---

Input: `$ARGUMENTS` (optional: team size, hours available, skills). Read ONLY `.hackathon/01-ps.md`, `.hackathon/02-domain.md` (sections 3-4), `.hackathon/03-prior-art.md` (Reuse Stack, Coverage gaps, Risks). If any is missing, say which and stop. If team size or hours are unknown, ask in ONE line and wait.

Rules:
- Time box: 15 minutes. Write `.hackathon/04-idea-scope.md`, max 80 lines. First line: `STATUS: PROPOSED`.
- Constraint gate: any approach that violates a Hard constraint in `01-ps.md` is discarded before scoring.
- Diversify on purpose. Generate exactly 4 approaches:
  - A: Off-the-shelf composition (mostly the Reuse Stack).
  - B: Simple custom core on top of existing tools.
  - C: Ambitious or novel (higher risk, higher upside).
  - D: Reframe (same pain, different angle than the PS suggests, still meeting every Hard constraint).
- Each approach: 2-line description, the R-ids it fully covers, libraries used, estimated custom-code hours, core algorithm and its complexity, and its riskiest assumption.
- Score 1-5 on each criterion, then compute the weighted total (max 55): Feasibility x3, Judging fit x3, Demo impact x2, Differentiation x2, Reuse leverage x1. Show the table. Justify every 1 and every 5 in a few words.
- Never pick an approach with Feasibility of 1 or 2. If the top two totals are within 3 points, pick the more feasible one.
- Do not choose a hardcore solution when a simpler one satisfies the PS and the targets.
- Every R-id from `01-ps.md` must appear in exactly one of MUST / NICE / DROP. The MUST set must make the Core user flow work end to end. Any R-id whose source is "PS" placed in NICE or DROP is marked `NEEDS USER APPROVAL`.
- Do NOT edit `01-ps.md` or `01-brief.md`. Propose spec changes only (`/build-rules` fills the brief's Scope line).

Sections of `04-idea-scope.md`:
## Approaches and scores
## Decision
- Chosen approach and why (3 lines max), Plan B (the runner-up), and a switch trigger that is specific and measurable: "If <X> is not working by <milestone or time>, switch to Plan B."
## Riskiest assumption and spike
- The single assumption that sinks the chosen approach if false, a 15-minute test for it, and the pass condition. This becomes the first task in the plan.
## MVP cut line (by R-id)
- MUST / NICE / DROP, with one line on why for each DROP.
## Complexity and performance targets
- Per MUST R-id: expected input size (from the PS or `(assumed)`), target Big-O or latency, the data structure or library that achieves it, and how it will be measured. Targets from `01-ps.md` may be tightened, never loosened.
## Screens and UX
- Names of the 2-5 screens or views, the single primary action on each, and the UI kit from the Reuse Stack.
## Build order hint
- 3 lines: the thin end-to-end slice first, then the next MUST items. `/handoff-prompt` turns each item into a task.
## Kill list
- The non-goals from `01-ps.md` plus tempting additions that would cause drift.
## Proposed spec changes
- Anything in `01-ps.md` the chosen approach contradicts, marked `NEEDS USER APPROVAL`, or "none".

Finish:
1. Print in chat: the score table, the Decision, the spike, MUST / NICE / DROP, and any `NEEDS USER APPROVAL` items. Ask: "Go with <approach>? (yes / pick another / tweak)".
2. Set `phase0.idea-and-scope: PROPOSED, <chosen approach>` in `.hackathon/STATE.md`.
3. On "yes": change line 1 of the file to `STATUS: LOCKED (changes only via /pivot-check)`, and set `phase0.idea-and-scope: LOCKED, <approach>`. On "pick another" or "tweak": rewrite the affected sections, keep it PROPOSED, and ask again.
4. When LOCKED, end with: `Next: /build-rules`