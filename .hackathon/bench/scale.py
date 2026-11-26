"""Scale bench: csv + json + txt at 1x/10x/100x; calls the real run_pipeline."""
import json, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wards.config import load_policy
from wards.pipeline import run_pipeline
for n in (1000, 10000, 100000):
    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / "in"; inp.mkdir()
        (inp / "a.csv").write_text("UHID,Name,Hb\n" + "".join(f"HSP{i:07d},Name: X{i},13.{i%10}\n" for i in range(n)), encoding="utf-8")
        (inp / "b.json").write_text(json.dumps({"results": [{"uhid": f"HSP{i:07d}", "test": "Hb", "value": 13.1} for i in range(n)]}), encoding="utf-8")
        (inp / "c.txt").write_text("UHID: HSP0000001\n" + "Pt mobile 9876543210 BP 120/80\n" * n, encoding="utf-8")
        t = time.monotonic(); r = run_pipeline(inp, Path(td) / "out", b"s", load_policy())
        print(n, round(time.monotonic() - t, 2), "s", r.report["resources"]["peak_rss_mb"], "MB")
