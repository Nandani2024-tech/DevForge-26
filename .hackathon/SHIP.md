2026-11-26 22:50 | R10 R11 R12 R13 | BLOCKED
gate | verdict | blockers | warnings
scope | PASS | 0 | 0 (tooling edit committed separately as 39ca495)
tests | FAIL | 1 (test_r22_vocab_overlap_ratchet: 4 allowlist lines need user approval; not a code bug) | 0
hardcode | WARN | 0 | 4 (H1-H4 in REVIEW.md)
complexity | PASS | 0 | 0
ui | SKIPPED (no UI changes) | - | -
Kit: CONTRACT OK; READY TO SUBMIT; check_dev leak 1.3%, PIN 0.0%, MRN 1.1%, medical 100.0%, F0.5 0.96 (P 1.00, R 0.84), wrong merges 0; pytest 77/78.
Unblock: user approves these allowlist lines (reviewer adds them, then re-run /verify-commit):
  email | wards/config.py | LINK_CONTACT_ID_TYPES | contact schema field
  pin | wards/config.py | PIN_LABEL_WORDS | Indian postal code (PIN) field
  pin | wards/patterns.py | redact_identifiers | Indian postal code (PIN) field
  patient | wards/slots.py | _PSN_TEXT_SLOT_KINDS | clinical schema word
Optional WARN cleanups: see REVIEW.md H1-H4.
2026-11-26 23:05 | 4 allowlist lines added (user-approved); H1-H4 fixed; bulk scale test now asserts growth ratio | pytest 78/78; check_dev unchanged; sanitized/ + records.jsonl byte-identical to the 22:30 run
