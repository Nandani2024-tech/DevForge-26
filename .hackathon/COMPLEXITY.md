# complexity-audit | WORKTREE @ 1f885cf | 2026-11-26 22:01 | verdict PASS
function | R-id | time | space | target | measured (1x/10x/100x) | verdict
_decide_text_date_orders (wards/pipeline.py) | R12 | O(R + total dates), dict/set lookups | O(dates) | O(dates) | dev run 1.74 s total | meets
date_order_evidence (wards/dates.py) | R12 | O(len(text)), one pass per regex | O(dates) | O(bytes) | inside dev run | meets
link_records | R10 | O(S·R·α(R)) | O(R) | O(R·α(R)) | 0.002/0.018/0.238 s | meets
generalise_text_qis | R13 | O(len) | O(len) | O(bytes) | 0.002/0.020/0.202 s; one line 0.002/0.019/0.209 s | meets
shift_dates_in_text | R12 | O(len) | O(len) | O(dates) | 0.003/0.032/0.329 s; one line 0.003/0.032/0.319 s | meets
dev run | R20 | - | - | < 20 s, < 512 MB | 1.74 s, 25.36 MB peak RSS | meets
Not verified: _decide_text_date_orders benched alone at 3 sizes (measured only inside the dev run); Linux run.
