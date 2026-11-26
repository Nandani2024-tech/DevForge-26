"""Scale bench for Task 3 functions (1x/10x/100x). Invented data only."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wards.linkage import RecordEvidence, link_records
from wards.dates import shift_dates_in_text
from wards.generalise import generalise_text_qis
import inspect

def recs(n):
    out = []
    for i in range(n):
        p = i // 3  # 3 records per invented patient
        ids = (("mrn", f"zq{p:07d}"),) if i % 3 != 2 else (("phone", f"9{p:09d}"),)
        out.append(RecordEvidence(i, f"f{i%50}.csv", f"row:{i}", ids, f"zorvak{p} quinlet", f"19{p%90+10:02d}-0{p%9+1}-1{p%9}", None))
    return out

def t(fn, *a, **k):
    s = time.perf_counter(); fn(*a, **k); return time.perf_counter() - s

print("shift sig", inspect.signature(shift_dates_in_text))
for n in (1000, 10000, 100000):
    print("link_records", n, round(t(link_records, recs(n)), 3))
line = "Adm 12/03/2026, DOA 2026-03-14, Age: 48/F, PIN: 226001, Pulse 78/min. "
for m in (200, 2000, 20000):
    txt = "\n".join([line]*m); one = line*m
    print("generalise lines", m, round(t(generalise_text_qis, txt, width=5, top_code=85, prefix_digits=3), 3),
          "one-line", round(t(generalise_text_qis, one, width=5, top_code=85, prefix_digits=3), 3))
for m in (200, 2000, 20000):
    txt = "\n".join([line]*m); one = line*m
    print("shift lines", m, round(t(shift_dates_in_text, txt, 17), 3), "one-line", round(t(shift_dates_in_text, one, 17), 3))
