checked: dc168be | 2026-11-26 22:01 | verdict: ON TRACK
Range: 298367b..dc168be (3 commits: 39ca495 tooling, 1f885cf R10-R13, dc168be R12 R13)

R-id | priority | status | evidence
R1 R2 R3 R8 R9 R15 R19 R21 | MUST | done-verified | see PROGRESS dashboard
R10 R11 R12 R13 | MUST | done-verified | F0.5 0.96, 0 wrong merges; tests/test_acceptance_r11_r13.py (681/681, 339/339, 0/447)
R5 R6 R7 R23 | MUST | partial | PATIENT_NAME 3.0%, MRN 1.1%, PHONE 0.3%, canaries 1/4; README model section missing
R16 R17 R20 | MUST | done-unverified | kill-test, TMP/HOME grep, network-off + Linux runs not done
R4 R14 R18 R22 R24 R25 | NICE | not started / partial (R22 guard) | -

Unplanned work: none. 39ca495 (1 line, .claude/skills) is workflow tooling, committed on its own as MISTAKES line 17 asks.
Priority balance: 100% of feature lines in this range serve MUST R-ids (R10-R13); no NICE work.
Contradictions: none with Non-goals, Kill list or hard constraints (stdlib only, no new deps, deterministic, offline).
Core flow: steps 1-4 work end to end on dev (CONTRACT OK, READY TO SUBMIT, exit 0, keyed outputs).
Spike: done in Task 1 (ID-slot PSN); now superseded by cluster PSNs (D8).
Approach: still B (two-pass rules + union-find); D8-D10 record the changes. Switch trigger (leak > 25% or 4/4 canaries after Task 2): not fired (leak 1.3%, canaries 1/4).
Stuck signals: MISTAKES line 32 (constants inlined at the call site) seen 5, flagged again at dc168be; line 17 seen 3; ship.fail counters for R10/R11 reached 2 (an allowlist approval, now cleared). Churn 0.05, falling.
Gates: test-from-codebase, hardcode-check (WARN), complexity-audit and feature-log all ran for dc168be.

Corrective actions:
1. /unstick on MISTAKES line 32 (seen 5): add a guard that flags string and number literals in wards/ outside config.py, instead of catching them one by one in review.
2. Next task: the V0 gate items - R16 kill-test, R17 TMP/HOME grep, R20 network-off run, R23 README model section - then R5/R7 residual leaks (N1 gazetteer).
3. Run setup in clean Python 3.10 and 3.12 venvs before the freeze (MISTAKES line 11).
Not verified: Linux behaviour; hidden-set generalisation beyond the R22 ratchet.
