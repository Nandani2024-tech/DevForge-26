---
name: domain-primer
description: Build a bottom-up, first-principles domain primer mapped to the requirement R-ids, with implementation notes, known-answer test cases and pitfalls for the coding agent, plus a viva cheat-sheet. Run after ps-breakdown.
disable-model-invocation: true
---

Input: `$ARGUMENTS` (optional: what the user already knows, e.g. "know linear algebra, new to RL"). Read ONLY `.hackathon/01-ps.md`. If missing, tell the user to run /ps-breakdown and stop.

Rules:
- Time box: 25 minutes. Write `.hackathon/02-domain.md`, max 100 lines.
- Scope by need: cover only concepts required by the R-ids, the hard constraints, and the traps in `01-ps.md`. Skip what the user said they know and spend the space on sections 3 to 5.
- Bottom-up: each level uses only terms already explained. No unexplained jargon. The user must be able to re-derive the idea, not just repeat it.
- Sources: official docs, the original paper, a solid survey or tutorial. Record every URL. Open a page before citing it.
- 2-action rule: after every 2 searches or fetches, append notes to `02-domain.md` BEFORE searching again.
- Never state a number, formula, default or benchmark you did not verify. Mark it `(unverified)`.
- The known-answer cases in section 5 must be small, hand-checkable, and either verified from a source or derived step by step in the file. Never invent expected outputs.
- Do NOT edit `01-ps.md` (locked). Put proposed spec changes in section 8.

Sections of `02-domain.md`:
1. **Concept map:** `R-id -> concepts needed -> where explained below`.
2. **Foundations (bottom-up):**
   - L0 prerequisites: 3-6 items, one line each.
   - L1 core concepts: term -> plain definition -> why it matters here.
   - L2 mechanism: how it works step by step, plus one tiny worked example with real numbers.
3. **Our sub-problem:** where the PS sits in the field, the standard approaches (named), the metrics used to judge them, and the known failure modes.
4. **Implementation notes (for the coding agent):** per R-id: the correct algorithm or method, its time/space complexity, sane defaults or hyperparameters, and numerically or semantically tricky parts (off-by-one, precision, ordering, leakage, encoding, concurrency).
5. **Test oracles:** 3-6 known-answer cases: `input -> expected output -> how it was verified or derived`. Include at least one edge case from section 7 of `01-ps.md`. These feed the tests, so they must be real.
6. **Pitfalls:** the common ways people get this domain wrong, one line each, phrased as "Wrong: X. Right: Y."
7. **Explain it:** a 30-second and a 2-minute explanation, for pitch and viva.
8. **Gaps and spec flags:** `UNKNOWN` items from `01-ps.md` that the domain resolves (with the finding), assumptions that look wrong (with evidence), and any proposed requirement change marked `NEEDS USER APPROVAL`. Up to 3 things still unclear for /prior-art-scan to chase.
9. **Self-test:** 8 questions from basics to our exact problem, each with a one-line answer.
10. **Sources:** URLs.

Also:
- Append up to 5 preventive entries from section 6 to `.hackathon/MISTAKES.md` per the MISTAKES rule in `CLAUDE.md` (source `domain-primer`, symptom `(preventive)`). Do not overwrite an existing file.
- Append to `.hackathon/01-brief.md` (one line, if absent): `Domain: read .hackathon/02-domain.md sections 4-6 before coding.`

Finish:
1. Create `.hackathon/STATE.md` if missing. Set `phase0.domain-primer: done, <one-line result>`.
2. Print in chat only: section 8, and the 30-second explanation.
3. End with: `Next: /prior-art-scan`