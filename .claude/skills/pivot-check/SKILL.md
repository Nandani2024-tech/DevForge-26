---
name: pivot-check
description: Decide continue, cut scope, switch to Plan B, or pivot, based on evidence from drift, progress, mistakes and reviews. The only skill that may change the locked spec or scope, and only after the user approves exact edits.
disable-model-invocation: true
---

Input: `$ARGUMENTS` (optional: the reason you are calling this, e.g. "spike failed" or "stuck on R3"). Read ONLY: `.hackathon/STATE.md`, `DRIFT.md`, the dashboard and last 3 entries of `PROGRESS.md`, the last 15 lines of `MISTAKES.md`, `REVIEW.md`, `COMPLEXITY.md` and `DECISIONS.md` (if present; never propose going back to a superseded approach without new evidence), `01-ps.md`, and `04-idea-scope.md`. If there is no evidence yet (no `DRIFT.md`, no `PROGRESS.md`), say so and recommend `/drift-check` first. Stop.

Rules:
- You decide nothing alone. You gather evidence, propose, and wait for the user's explicit approval before editing any file.
- Prefer the smallest change that fixes the problem. The order of preference: **continue** (fix the cause) > **cut scope** (move NICE/MUST to lower priority) > **simplify the approach** (same Decision, lighter method or library) > **switch to Plan B** > **pivot** (new approach or reframing).
- Judge from evidence and from what remains to be done, never from effort already spent (sunk cost). Ask: "if I started now with what I know, would I choose this?"
- Never propose a change that violates a Hard constraint in `01-ps.md`. Changing the PS itself (requirements, constraints) risks disqualification or a lower score: flag it clearly, treat it as a last resort, and require the user to confirm they understand.
- Never cut the Core user flow. A MUST that cannot be met may be re-scoped (thinner version), never silently dropped.
- Evidence must be cited: drift verdict, R-id status, repeated mistake lines, failed gates, spike result.

Steps:
1. **Evidence summary (max 8 lines):** verdict, honest progress (MUST done-verified/total), spike result, switch-trigger status, repeated root causes, quality-gate status, what remains.
2. **Diagnose the cause class:** spec misunderstanding / wrong approach / too much scope / environment or library problem / process (no tests, patches, drift) / external blocker. Name the one most supported by the evidence.
3. **Options (2-4, always include "continue" with a concrete fix):** for each: what changes, which R-ids are affected, effort left (rough), risk, what the demo looks like afterward, and the exact edits it needs.
4. **Recommendation:** one option, with the main reason and what would make you wrong.
5. **Proposed edits:** show the exact before/after text for each file (`04-idea-scope.md`: Decision, MUST/NICE/DROP, targets, Screens; `01-ps.md` only if unavoidable). Mark `01-ps.md` edits `HIGH RISK`.
6. Print the evidence, the options and the proposed edits, and ask: "Apply option <X>? (yes / other option / no)". STOP and wait.

On approval:
- Edit `04-idea-scope.md` and, if approved, `01-ps.md`. Keep `STATUS: LOCKED`. Append a `## Change log` entry at the bottom of each edited file: `<date> | <what changed> | <why> | <evidence>`.
- If MUST/NICE/DROP or the targets changed, update the Scope line and targets in `01-brief.md` and the complexity targets in `00-rules.md` to match, and tell the user.
- If the approach changed, note which existing code is now obsolete and list the files to remove. Do not delete anything yourself.
- If a library changed, tell the user to run `/reuse-check <component>` for the new one.
- Log the lesson in `MISTAKES.md` per the MISTAKES rule in `CLAUDE.md` (source `pivot-check`).
- Append an entry to `.hackathon/DECISIONS.md` per the DECISIONS rule in `CLAUDE.md` (Trigger: pivot-check), for every option except "continue". Was = the old Decision/approach with the last commit that used it; Now = the approved option; Why = the cited evidence; Obsolete = the files listed above.

Finish:
1. Append to the decision log in `.hackathon/STATE.md`: `decision: <date> | <option> | <reason> | <files changed>`. Set `build.pivot-check: <decision>`.
2. Print the decision and the next action.
3. End with: `Next: /handoff-prompt` (after approval), or `Next: continue the fix` (if the decision was continue).