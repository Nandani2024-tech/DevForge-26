checked: d15a3c6 | 2026-11-27 05:50 | verdict: ON TRACK

Range 74d4590..d15a3c6 (2 commits).
R-id | priority | status | evidence
R5 | MUST | done-verified | d15a3c6: dev unchanged; renamed-header set all 7 R5 types <= 2% (MRN 6.4% -> 0.0%)
R8 | MUST | done-verified | medical kept 4854/4855 on dev and renamed set; over-redaction tests (notes, timestamps, doses) pass
R16, R17, R20 | MUST | done-unverified | kill-test, TMP/HOME grep, network-off/Linux run still not done
R23 | MUST | partial | README model section missing (check_submission: README 62 words)

Unplanned work:
fff7ed4 .claude/skills/score-check/SKILL.md | 12 | workflow tooling, no R-id | trivial, own commit (keep)

Effort: 1155/1167 changed lines (99%) on MUST R5/R8; 0 on NICE or DROP.
Contradictions: none. No Kill-list item, no new dependency, no dev word lists (vocab lock and allowlist unchanged).
Core flow: steps 1-4 work on dev and the renamed set (exit 0, CONTRACT OK, READY TO SUBMIT, keyed outputs).
Spike: done (scaffold, PROGRESS). Approach: still B (custom two-pass rules); changes recorded as D12-D14. Switch trigger (> 25% leak or 4/4 canaries): not fired (0.4%, 0/4).
Stuck signals: R5 took 3 verify rounds (2 blocked). Repeating root causes in MISTAKES: dev strings copied into tests (seen 7), constants at the call site (seen 8), handover without a full test run (seen 3), timing-test flake (seen 2). Range churn 0.09 (was 0.03): rising, from the rewrites inside the R5 rounds, 0 reverts.
Gates @ d15a3c6: test-from-codebase 127/127, hardcode-check WARN (1 duplication), complexity-audit PASS, feature-log logged.
Honest progress: MUST 15/19 done-verified (79%); NICE 0/6.

Corrective actions:
1. Finish the unverified MUSTs next: R16 kill-test, R17 TMP/HOME grep, R20 network-off run, R23 README model section (one handoff).
2. Put the repeating rules into the next handoff: invented test names checked against dev, constants only in wards/config.py, full pytest + kit output before handover.
3. Stabilise test_r9_channel_cleaner_scales_linearly (flaked twice) with the call-count style used in the R5 scale test.
Not verified: Linux / Python 3.10 and 3.12 runs; peak RSS at 50k rows.
