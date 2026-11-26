"""N4 base64 scaling bench: one FHIR-like JSON with a text attachment at 1x/10x/100x."""
import base64, json, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wards.config import load_policy
from wards.pipeline import run_pipeline
line = "Patient Name: Zoravar Chatterjee, phone 9000011111, Hb 12.5 g/dL, Dolo 650mg 1-0-1.\n"
for reps in (200, 2000, 20000):
    td = Path(tempfile.mkdtemp()); inp = td / "in"; inp.mkdir()
    payload = base64.b64encode((line * reps).encode()).decode()
    doc = {"resourceType": "DocumentReference", "content": [{"attachment": {"contentType": "text/plain", "data": payload}}],
           "fields": [base64.b64encode(f"Name: Zoravar Chatterjee row {i}".encode()).decode() for i in range(reps // 10)]}
    (inp / "d.json").write_text(json.dumps(doc), encoding="utf-8")
    t = time.perf_counter(); run_pipeline(inp, td / "out", b"k", load_policy()); dt = time.perf_counter() - t
    print(f"reps {reps:6d} bytes {len(payload):9d} seconds {dt:.3f}")
