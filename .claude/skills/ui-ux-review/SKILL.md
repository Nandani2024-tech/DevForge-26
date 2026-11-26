---
name: ui-ux-review
description: Review a running screen against a demo-focused UX checklist (primary action, states, consistency, real data, readability, click count) and produce an Antigravity fix prompt. Marks anything it could not see as unverified.
disable-model-invocation: true
---

Input: `$ARGUMENTS` = the screen or flow name (e.g. `search results`, `demo flow`). If empty, review the whole Core user flow.

Read ONLY: the Core user flow and judging section in `.hackathon/01-ps.md`, the `## Screens and UX` section of `04-idea-scope.md` (primary action per screen, UI kit), the UI/UX rules in `00-rules.md`, and the run command. Do NOT scan the repo, except the files of the screen under review.

Getting the real UI: try in this order, and record which one you used.
1. Use screenshots the user pastes or points to (ask for them if none are provided and nothing else works; when run from `/ship`, never ask: go straight to step 3).
2. If Playwright or a browser tool is available, start the app with the run command and capture screenshots of the flow at desktop and a projector-like size (1280x720), plus a narrow mobile width if the PS needs mobile.
3. If neither is possible, review the code of the screen only, and label EVERY visual finding `unverified (code only)`. State that a visual review is still needed.

Checklist (check each one against what you saw):
- **Flow:** the demo flow completes in the fewest clicks; each screen has ONE obvious primary action matching `04-idea-scope.md`; no dead ends; the user can see progress.
- **States:** loading, empty, error and success exist and look intentional; errors say what happened and what to do; no raw stack traces or `undefined`/`null`/`NaN` shown.
- **Real data:** no lorem ipsum, placeholder text, or fake static numbers; every displayed value comes from real data. Findings here also go to `/hardcode-check`.
- **Clarity:** the visible result explains itself in under 5 seconds, using plain labels; the key result is the largest or most prominent element.
- **Consistency:** one type scale, one spacing scale, one color system from the chosen UI kit; consistent buttons, inputs and icons; no mixed styles.
- **Legibility for a live demo:** readable on a projector: body text of 16px or more, strong contrast, key numbers large; no important info in tiny or light-gray text.
- **Feedback:** actions respond immediately; long operations show progress; disabled states are clear.
- **Responsiveness:** nothing overflows or breaks at the tested sizes.
- **Accessibility basics:** labels on inputs, focus visible, alt text, contrast; keyboard use works for the main flow.
- **Demo risk:** anything that can break live (slow first load, empty first state, a dependency on network/API keys); suggest a seeded real-data state for the demo.

Rules:
- Rank findings: `BLOCKER` (breaks the demo flow or shows fake or broken data), `FIX` (clearly hurts judging), `POLISH` (nice to have). Do not pad the list; if the screen is good, say so.
- Fixes use the existing UI kit and tokens. Do not propose a redesign or a new library.
- Do not edit code.

Write `.hackathon/UI-REVIEW.md` (overwrite, max 40 lines):
- Header: screen, date, method used (screenshots / browser / code only), verdict `PASS` / `WARN` / `FAIL` (FAIL if any BLOCKER).
- Table: `id | screen | checklist item | what is wrong | fix | severity | verified?`
- A paste-ready **Antigravity fix prompt** covering BLOCKER and FIX items (read-first line, the screen, exact changes, use the UI kit, no new dependencies, keep logic unchanged, show a screenshot or describe the result).
- Last line: what you could not verify.

Also: log every BLOCKER and FIX finding in `.hackathon/MISTAKES.md` per the MISTAKES rule in `CLAUDE.md` (source `ui-ux-review`). Findings marked `unverified` are not logged.

Finish:
1. Set `build.ui-ux-review: <screen> <verdict>` in `.hackathon/STATE.md`.
2. Print the verdict, the table and the fix prompt.
3. End with: `Next: paste the fix prompt into Antigravity, then re-run /ui-ux-review <screen>` (WARN/FAIL), else `Next: /feature-log`