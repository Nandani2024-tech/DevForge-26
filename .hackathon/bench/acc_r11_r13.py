"""Measure R11 claim-in-record, R12 intervals, R13 band truthfulness on one output folder."""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import csv, hashlib, io, json, re, sys, datetime as dt, collections
from pathlib import Path
sys.path.insert(0, r"C:/Devforge")
from wards.ingest import decode_bytes
from wards.dates import parse_dob_iso

KIT = Path(r"C:/Secret-Wards-ToolKit/dev"); OUT = Path(sys.argv[1])
truth = json.load(open(KIT / "truth/truth.json", encoding="utf-8"))
rep = json.load(open(OUT / "report.json", encoding="utf-8"))
out_by_sha = collections.defaultdict(list)
for f in rep["files"]:
    if f.get("output"): out_by_sha[f["input_sha256"]].append(f["output"])
def text_of(p):
    return (OUT / p).read_text(encoding="utf-8")
def ptr(obj, p):
    for part in [x.replace("~1", "/").replace("~0", "~") for x in p.split("/")[1:]]:
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj

# R11: claim found inside its record
recs = [json.loads(l) for l in (OUT / "records.jsonl").read_text(encoding="utf-8").splitlines()]
ok = tot = 0
for r in recs:
    if not r["patient"]: continue
    tot += 1; t = text_of(r["file"]); loc = r.get("out", r["loc"])
    if loc.startswith("row:"):
        rows = list(csv.reader(io.StringIO(t, newline=""), delimiter="\t" if r["file"].endswith(".tsv") else ","))
        seg = "|".join(rows[int(loc[4:]) + 1])
    elif loc.startswith("/"):
        seg = json.dumps(ptr(json.loads(t), loc), ensure_ascii=False)
    else: seg = t
    ok += r["patient"] in seg
print(f"R11 claims found in record: {ok}/{tot}")

# R12 / R13 from truth units
offs_by_unit = collections.defaultdict(list); offs_by_pt = collections.defaultdict(set)
unparsed = 0; bands_bad = bands_tot = 0; dob_bad = dob_tot = 0
for path, fe in sorted(truth["files"].items()):
    outs = out_by_sha.get(fe["sha256"]) or []
    if not outs: continue
    t = text_of(outs[0]); fmt = fe["format"]
    rows = list(csv.reader(io.StringIO(t, newline=""), delimiter=fe.get("delimiter") or ",")) if fmt in ("csv", "tsv") else None
    raw_hdr = None
    if rows is not None:
        raw = decode_bytes((KIT / "input" / path).read_bytes())
        raw_txt = raw[0] if isinstance(raw, tuple) else raw
        raw_hdr = next(csv.reader(io.StringIO(raw_txt, newline=""), delimiter=fe.get("delimiter") or ","))
    data = json.loads(t) if fmt in ("json", "fhir") else None
    def value(loc, p):
        if rows is not None:
            return rows[int(loc[4:]) + 1][raw_hdr.index(p[4:])]
        base = "" if loc == "doc" else loc
        return ptr(data, base + p)
    for loc, u in fe["units"].items():
        for d in u.get("dates") or []:
            try:
                if "path" in d: v = str(value(loc, d["path"]))
                else:
                    m = re.search(re.escape(d["anchor"]) + r"\s*([^\n]+)", t); v = m.group(1) if m else ""
                iso = parse_dob_iso(v, order=d["hint"])
            except (KeyError, IndexError, ValueError, TypeError): iso = None
            if iso is None: unparsed += 1; continue
            off = (dt.date.fromisoformat(iso) - dt.date.fromisoformat(d["true"])).days
            offs_by_unit[(path, loc)].append(off); offs_by_pt[d["patient"]].add(off)
        for f in u.get("fields") or []:
            try: v = str(value(loc, f["path"]))
            except (KeyError, IndexError, ValueError, TypeError): continue
            if f["kind"] == "age":
                m = re.search(r"(\d+)\s*-\s*(\d+)|(\d+)\+|(\d+)", v)
                if m is None: continue  # placeholder: no band claimed
                bands_tot += 1
                if m.group(1): good = int(m.group(1)) <= f["true"] <= int(m.group(2))
                elif m.group(3): good = f["true"] >= int(m.group(3))
                else: good = int(m.group(4)) == f["true"]
                bands_bad += not good
units_multi = [o for o in offs_by_unit.values() if len(o) > 1]
print(f"R12 dates parsed: {sum(map(len, offs_by_unit.values()))}, not found/parsed: {unparsed}")
print(f"R12 records with >=2 dates: {len(units_multi)}, intervals exact in {sum(len(set(o)) == 1 for o in units_multi)}")
pts = [p for p, o in offs_by_pt.items()]
print(f"R12 truth patients: {len(pts)}, with one offset across all their records: {sum(len(offs_by_pt[p]) == 1 for p in pts)}")
all_offs = [o for p in pts for o in offs_by_pt[p]]
print(f"R12 offsets: zero-shift {sum(o == 0 for o in all_offs)}, |shift|>180 {sum(abs(o) > 180 for o in all_offs)}, |shift|<7 {sum(abs(o) < 7 for o in all_offs)}, distinct {len(set(all_offs))}")
print(f"R13 age bands: {bands_tot} checked, excluding true age: {bands_bad}")
print("--- detail")
for k, o in offs_by_unit.items():
    if len(set(o)) > 1 or any(abs(x) > 180 for x in o): print("unit", k[0].split("/")[0], k[1], o)
for path, fe in sorted(truth["files"].items()):
    outs = out_by_sha.get(fe["sha256"]) or []
    if not outs or fe["format"] not in ("csv","tsv","json"): continue
    t = text_of(outs[0])
    for loc, u in fe["units"].items():
        for f in u.get("fields") or []:
            if f["kind"] != "age": continue
            try:
                if fe["format"] in ("csv","tsv"):
                    raw = decode_bytes((KIT / "input" / path).read_bytes()); raw_txt = raw[0] if isinstance(raw, tuple) else raw
                    hdr = next(csv.reader(io.StringIO(raw_txt, newline=""), delimiter=fe.get("delimiter") or ","))
                    rows = list(csv.reader(io.StringIO(t, newline=""), delimiter=fe.get("delimiter") or ","))
                    v = rows[int(loc[4:]) + 1][hdr.index(f["path"][4:])]
                else:
                    v = str(ptr(json.loads(t), ("" if loc == "doc" else loc) + f["path"]))
            except (KeyError, IndexError, ValueError): continue
            m = re.search(r"(\d+)\s*-\s*(\d+)|(\d+)\+", v)
            if m and m.group(1) and not (int(m.group(1)) <= f["true"] <= int(m.group(2))): print("age", path.split("/")[0], fe["format"], f["path"], "true", f["true"], "out", v)
            if m and m.group(3) and f["true"] < int(m.group(3)): print("age", path.split("/")[0], f["path"], "true", f["true"], "out", v)
print("--- date detail")
for path, fe in sorted(truth["files"].items()):
    for loc, u in fe["units"].items():
        o = offs_by_unit.get((path, loc), [])
        if (len(set(o)) > 1 or any(abs(x) > 180 for x in o)):
            for d in u.get("dates") or []:
                print(fe["format"], d.get("anchor") or d.get("path"), "hint", d["hint"], "true", d["true"])
            raw = (KIT / "input" / path).read_bytes().decode("utf-8", "replace")
            outp = text_of(out_by_sha[fe["sha256"]][0])
            for d in u.get("dates") or []:
                a = d.get("anchor")
                if a:
                    mi = re.search(re.escape(a) + r"[^\n]{0,40}", raw); mo = re.search(re.escape(a) + r"[^\n]{0,40}", outp)
                    print("   in :", re.sub(r"[A-Za-z]{3,}", "W", mi.group(0)) if mi else None); print("   out:", re.sub(r"[A-Za-z]{3,}", "W", mo.group(0)) if mo else None)
