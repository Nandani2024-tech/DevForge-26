"""Scale bench for wards.patterns.redact_identifiers (1x/10x/100x lines of a dense ID text)."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wards.patterns import redact_identifiers
line = "Pt Ram ph 9876543210 Aadhaar 8265 7330 7111 UHID: ABC-123456 Dolo 650mg 1-0-1\n"
for n in (200, 2000, 20000):
    text = line * n
    t = time.perf_counter(); redact_identifiers(text); dt = time.perf_counter() - t
    print(f"lines={n} bytes={len(text)} sec={dt:.3f}")
