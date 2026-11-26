---
name: reuse-check
description: Before building a generic component that is not in the Reuse Stack, search for and verify an existing library or API, then give a USE/ADAPT/BUILD verdict. Adds to the Reuse Stack only with approval.
disable-model-invocation: true
---

Input: `$ARGUMENTS` = the component or need (e.g. "rate limiting", "CSV parsing", "chart for time series"), optionally with the R-id. If empty, ask in one line and stop.

Read ONLY: the Reuse Stack, Candidates and Risks sections of `.hackathon/03-prior-art.md`, the Hard constraints in `01-ps.md` (section 5), and the stack and dependency files in the repo root (e.g. `package.json`, `requirements.txt`, `pom.xml`) to know what is already installed.

Steps:
1. **Already covered?** Check whether the Reuse Stack or an installed dependency already provides this. If yes, report the exact function or entry point and stop with `USE (already in stack)`.
2. **Search** (max 6 searches): official docs and registries first, then well-maintained repos. Try framework-native features before adding a new package. Include a lightweight option and a full-featured one.
3. **Verify each candidate (max 3)** by opening the docs or registry page: version, last release or commit date, license, weekly downloads or stars as a rough health signal, install command, and the entry-point function for our use. Never invent an API or version; mark `(unverified)` if not opened.
4. **Smoke test the top pick** in a scratch directory (never in the project), max 2 minutes: install and run a minimal call. Record `pass / fail / not run`.
5. **Judge fit:** compatibility with the existing stack and versions, license, size and setup time, a paid key or quota that could break the live demo, and conflicts with Hard constraints. Reject stale (about 2 years without maintenance, unless tiny and stable) and unclear licenses.
6. **Verdict:**
   - `USE`: install and use as is.
   - `ADAPT`: use it with a thin wrapper, or take the pattern.
   - `BUILD`: nothing fits, or it is under ~30 lines of code and a dependency is not worth it. Say why.
7. Print: verdict, the chosen package with the install command, a 3-line usage sketch from the official docs (not invented), gotchas, and the runner-up.

Then ask: "Add <package> to the Reuse Stack? (yes / no)". On yes, if the package replaces one already in the Reuse Stack or the code, append an entry to `.hackathon/DECISIONS.md` per the DECISIONS rule in `CLAUDE.md` (Trigger: reuse-check) and mark the old row `SUPERSEDED by <package>`. Then add a row to the `## Reuse Stack` table in `03-prior-art.md` in the same column format, and append the gotchas to `## Integration notes`. On no, write the rejection reason under `## Candidates`. Always record the candidates considered under `## Candidates` with their verdicts.

Also: if the package conflicts with an earlier `MISTAKES.md` rule, say so.

Finish:
1. Set `build.reuse-check: <component> -> <verdict>` in `.hackathon/STATE.md`.
2. End with: `Next: /handoff-prompt` (it will now include the new library)