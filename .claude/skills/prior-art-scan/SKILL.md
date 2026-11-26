---
name: prior-art-scan
description: Find and verify existing libraries, APIs, datasets, UI kits and projects for each requirement, produce the Reuse Stack, and record integration gotchas, so nothing is built from scratch needlessly.
disable-model-invocation: true
---

Input: `$ARGUMENTS` (optional: tech constraints, e.g. "Python only, no paid APIs"). Read ONLY `.hackathon/01-ps.md` and `.hackathon/02-domain.md` (sections 4 and 8 especially). If either is missing, say which and stop.

Rules:
- Time box: 20 minutes. Write `.hackathon/03-prior-art.md`, max 80 lines.
- Search per requirement, not generically. For each R-id (and each Hard constraint in `01-ps.md`), look for something that already covers it. Search in 5 buckets: (1) libraries, SDKs, APIs, (2) datasets (real data beats mocks, per the PS), (3) open-source projects solving the same or a similar problem, (4) UI/UX kit: component library, charts, layout or design system, (5) papers or earlier hackathon winners.
- 2-action rule: after every 2 searches or fetches, append findings to `03-prior-art.md` BEFORE searching again.
- Verify before listing: open the official docs, registry page or repo. Record version, last release or commit date, license, install command or endpoint. Never invent a URL, version or API. Unverified items get `(unverified)` and cannot go in the Reuse Stack.
- Smoke test (top 3 critical dependencies only): run a minimal check in a temp directory, never in the project repo, max 2 minutes each. Record `smoke: pass / fail / not run`.
- Reject: stale with no maintenance (about 2 years) unless tiny and stable, unclear license, conflicts with a Hard constraint in `01-ps.md`, setup over 30 minutes, or needs a paid key or quota that could break the live demo (unless the PS provides it).
- Max 10 candidates. Prefer one well-known library over three obscure ones.
- Do NOT edit `01-ps.md`. Propose changes only.

Sections of `03-prior-art.md`:
## Reuse Stack
(exact heading; this is what gets tagged in Antigravity)
`R-id | need | package or API | version | install command or endpoint | license | smoke`
## Coverage gaps
- R-ids with no reuse option, so custom code is required. One line on why nothing fits.
## Candidates
- `name | URL | what it gives us | R-ids | license | last activity | setup minutes | verdict: USE / ADAPT / BUILD | reason`
## Already solved
- What exists, so we do not reinvent it.
## Datasets
- name, URL, size, format, license, whether it satisfies the PS data requirement.
## Integration notes (for the coding agent)
- Per Reuse Stack item: auth, rate limits, version pins, known bugs, gotchas, the right entry-point function or endpoint.
## Differentiation gap
- What existing solutions miss that we can credibly add within the time available.
## Risks and blockers
- API limits, keys, data size, licensing, anything that can block the demo.
## Resolved unknowns
- `UNKNOWN` items from `01-ps.md` section 4 or 10 now answered, with the finding and `NEEDS USER APPROVAL` for any change to the locked file.
## Sources
- URLs.

Also:
- Append to `.hackathon/01-brief.md` (one line, if absent): `Libraries: use the Reuse Stack in .hackathon/03-prior-art.md. Do not add others without asking.`
- Append up to 5 integration gotchas to `.hackathon/MISTAKES.md` per the MISTAKES rule in `CLAUDE.md` (source `prior-art-scan`, symptom `(preventive)`).

Finish:
1. Set `phase0.prior-art-scan: done, <one-line result>` in `.hackathon/STATE.md`.
2. Print in chat only: the Reuse Stack, Coverage gaps, Differentiation gap, and Risks.
3. End with: `Next: /idea-and-scope`