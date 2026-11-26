---
name: decision
description: Record an approach change (old approach replaced by a better one) in .hackathon/DECISIONS.md, or fill in the reason for one /ship logged as unknown. Use when you change direction outside /pivot-check or /unstick.
disable-model-invocation: true
argument-hint: what changed and why, e.g. "R3 swapped regex parser for lark: regex broke on nested input"
---

Input: `$ARGUMENTS` = what changed and why. If empty, show the entries in `.hackathon/DECISIONS.md` whose `Why` is `unknown` and ask for the reasons in one line, then stop.

Read ONLY: `.hackathon/DECISIONS.md`, the Decision and MUST list in `04-idea-scope.md`, the Reuse Stack in `03-prior-art.md`, and `git log --oneline -15`.

Steps:
1. If the input fills in an `unknown` reason for an existing entry, update only that entry's `Why` and `Lesson` lines and stop.
2. Otherwise append a new entry per the DECISIONS rule in `CLAUDE.md` (Trigger: user). Find `Was` and its commit hash in git log. Never invent a hash or evidence; write `unverified` if you cannot find it.
3. If the change contradicts the LOCKED Decision or MUST/NICE/DROP in `04-idea-scope.md`, do not edit that file: say so and recommend `/pivot-check`.
4. If a library was replaced, mark its Reuse Stack row `SUPERSEDED by <new>` in `03-prior-art.md`, and recommend `/reuse-check <new>` if the new one is not in the stack.
5. Log the lesson in `MISTAKES.md` per the MISTAKES rule in `CLAUDE.md` (source `decision`), unless it is only an improvement, not a mistake.

Finish: set `build.decision: D<n> <title>` in `.hackathon/STATE.md`, print the entry, and end with `Next: /handoff-prompt` (or `/pivot-check` if step 3 applied).
