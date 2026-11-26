# STATE
phase0.ps-breakdown: done, 25 requirements (R1 run contract ... R25 brief PDF) with kit-tool acceptance tests; starter baseline measured (leak 84.1%, canaries 4/4, F0.5 0); team name known: Procrastinators (01-ps.md change log 2026-11-26).
phase0.domain-primer: done, 02-domain.md (8 sources verified, 6 oracle groups hand-derived; Aadhaar Verhoeff holds on only 79% of dev values -> hint, not gate); 5 preventive MISTAKES entries.
phase0.prior-art-scan: done, Reuse Stack = stdlib + psutil, cryptography, rapidfuzz, jellyfish (runtime) + fhir.resources R4B, Faker, pytest (tests); custom transliteration beats the library; evaluator Python version UNKNOWN; R4 acceptance change NEEDS USER APPROVAL.
decisions 2026-11-26: R4 acceptance edited (user-approved, 01-ps change log); target Python 3.10-3.12, pins rapidfuzz 3.14.5 + jellyfish 1.2.1; ABHA format closed (shape + label context). Pending: setup test in clean 3.10 + 3.12 venvs before submit.
phase0.idea-and-scope: LOCKED, B simple custom core (starter + two-pass rules), 3 tasks: scaffold / detection / linkage+privacy; V0 gate excludes base64 channel until N4
phase0.build-rules: done
build.current-task: Task 3 R10 R11 R12 R13 (linkage + conflict guard, HMAC PSN in record + records.jsonl, per-patient date shift incl. DOB, age bands + top-code, district, PIN prefix; then V0 gate)
build.test-from-codebase: 84/84 for R12 R13 @ dc168be
build.hardcode-check: WARN @ dc168be
build.complexity-audit: PASS @ dc168be
build.ui-ux-review: SKIPPED (no UI changes) @ dc168be
build.feature-log: R12 R13 logged @ dc168be
ship.last: dc168be | R12 R13 | 2026-11-26
build.ship: R12 R13 committed dc168be
build.drift-check: ON TRACK @ dc168be
build.unstick: R22 | blocker: dev-derived word lists recur, guard blind to non-PII dev vocab | chosen: B (ratchet, D6); C deferred to N7
