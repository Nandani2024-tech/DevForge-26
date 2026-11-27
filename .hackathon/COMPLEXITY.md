# COMPLEXITY | range WORKTREE on 357b571 | 2026-11-27 | verdict PASS

function (file:line) | R-id | time | space | target | measured | verdict
_process_text + redact_known_names_in_text (pipeline.py, channels.py) | R7,R9,R20 | O(len(text)): one protect mask + one token scan per segment | O(len(text)) | O(bytes) per file | text doc 500/5,000/50,000 lines: 0.32/2.71/33.58 s (357b571: 0.26/2.43/21.9 s); growth x8.5 / x12.4 per 10x | meets (1.5x slower at 50k lines)
build_protect_mask ASHA branch (names.py) | R7,R8 | O(60) look-back per ASHA match, bounded | O(1) | linear | included above | meets
dev run | R20 | - | - | < 20 s, < 512 MB | 2.09 s, 25.7 MB (report.json) | meets
whole-pipeline text scale test | R7,R9 | - | - | ratio bounds | test_r7_r9_whole_pipeline_plain_text_scales_linearly passes | meets

Not verified: peak RSS at 50k lines; the x12.4 step at 50k lines (slightly above linear) was not profiled.
