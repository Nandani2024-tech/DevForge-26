---
name: unstick
description: "When a task has failed twice or stalled, stop patching: log it, find the root cause, and propose three alternative routes (existing library, simpler approach, reframe) with a recommendation. Decides nothing and changes no code."
disable-model-invocation: true
---

Input: `$ARGUMENTS` = the blocker in one or two lines (what you are trying to do and what fails). If empty, ask in one line and stop.

Read ONLY: `.hackathon/00-rules.md` (stuck protocol), `MISTAKES.md`, `03-prior-art.md` (Reuse Stack, Candidates), `04-idea-scope.md` (Decision, Plan B, switch trigger, targets), `02-domain.md` sections 4 and 6, and the R-id acceptance test involved. Read only the specific failing files, logs or error output the user provides or points to. Do NOT scan the repo. Do NOT edit code.

Steps:
1. **Restate:** symptom, expected vs actual, and the R-id it blocks, in 3 lines.
2. **What was tried:** list the attempts from this conversation or from what the user pasted. If unknown, ask once: "What have you tried?" and wait. Do not repeat anything already tried.
3. **Check MISTAKES.md:** has this root cause or symptom appeared before? If so, quote the rule that was ignored.
4. **Root-cause hypotheses (max 3, ranked):** each with the evidence for it and the cheapest experiment that would confirm or kill it (a print, a minimal repro, a version check, reading the docs). Run read-only experiments yourself if you can; otherwise give the exact command. Never propose a fix before the cause is known.
5. **Three alternative routes** (all must still satisfy `01-ps.md`; check the Hard constraints):
   - **A. Use something that exists:** search the web and the Reuse Stack for a library, API, or example that does this part. Verify it before listing it (docs, version, license) and mark `(unverified)` if you could not.
   - **B. Simplify:** a lighter version of the same requirement that still meets the acceptance test and the targets, or a smaller slice.
   - **C. Reframe:** solve the underlying need from a different angle, or move the difficulty elsewhere (precompute, change the data shape, split the problem, change the interface).
   For each: what changes, R-ids affected, effort left, risk, how it affects the demo, and what spec edit it needs (if any).
6. **Recommendation:** one route and the main reason. Also state when to abandon the current approach: after the cheapest experiment fails, or if the stuck point is the riskiest assumption from the spike.
7. **Switch trigger:** read the trigger in `04-idea-scope.md`. State whether this blocker fires it, plus the evidence.

Rules:
- Stuck is a signal about the approach, not about effort. Do not recommend "try harder", more retries, or special-casing.
- If a route needs a spec or scope change, say so and send the user to `/pivot-check` rather than making the change.
- Be honest when the hypothesis is weak or unknown.

Also: log the blocker in `.hackathon/MISTAKES.md` per the MISTAKES rule in `CLAUDE.md` (source `unstick`; root cause may be `unknown, hypothesis: X`).

Finish:
1. Set `build.unstick: <R-id> | blocker: <short> | recommended: <A/B/C>` in `.hackathon/STATE.md`.
2. Print the hypotheses, the three routes in a table, the recommendation, and the switch-trigger status.
3. On the user's pick: if the route replaces code or a library that is already built (A, C, or a B that drops built code), append an entry to `.hackathon/DECISIONS.md` per the DECISIONS rule in `CLAUDE.md` (Trigger: unstick). Then print a paste-ready Antigravity prompt for it (start with the read-first line from `00-rules.md`, state the root cause, the chosen route, constraints, and the acceptance test).
4. End with: `Next: tell me which route (A/B/C), or /pivot-check`