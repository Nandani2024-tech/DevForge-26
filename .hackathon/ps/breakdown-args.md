Official statement: ../Secret-Wards-ToolKit/docs/PROBLEM_STATEMENT.md and .hackathon/ps/track3.pdf. Output format: docs/SPEC.md. Scoring: docs/SCORING.md and scoring.toml. Ignore overview.pdf's Track 3 description (it is wrong).
Rules for the spec:
- R1 must be the run contract: raksha.toml + main.py --input --output produce sanitized/, report.json, records.jsonl. Acceptance: validate_output.py prints CONTRACT OK.
- Acceptance tests use the kit tools: validate_output.py (format), check_dev.py (quality, with a target number per R-id), check_submission.py --run (determinism, changed secret, no secret written, input untouched).
- Record the schemas, file types and counts from dev/, but never copy patient names, IDs or values from dev/ or truth/ into .hackathon files (no hardcoding).
- Dev machine is Windows; the evaluator is Linux (2 CPU, 4 GB, 15 min, offline). Note peak-RSS measurement needs a cross-platform method.
- Cover every requirement. The V0 cut happens later in /idea-and-scope.