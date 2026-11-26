#!/usr/bin/env python3
"""ESTIMATE of the official Secret Wards score on the practice data (measurement only).

Implements Secret-Wards-ToolKit docs/SCORING.md and docs/ATTACKS.md with the weights in
scoring.toml, against our output for dev/input and dev/truth/truth.json. The organisers'
evaluator code is not published, so every number is an ESTIMATE; the places where the
published text leaves room for interpretation are listed in the printed table and in
ASSUMPTIONS below. Prints counts and scores only, never PII values.

Usage (repo root):
  python tools/estimate_score.py --kit ..\\Secret-Wards-ToolKit --work <rehearsal work dir>
(the work dir is the one tools/rehearse_eval.py wrote: out_A1, out_B, rehearsal.json)
  --input <dir> --truth <file> override dev/input and truth.json (used for the mutated set).
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import itertools
import json
import math
import re
import sys
import tomllib
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sw_common as C  # noqa: E402

ASSUMPTIONS = [
    "allowed occurrences = key occurrences inside the unit's preserve texts (input side)",
    "if a key is not found in the located input record, pii_occ is taken as 1 (conservative)",
    "contextual-precision trap groups are mapped from preserve kinds (doctor, complaint, history, "
    "ward/hospital/department, dose, frequency, eponym, diagnosis for k/c/o, 'asha' context); "
    "doctor probes in meaning-trap units form the doctor-vs-relative group",
    "dates are aligned by order of date tokens inside the input and output record",
    "generalisation fields without a path (free text) are not scored",
    "lab medians pair a test with the value at the sibling path (CSV row / JSON parent)",
    "FHIR validity uses our own structural checks, not raksha_eval/scoring/fhir.py or fhir.resources",
    "attacker name matching uses a skeleton key; Devanagari is transliterated with "
    "wards.linkage._transliterate_deva_word (read-only import)",
    "A4 profile join uses PSNs present in the record and reference-like field values",
    "A5 success = weight on the true person's profiles / weight of all matching profiles",
]

TRAP_GROUP = {"doctor": "doctor", "complaint": "c/o-complaint", "history": "h/o",
              "ward": "hospital-ward", "hospital": "hospital-ward", "department": "hospital-ward",
              "dose": "dose", "frequency": "1-0-1", "eponym": "eponym", "diagnosis": "k/c/o"}
HOSP = {"snj": "sanjeevani", "jjh": "jeevan jyoti", "ass": "arogya", "dhh": "hardoi"}
HOSP_FILE = {"sanjeevani": "sanjeevani", "jeevanjyoti": "jeevan jyoti", "arogya": "arogya",
             "dhhardoi": "hardoi"}


def f_beta(p, r, b):
    return (1 + b * b) * p * r / (b * b * p + r) if p + r else 0.0


def loglin(x, good, limit):
    if x <= good:
        return 1.0
    if x >= limit:
        return 0.0
    return 1 - (math.log(x) - math.log(good)) / (math.log(limit) - math.log(good))


def mean(xs, default=0.0):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else default


# ============================================================== loading
class Release:
    """One release: either our output (sanitized/ + records.jsonl) or the raw input."""

    def __init__(self, truth, inp: Path, out: Path | None):
        self.truth, self.inp, self.out = truth, inp, out
        self.raw = out is None
        self.report, self.renamed, self.recs = {}, {}, defaultdict(dict)
        self.recs_out = defaultdict(dict)
        if out:
            try:
                self.report = json.loads((out / "report.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.report = {}
            self.renamed = {e.get("input_sha256"): e.get("output") for e in self.report.get("files") or []}
            self.status = {e.get("input_sha256"): e.get("status") for e in self.report.get("files") or []}
            for line in (out / "records.jsonl").read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    f = str(r["file"]).replace("sanitized/", "", 1)
                    self.recs[f][r["loc"]] = r.get("patient")
                    if r.get("out"):
                        self.recs_out[f][r["loc"]] = r["out"]
        self.cache = {}

    def out_rel(self, rel, f):
        if self.raw:
            return rel
        d = self.renamed.get(f["sha256"])
        if d:
            return str(d).replace("sanitized/", "", 1)
        return None if self.status.get(f["sha256"]) == "quarantined" else rel

    def parsed(self, rel, f):
        o = self.out_rel(rel, f)
        key = (o, f["format"])
        if key not in self.cache:
            if o is None:
                self.cache[key] = None
            else:
                root = self.inp if self.raw else self.out / "sanitized"
                enc = f.get("encoding") if self.raw else None
                self.cache[key] = C.ParsedFile(root / o, f["format"], f.get("delimiter"), enc)
        return self.cache[key]

    def record(self, rel, f, loc):
        """(text, fields, located, out_rel)"""
        o = self.out_rel(rel, f)
        if loc == "@filename":
            return (o or ""), None, o is not None, o
        pf = self.parsed(rel, f)
        if pf is None or not pf.exists:
            return "", None, False, o
        oloc = self.recs_out.get(o, {}).get(loc, loc)
        t, fl, ok = pf.record(oloc)
        return t, fl, ok, o

    def pseudonym(self, o, loc):
        recs = self.recs.get(o or "", {})
        if loc in recs:
            return recs[loc]
        if loc.startswith("/"):
            parts = loc.split("/")
            for i in range(len(parts) - 1, 1, -1):
                if "/".join(parts[:i]) in recs:
                    return recs["/".join(parts[:i])]
        return recs.get("doc")


def entity_keys(e):
    if e.get("match") == "name":
        return [(C.norm(t), "name") for t in e.get("tokens") or [] if t]
    k = e.get("key") if e.get("key") is not None else e["surface"]
    return [(C.norm(str(k)), e["match"])]


# ============================================================== leak engine
class Units:
    def __init__(self, truth, inp_rel: Release, rel_out: Release):
        self.items = []  # dicts per unit
        for rel, f in truth["files"].items():
            for loc, u in f["units"].items():
                it, ifl, iok, _ = inp_rel.record(rel, f, loc)
                ot, ofl, ook, orel = rel_out.record(rel, f, loc)
                self.items.append({"rel": rel, "f": f, "loc": loc, "u": u,
                                   "in": it, "in_n": C.nz(it), "in_fields": ifl,
                                   "out": ot, "out_n": C.nz(ot) if ook or ot else "",
                                   "out_fields": ofl, "located": ook, "orel": orel,
                                   "in_header": (inp_rel.parsed(rel, f).header
                                                 if inp_rel.parsed(rel, f) else None)})


def leak_of_mention(it, e):
    pres = C.nz("\n".join(p["text"] for p in it["u"].get("preserve") or []))
    if it["orel"] is None and e["channel"] != "filename":
        return 0.0, []
    ls = []
    for k, m in entity_keys(e):
        allowed = C.count_key(pres, k, m)
        occ_in = C.count_key(it["in_n"], k, m)
        pii = occ_in - allowed
        if pii <= 0:
            allowed, pii = 0, 1
        occ_out = C.count_key(it["out_n"], k, m)
        ls.append(min(max(occ_out - allowed, 0), pii) / pii)
    return mean(ls), ls


# ============================================================== categories
def detection(units, cfg):
    tw = cfg["detection"]["type_weights"]
    by_type, by_script = defaultdict(list), defaultdict(list)
    leaked_mentions = Counter()
    for it in units.items:
        for e in it["u"]["entities"]:
            lk, _ = leak_of_mention(it, e)
            it.setdefault("leaks", []).append((e, lk))
            by_type[e["type"]].append(1 - lk)
            by_script[e["script"]].append(1 - lk)
            if lk > 0:
                leaked_mentions[e["type"]] += 1
    type_rec = {t: mean(v) for t, v in by_type.items()}
    script_rec = {s: mean(v) for s, v in by_script.items()}
    wsum = sum(tw.get(t, 1.0) for t in type_rec)
    macro_type = sum(tw.get(t, 1.0) * r for t, r in type_rec.items()) / wsum
    macro_script = mean(script_rec.values())
    mix = cfg["detection"]["type_mix"]
    recall = mix * macro_type + (1 - mix) * macro_script
    groups = defaultdict(list)
    for it in units.items:
        meaning = "meaning_trap" in (it["u"].get("tags") or [])
        for p in it["u"].get("preserve") or []:
            g = TRAP_GROUP.get(p["kind"])
            if p["kind"] == "context" and "asha" in p["text"].lower():
                g = "asha"
            if g == "doctor" and meaning:
                g = "doctor-vs-relative"
            if g and it["orel"] is not None:
                groups[g].append(C.norm(p["text"]) in it["out_n"])
    clean_tr = token_retention(units, clean_only=True)
    parts = {g: mean(v) for g, v in groups.items()}
    parts["clean_token_retention"] = clean_tr
    precision = mean(parts.values())
    score = f_beta(precision, recall, cfg["detection"]["beta"])
    return {"score": score, "recall": recall, "precision": precision, "macro_type": macro_type,
            "macro_script": macro_script, "type_recall": type_rec, "script_recall": script_rec,
            "precision_groups": parts, "mentions_leaked": dict(leaked_mentions)}


def token_retention(units, clean_only=False):
    tot = kept = 0
    for it in units.items:
        if clean_only and not it["f"].get("clean"):
            continue
        if it["loc"] in ("@filename", "@header", "@file") or it["orel"] is None and not clean_only:
            pass
        excl = {C.norm(x) for x in it["u"].get("exclude") or []}
        for e in it["u"]["entities"]:
            excl.update(k for k, _ in entity_keys(e))
        tin = Counter(w for w in C._WORD.findall(it["in_n"]) if w not in excl and not w.isdigit())
        tout = Counter(C._WORD.findall(it["out_n"]))
        tot += sum(tin.values())
        kept += sum(min(c, tout[w]) for w, c in tin.items())
    return kept / tot if tot else 1.0


def probe_score(it, p):
    t = C.norm(p["text"])
    if it["orel"] is None or t not in it["out_n"]:
        return 0.0
    if not p.get("path"):
        return 1.0
    v = C.field_value(it["out_fields"], p["path"], it["in_header"])
    return 1.0 if v is not None and t in C.nz(str(v)) else 0.8


def align_dates(it, hint):
    din = [m.group(0) for m in C.DATE_TOKEN.finditer(it["in"])]
    dout = [m.group(0) for m in C.DATE_TOKEN.finditer(it["out"])]
    mp = defaultdict(list)
    if len(din) == len(dout):
        for a, b in zip(din, dout):
            ia, ib = C.parse_date(a, hint) or C.parse_date(a, "mdy" if hint == "dmy" else "dmy"), \
                C.parse_date(b, hint) or C.parse_date(b, "mdy" if hint == "dmy" else "dmy")
            if ia:
                mp[ia].append(ib)
    return mp


def utility(units, reg, truth, cfg):
    w = cfg["utility"]["weights"]
    # clinical probes
    num = den = 0.0
    for it in units.items:
        for p in it["u"].get("preserve") or []:
            wt = p.get("weight", 1.0)
            den += wt
            num += wt * probe_score(it, p)
    clinical = num / den if den else 1.0
    # temporal
    per_pat = defaultdict(list)
    los_true, los_out, los_scores = [], [], []
    for it in units.items:
        ds = it["u"].get("dates") or []
        if not ds:
            continue
        mp = align_dates(it, it["f"].get("date_hint") or "dmy")
        used = Counter()
        ev = {}
        for d in ds:
            lst = mp.get(d["true"], [])
            o = lst[used[d["true"]]] if used[d["true"]] < len(lst) else None
            used[d["true"]] += 1
            per_pat[d.get("patient") or it["u"].get("patient")].append((d["true"], o))
            ev[d["event"]] = (d["true"], o)
        if "admission" in ev and "discharge" in ev:
            (ta, oa), (td, od) = ev["admission"], ev["discharge"]
            tl = (date.fromisoformat(td) - date.fromisoformat(ta)).days
            los_true.append(tl)
            if oa and od:
                ol = (date.fromisoformat(od) - date.fromisoformat(oa)).days
                los_out.append(ol)
                los_scores.append(1.0 if ol == tl else 0.0)
            else:
                los_scores.append(0.0)
    pair_scores = []
    for pid, evs in per_pat.items():
        evs = list(dict.fromkeys(evs))
        for (t1, o1), (t2, o2) in itertools.combinations(evs, 2):
            if not (o1 and o2):
                pair_scores.append(0.0)
                continue
            dt = (date.fromisoformat(t2) - date.fromisoformat(t1)).days
            do = (date.fromisoformat(o2) - date.fromisoformat(o1)).days
            pair_scores.append(1.0 if dt == do else 0.5 if abs(dt - do) == 1 else 0.0)
    interval = mean(pair_scores, 1.0)
    los = mean(los_scores, 1.0)
    temporal = 0.6 * interval + 0.4 * los
    # generalisation
    gscores, gkinds, untruthful = [], defaultdict(list), 0
    pat_reg = {pid: reg.get(p["rid"]) for pid, p in truth["patients"].items()}
    for it in units.items:
        for fd in it["u"].get("fields") or []:
            if not fd.get("path") or it["orel"] is None:
                continue
            v = C.field_value(it["out_fields"], fd["path"], it["in_header"])
            s, bad = gen_score(fd, None if v is None else str(v), pat_reg.get(fd.get("patient")))
            untruthful += bad
            gscores.append(s)
            gkinds[fd["kind"]].append(s)
    generalization = mean(gscores, 1.0)
    # statistics
    stats = statistics(units, los_true, los_out)
    tok = token_retention(units)
    located = [it["located"] for it in units.items if it["f"].get("expect") == "sanitize"]
    record_ret = mean(located)
    parts = {"clinical_probes": clinical, "temporal": temporal, "generalization": generalization,
             "statistics": stats["score"], "token_retention": tok, "record_retention": record_ret}
    score = sum(w[k] * parts[k] for k in w)
    return {"score": score, "parts": parts, "interval": interval, "los": los,
            "date_pairs": len(pair_scores), "gen_by_kind": {k: mean(v) for k, v in gkinds.items()},
            "untruthful_bands": untruthful, "stats": stats}


def gen_score(fd, v, regrow):
    if v is None:
        return 0.0, 0
    k, tv = fd["kind"], fd["true"]
    vn = C.norm(v).strip()
    if k == "age":
        m = re.match(r"\s*(\d{1,3})\s*(?:-|–|to)\s*(\d{1,3})", vn)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if not lo <= tv <= hi:
                return 0.0, 1
            wd = hi - lo + 1
            return (0.9 if wd <= 5 else 0.8 if wd <= 10 else 0.6 if wd <= 20 else 0.3), 0
        m = re.match(r"\s*(\d{1,3})\s*\+", vn)
        if m:
            return (0.3, 0) if tv >= int(m.group(1)) else (0.0, 1)
        m = re.match(r"\s*(\d{1,3})\b", vn)
        if m:
            return (1.0, 0) if int(m.group(1)) == tv else (0.0, 1)
        return 0.0, 0
    if k == "dob":
        ds = C.parse_dates(vn) or C.parse_dates(vn, "mdy")
        if ds:
            d, t = date.fromisoformat(ds[0]), date.fromisoformat(tv)
            return (1.0 if d == t else 0.9 if abs((d - t).days) <= 365 else 0.0), 0
        m = re.fullmatch(r"\s*(\d{4})\s*", vn)
        if m:
            return (0.8, 0) if m.group(1) == tv[:4] else (0.0, 1)
        return 0.0, 0
    if k == "pin":
        dg = re.sub(r"\D", "", vn)
        if dg == tv:
            return 1.0, 0
        if dg[:3] == tv[:3] and (len(dg) == 3 or re.fullmatch(r"\d{3}(?:0{3}|[*x]{3})", vn.replace(" ", ""))):
            return 0.7, 0
        return 0.0, 0
    if k == "village":
        if vn == C.norm(tv) or C.norm(tv) in vn:
            return 1.0, 0
        if regrow and C.norm(regrow["tehsil"]) in vn:
            return 0.8, 0
        if regrow and C.norm(regrow["district"]) in vn:
            return 0.7, 0
        return 0.0, 0
    if k in ("district", "gender"):
        tn = C.norm(str(tv))
        if k == "gender":
            hindi = {"पुरुष": "m", "महिला": "f", "स्त्री": "f", "मर्द": "m", "औरत": "f"}
            g = next((x for w, x in hindi.items() if w in vn), vn[:1])
            return (1.0 if g == tn[:1] else 0.0), 0
        if tn in vn or " ".join(words_of(tn)) in " ".join(words_of(vn))                 or "".join(words_of(tn)) == "".join(words_of(vn)):
            return 1.0, 0
        return 0.0, 0
    return 0.0, 0


def _num(v):
    m = re.search(r"-?\d+(?:\.\d+)?", str(v))
    return float(m.group(0)) if m else None


def statistics(units, los_true, los_out):
    # ICD-10 distribution
    cin, cout = Counter(), Counter()
    for it in units.items:
        for p in it["u"].get("preserve") or []:
            if p["kind"] == "diagnosis_code":
                c = C.norm(p["text"])
                cin[c] += 1
                if it["orel"] is not None and c in it["out_n"]:
                    cout[c] += 1

    def tvd(a, b):
        sa, sb = sum(a.values()), sum(b.values())
        if not sa or not sb:
            return 1.0
        return 0.5 * sum(abs(a[k] / sa - b[k] / sb) for k in set(a) | set(b))
    icd = (1 - tvd(cin, cout)) * (sum(cout.values()) / max(1, sum(cin.values())))

    def bins(xs):
        return Counter(min(x, 15) if x < 4 else (5 if x <= 5 else 7 if x <= 7 else 14 if x <= 14 else 15)
                       for x in xs)
    los = (1 - tvd(bins(los_true), bins(los_out))) * (len(los_out) / max(1, len(los_true))) if los_true else 1.0
    # lab medians
    tv, ov = defaultdict(list), defaultdict(list)
    for it in units.items:
        pres = it["u"].get("preserve") or []
        tests = [p for p in pres if p["kind"] == "lab_test" and p.get("path")]
        vals = {p["path"]: p for p in pres if p["kind"] == "lab" and p.get("path")}
        for tp in tests:
            par = tp["path"].rsplit("/", 1)[0] if tp["path"].startswith("/") else None
            vp = next((p for path, p in vals.items() if (par and path.startswith(par + "/"))
                       or (not par and path.startswith("col:"))), None)
            if not vp:
                continue
            x = _num(vp["text"])
            if x is None:
                continue
            name = C.norm(tp["text"])
            tv[name].append(x)
            if it["orel"] is not None:
                o = C.field_value(it["out_fields"], vp["path"], it["in_header"])
                y = _num(o) if o is not None else None
                if y is not None:
                    ov[name].append(y)

    def med(xs):
        xs = sorted(xs)
        n = len(xs)
        return (xs[n // 2] + xs[(n - 1) // 2]) / 2
    lab_ok = [1.0 if ov.get(t) and abs(med(ov[t]) - med(v)) <= 0.1 * abs(med(v)) else 0.0
              for t, v in tv.items()]
    lab = mean(lab_ok, 1.0)
    return {"score": mean([icd, los, lab]), "icd": icd, "los_hist": los, "lab_medians": lab,
            "lab_tests": len(tv)}


def identity(units, rel_out):
    rows = []
    for it in units.items:
        u = it["u"]
        if u.get("link") in ("required", "ambiguous") and u.get("patient"):
            psn = rel_out.pseudonym(it["orel"], it["loc"]) if it["orel"] else None
            rows.append((u["patient"], psn, u["link"], it))
    # pairwise precision over all units with a PSN (ambiguous included)
    by_psn = defaultdict(list)
    for i, (t, y, l, _) in enumerate(rows):
        if y:
            by_psn[y].append(i)
    tp = fp = 0
    for m in by_psn.values():
        for i, j in itertools.combinations(m, 2):
            if rows[i][0] == rows[j][0]:
                tp += 1
            else:
                fp += 1
    req = [i for i, r in enumerate(rows) if r[2] == "required"]
    by_true = defaultdict(list)
    for i in req:
        by_true[rows[i][0]].append(i)
    true_pairs = sum(len(v) * (len(v) - 1) // 2 for v in by_true.values())
    tp_req = sum(1 for v in by_true.values() for i, j in itertools.combinations(v, 2)
                 if rows[i][1] and rows[i][1] == rows[j][1])
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp_req / true_pairs if true_pairs else 0.0
    f05 = f_beta(prec, rec, 0.5)
    # B-cubed over required units
    clus = defaultdict(list)
    for i in req:
        clus[rows[i][1] or f"_single{i}"].append(i)
    bp, br = [], []
    for i in req:
        c = clus[rows[i][1] or f"_single{i}"]
        tset = by_true[rows[i][0]]
        inter = sum(1 for j in c if rows[j][0] == rows[i][0])
        bp.append(inter / len(c))
        br.append(inter / len(tset))
    b3 = f_beta(mean(bp), mean(br), 1.0)

    def trap_recall(pids):
        pairs = ok = 0
        for p in pids:
            v = by_true.get(p, [])
            for i, j in itertools.combinations(v, 2):
                pairs += 1
                ok += bool(rows[i][1] and rows[i][1] == rows[j][1])
        return ok / pairs if pairs else 1.0
    tr = units.truth_traps
    lang = trap_recall(tr["language"])
    frag = trap_recall(tr["fragmented"])
    hp = hok = 0
    for a, b in tr["homonym_pairs"]:
        ia = [i for i, r in enumerate(rows) if r[0] == a]
        ib = [i for i, r in enumerate(rows) if r[0] == b]
        for i in ia:
            for j in ib:
                hp += 1
                hok += not (rows[i][1] and rows[i][1] == rows[j][1])
    hom = hok / hp if hp else 1.0
    any_psn = any(r[1] for r in rows)
    score = (0.4 * f05 + 0.3 * b3 + 0.1 * lang + 0.1 * frag + 0.1 * hom) if any_psn else 0.0
    false_merge_psn = sum(1 for m in by_psn.values() if len({rows[i][0] for i in m}) > 1)
    return {"score": score, "precision": prec, "recall": rec, "f05": f05, "b3": b3,
            "language_trap": lang, "fragmented_trap": frag, "homonym": hom,
            "units": len(rows), "with_psn": sum(1 for r in rows if r[1]),
            "false_merge_psns": false_merge_psn}


# ============================================================== integrity
FHIR_BUNDLE_TYPES = {"document", "message", "transaction", "transaction-response", "batch",
                     "batch-response", "history", "searchset", "collection"}
_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_DT_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?)?)?$")


def fhir_check(tree):
    checks = []
    checks.append(isinstance(tree, dict) and tree.get("resourceType") == "Bundle")
    if not checks[0]:
        return 0.0, ["not a Bundle"]
    checks.append(tree.get("type") in FHIR_BUNDLE_TYPES)
    ids = set()
    entries = tree.get("entry") or []
    probs = []
    for e in entries:
        r = e.get("resource") or {}
        ok = isinstance(r.get("resourceType"), str) and isinstance(r.get("id"), str)
        checks.append(ok)
        if ok:
            ids.add(f"{r['resourceType']}/{r['id']}")
        if e.get("fullUrl"):
            ids.add(e["fullUrl"])
    for path, v in C.flatten(tree):
        k = path.rsplit("/", 1)[-1]
        if v == "\x00KEY":
            continue
        if k == "reference" and isinstance(v, str):
            ok = v in ids or v.startswith("#")
            checks.append(ok)
            if not ok:
                probs.append("unresolved reference")
        elif k in ("birthDate", "date") and isinstance(v, str):
            ok = bool(_DATE_RE.match(v) or _DT_RE.match(v))
            checks.append(ok)
            if not ok:
                probs.append(f"bad {k}")
        elif k in ("effectiveDateTime", "issued", "start", "end", "authoredOn", "recordedDate") \
                and isinstance(v, str):
            ok = bool(_DT_RE.match(v))
            checks.append(ok)
            if not ok:
                probs.append(f"bad {k}")
        elif k == "data" and "/attachment" in path.lower() or (k == "data" and isinstance(v, str)
                                                                and "content" in path):
            try:
                base64.b64decode(v, validate=True)
                checks.append(True)
            except Exception:
                checks.append(False)
                probs.append("bad base64")
        elif k == "gender" and isinstance(v, str):
            ok = v in ("male", "female", "other", "unknown")
            checks.append(ok)
            if not ok:
                probs.append("bad gender")
    return (1.0 if all(checks) else sum(checks) / len(checks)), sorted(set(probs))


def json_paths(obj):
    out = {}
    for p, v in C.flatten(obj):
        if v == "\x00KEY":
            continue
        out[re.sub(r"/\d+(?=/|$)", "/#", p)] = type(v).__name__
    return out


def integrity(truth, inp: Path, out: Path, rel_out: Release, rehearsal, units, cfg):
    w = cfg["integrity"]["weights"]
    san = out / "sanitized"
    fmt_ok, schema, fhir_s, fhir_probs = [], [], [], Counter()
    for rel, f in truth["files"].items():
        o = rel_out.out_rel(rel, f)
        if o is None or not (san / o).is_file():
            continue
        b = (san / o).read_bytes()
        try:
            txt = (b[3:] if b.startswith(b"\xef\xbb\xbf") else b).decode("utf-8")
        except UnicodeDecodeError:
            fmt_ok.append(0.0)
            continue
        fin = C.ParsedFile(inp / rel, f["format"], f.get("delimiter"), f.get("encoding"))
        fo = C.ParsedFile(san / o, f["format"], f.get("delimiter"), None)
        fmt_ok.append(1.0 if fo.ok or f["format"] not in ("csv", "tsv", "json", "fhir", "text") else 0.0)
        if f["format"] in ("csv", "tsv") and fin.ok and fo.ok:
            hdr_pii = any(u["entities"] for l, u in f["units"].items() if l == "@header")
            s = [len(fin.header) == len(fo.header),
                 hdr_pii or fin.header == fo.header,
                 len(fin.rows) == len(fo.rows),
                 all(len(a) == len(b) for a, b in zip(fin.rows, fo.rows))]
            schema.append(mean(s))
        elif f["format"] in ("json", "fhir") and fin.ok and fo.ok:
            pi, po = json_paths(fin.tree), json_paths(fo.tree)
            jac = len(set(pi) & set(po)) / max(1, len(set(pi) | set(po)))
            gen = [g.replace("key:", "") for g in f.get("generalizable") or []]
            same = [pi[p] == po[p] for p in set(pi) & set(po) if not any(g and g in p for g in gen)]
            schema.append(0.5 * jac + 0.5 * mean(same, 1.0))
            if f["format"] == "fhir":
                s, probs = fhir_check(fo.tree)
                fhir_s.append(s)
                fhir_probs.update(probs)
        elif f["format"] == "text":
            li, lo = fin.raw.count("\n") + 1, txt.count("\n") + 1
            schema.append(min(li, lo) / max(li, lo))
    # pseudonym consistency
    claims = ok = 0
    for line in (out / "records.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if not r.get("patient"):
            continue
        claims += 1
        rel = str(r["file"]).replace("sanitized/", "", 1)
        pf = C.ParsedFile(san / rel, "json" if rel.endswith(".json") else
                          ("csv" if rel.endswith(".csv") else "tsv" if rel.endswith(".tsv") else "text"),
                          "\t" if rel.endswith(".tsv") else None, None)
        t, _, _ = pf.record(r.get("out") or r["loc"])
        ok += r["patient"] in t
    pseud = ok / claims if claims else 0.0
    sc = rehearsal["side_channels"]
    hyg_parts = {k: (1.0 if v["hits"] == 0 else 0.0) for k, v in sc.items()}
    tmp_left = sum(len(r["tmp_files"]) + len(r["home_files"]) for r in rehearsal["runs"].values())
    if tmp_left and hyg_parts.get("TMPDIR/HOME") == 1.0:
        hyg_parts["TMPDIR/HOME"] = 0.5
    hygiene = mean(hyg_parts.values())
    # quarantine handling
    either = [(rel, f) for rel, f in truth["files"].items() if f.get("expect") == "either"]
    safe = copies = 0
    for rel, f in either:
        o = rel_out.out_rel(rel, f)
        raw = o is not None and (san / o).is_file() and (san / o).read_bytes() == (inp / rel).read_bytes()
        copies += raw
        safe += not raw
    listed = {e.get("input_sha256") for e in rel_out.report.get("files") or []}
    silent = sum(1 for f in truth["files"].values()
                 if f["sha256"] not in listed and rel_out.out_rel("", f) is None)
    quarantine = 0.5 * safe / max(1, len(either)) + 0.3 * (1 - silent / len(truth["files"])) \
        + 0.2 * (1 - copies / max(1, len(either)))
    # report quality
    rep = rel_out.report
    comp = [rep.get("schema") == "raksha-report/1",
            all(k in (rep.get("counts") or {}) for k in C.COUNT_KEYS),
            isinstance(rep.get("entities"), dict),
            isinstance((rep.get("timing") or {}).get("seconds"), (int, float)),
            isinstance((rep.get("resources") or {}).get("peak_rss_mb"), (int, float)),
            len(listed & {f["sha256"] for f in truth["files"].values()}) == len(
                {f["sha256"] for f in truth["files"].values()})]
    h = rehearsal["report_honesty"]
    hon = [h["claimed"][k] == h["recounted"][k] for k in ("files_total", "files_sanitized", "files_quarantined")]
    report_q = 0.5 * mean(comp) + 0.5 * mean(hon)
    parts = {"format_validity": mean(fmt_ok), "schema_preservation": mean(schema),
             "fhir_validity": mean(fhir_s, 1.0), "pseudonym_consistency": pseud,
             "channel_hygiene": hygiene, "quarantine_handling": quarantine, "report_quality": report_q}
    return {"score": sum(w[k] * parts[k] for k in w), "parts": parts,
            "fhir_problems": dict(fhir_probs), "report_completeness_flags": comp,
            "pseudonym_claims": claims, "either_files": len(either), "raw_copies": copies}


def performance(rehearsal, profile, cfg):
    p = cfg["performance"]["profiles"][profile]
    runs = rehearsal["runs"]
    rel = mean(1.0 if r["exit"] == 0 and r["status"] == "ok" else 0.3 if r["status"] == "ok" else 0.0
               for r in runs.values())
    wall = max(r["wall_s"] for r in runs.values())
    rss = max(r["peak_rss_mb"] for r in runs.values())
    parts = {"reliability": rel, "wall_time": loglin(wall, p["time_good_s"], p["time_limit_s"]),
             "peak_memory": loglin(rss, p["memory_good_mb"], p["memory_limit_mb"]),
             "determinism": rehearsal["determinism"]["share"]}
    ws = {"reliability": 0.3, "wall_time": 0.3, "peak_memory": 0.2, "determinism": 0.2}
    return {"score": sum(ws[k] * parts[k] for k in ws) / sum(ws.values()), "parts": parts,
            "wall_s": wall, "rss_mb": rss, "profile": profile}


# ============================================================== attacker
def skel(w: str) -> str:
    w = C.norm(w)
    for a, b in (("ee", "i"), ("oo", "u"), ("aa", "a"), ("w", "v"), ("ph", "f"), ("sh", "s"),
                 ("th", "t"), ("dh", "d"), ("bh", "b"), ("kh", "k"), ("gh", "g"), ("z", "j"),
                 ("y", "i")):
        w = w.replace(a, b)
    w = re.sub(r"(.)\1+", r"\1", w)
    return w[:-1] if len(w) > 3 and w.endswith("a") else w


try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from wards.linkage import _transliterate_deva_word as _deva  # read-only use
except Exception:  # pragma: no cover
    _deva = None

_DEVA = re.compile(r"[ऀ-ॿ]+")


def words_of(text):
    ws = []
    for w in C._WORD.findall(C.norm(text)):
        if _DEVA.fullmatch(w) and _deva:
            try:
                w = _deva(w) or w
            except Exception:
                pass
        ws.append(skel(w))
    return ws


class Attacker:
    def __init__(self, reg_rows, ref_date):
        self.reg = reg_rows
        self.ref = date.fromisoformat(ref_date)
        self.dist = {skel(r["district"]) for r in reg_rows}
        self.teh = {skel(r["tehsil"]) for r in reg_rows}
        self.vil = {skel(r["village"]) for r in reg_rows}
        self.pins = {r["pin"] for r in reg_rows}
        for r in reg_rows:
            r["_n"] = [skel(x) for x in r["name"].split()]
            r["_rel"] = [skel(x) for x in r["relative_name"].split()]
            r["_d"], r["_t"], r["_v"] = skel(r["district"]), skel(r["tehsil"]), skel(r["village"])
            r["_house"] = C.norm(r["house_no"])

    def evidence(self, text, fields=None):
        n = C.nz(text)
        ev = defaultdict(set)
        runs = C.digit_runs(n)
        for r in runs:
            if len(r) == 10 and r[0] in "6789":
                ev["phone"].add(r)
            if len(r) == 6 and r in self.pins:
                ev["pin"].add(r)
        for m in re.finditer(r"\b(\d{3})(?:\*{3}|x{3}|\s?\*+)", n):
            ev["pin3"].add(m.group(1))
        for m in re.finditer(r"[\w.+-]+@[\w-]+\.[\w.]+", n):
            ev["email"].add(m.group(0))
        for m in re.finditer(r"x{4}[\s-]?x{4}[\s-]?(\d{4})", n):
            ev["last4"].add(m.group(1))
        for m in re.finditer(r"\b(\d{2})x{4,6}(\d{2})\b", n):
            ev["mphone"].add((m.group(1), m.group(2)))
        for m in re.finditer(r"(?:age|umar|आयु|उम्र)\s*[:\-]?\s*(\d{1,3})\b|\b(\d{1,3})\s*(?:/\s*[mf]\b|yrs?\b|years?\b|y\b|वर्ष|साल)", n):
            a = int(m.group(1) or m.group(2))
            if 0 < a < 120:
                ev["age"].add((a, a))
        for m in re.finditer(r"\b(\d{1,3})\s*-\s*(\d{1,3})\s*(?:yrs?|/\s*[mf]\b|y\b)?", n):
            lo, hi = int(m.group(1)), int(m.group(2))
            if 0 <= lo < hi <= 125 and hi - lo <= 20 and (fields is None or "age" in n[max(0, m.start() - 30):m.start()] or re.search(r"(yrs?|/\s*[mf])", m.group(0))):
                ev["age"].add((lo, hi))
        for m in re.finditer(r"\b(\d{2,3})\s*\+", n):
            ev["age"].add((int(m.group(1)), 125))
        if fields:
            for k, v in fields.items():
                kn = C.norm(str(k))
                if re.search(r"age|umar|उम्र|आयु", kn) and v is not None:
                    vs = C.norm(str(v))
                    m = re.match(r"\s*(\d{1,3})\s*-\s*(\d{1,3})", vs) or re.match(r"\s*(\d{1,3})\s*\+", vs) \
                        or re.match(r"\s*(\d{1,3})\b", vs)
                    if m:
                        lo = int(m.group(1))
                        hi = int(m.group(2)) if m.lastindex and m.lastindex >= 2 else (125 if "+" in vs else lo)
                        ev["age"].add((lo, hi))
                if re.search(r"gender|sex|ling|लिंग", kn) and v:
                    g = C.norm(str(v))[:1]
                    if g in ("m", "f"):
                        ev["gender"].add(g.upper())
                if re.search(r"dob|birth|janm|जन्म", kn) and v:
                    ds = C.parse_dates(C.norm(str(v))) or re.findall(r"\b(19\d\d|20\d\d)\b", str(v))
                    if ds:
                        ev["byear"].add(int(str(ds[0])[:4]))
        for m in re.finditer(r"(?:dob|d\.o\.b|जन्म तिथि|janm tithi)\s*[:\-]?\s*([\w/.\- ]{6,12})", n):
            ds = C.parse_dates(m.group(1))
            if ds:
                ev["byear"].add(int(ds[0][:4]))
        if re.search(r"\b(?:male|पुरुष|s/o|sahab)\b|/\s*m\b", n):
            ev["gender"].add("M")
        if re.search(r"\b(?:female|महिला|w/o|d/o|behenji)\b|/\s*f\b", n):
            ev["gender"].add("F")
        ws = words_of(text)
        wset = set(ws)
        for w in wset:
            if w in self.dist:
                ev["district"].add(w)
            if w in self.teh:
                ev["tehsil"].add(w)
            if w in self.vil:
                ev["village"].add(w)
        bigr = {a + " " + b for a, b in zip(ws, ws[1:])}
        for name_set, key in ((self.dist, "district"), (self.teh, "tehsil"), (self.vil, "village")):
            for x in name_set:
                if " " in x and x in bigr:
                    ev[key].add(x)
        # names: drop tokens right after "dr"
        drop = {ws[i + 1] for i, w in enumerate(ws[:-1]) if w in ("dr", "doctor")}
        ev["words"] = wset - drop
        ev["text"] = {n}
        ev["dates"] = set(C.parse_dates(n))
        return ev

    def attack(self, ev):
        cands = list(self.reg)

        def filt(pred):
            nonlocal cands
            new = [r for r in cands if pred(r)]
            if new:
                cands = new
        if ev.get("phone"):
            filt(lambda r: r["phone"] in ev["phone"])
        if ev.get("email"):
            filt(lambda r: r["email"] and C.norm(r["email"]) in ev["email"])
        if ev.get("last4"):
            filt(lambda r: r["aadhaar_last4"] in ev["last4"])
        if ev.get("mphone"):
            filt(lambda r: any(r["phone"][:2] == a and r["phone"][-2:] == b for a, b in ev["mphone"]))
        if ev.get("district"):
            filt(lambda r: r["_d"] in ev["district"])
        if len(ev.get("gender", ())) == 1:
            filt(lambda r: r["gender"] in ev["gender"])
        if ev.get("age"):
            filt(lambda r: any(lo - 1 <= int(r["age"]) <= hi + 2 for lo, hi in ev["age"]))
        if ev.get("byear"):
            filt(lambda r: any(abs((self.ref.year - int(r["age"])) - y) <= 1 for y in ev["byear"]))
        if ev.get("tehsil"):
            filt(lambda r: r["_t"] in ev["tehsil"])
        if ev.get("village"):
            filt(lambda r: r["_v"] in ev["village"])
        if ev.get("pin"):
            filt(lambda r: r["pin"] in ev["pin"])
        if ev.get("pin3"):
            filt(lambda r: r["pin"][:3] in ev["pin3"])
        words = ev.get("words", set())
        text = next(iter(ev.get("text", {""})))
        ws = {}
        for r in cands:
            wgt = 1.0
            if all(t in words for t in r["_n"]):
                wgt *= 60
            else:
                if r["_n"][0] in words:
                    wgt *= 8
                if r["_n"][-1] in words and len(r["_n"][-1]) > 2:
                    wgt *= 3
            if r["_rel"] and all(t in words for t in r["_rel"]):
                wgt *= 8
            if r["_house"] and re.search(r"(?<![\w/])" + re.escape(r["_house"]) + r"(?![\w/])", text):
                wgt *= 2
            ws[r["rid"]] = wgt
        tot = sum(ws.values())
        return {k: v / tot for k, v in ws.items()}


def pool(evs):
    out = defaultdict(set)
    for e in evs:
        for k, v in e.items():
            out[k] |= v
    if "text" in out:
        out["text"] = {"\n".join(sorted(out["text"]))}
    return out


_REFKEY = re.compile(r"patient_ref|uhid|mrn|patient_id|ipd|reg_no|reference", re.I)


def privacy(truth, units, side, reg_rows, kf, release_tag, rel_out: Release | None, cfg):
    """A2/A3, A4, A5 on one release ('our' or 'raw'). A1/A6/A7 are computed separately."""
    att = Attacker(reg_rows, truth["ref_date"])
    pid_rid = {pid: p["rid"] for pid, p in truth["patients"].items()}
    recs = []
    for it in units.items:
        pid = it["u"].get("patient")
        if not pid or pid not in pid_rid:
            continue
        text = it[side]
        if side == "out" and it["orel"] is None:
            continue
        fields = it[f"{side}_fields"]
        ev = att.evidence(text, fields)
        refs = set()
        for m in re.finditer(r"PSN-[0-9A-Z]{6}", text):
            refs.add(m.group(0))
        for k, v in (fields or {}).items():
            if _REFKEY.search(str(k)) and v and not str(v).startswith("[") and len(str(v)) >= 4:
                refs.add(C.norm(str(v)))
        hosp = {v for k, v in HOSP_FILE.items() if k in it["rel"].lower()}
        for k, v in HOSP.items():
            if v in C.norm(text):
                hosp.add(v)
        recs.append({"pid": pid, "rid": pid_rid[pid], "ev": ev, "refs": refs, "hosp": hosp,
                     "p": att.attack(ev)})
    a23 = mean(r["p"].get(r["rid"], 0.0) for r in recs)
    # A4: profiles through shared refs (union-find)
    parent = list(range(len(recs)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    first = {}
    for i, r in enumerate(recs):
        for ref in r["refs"]:
            if ref in first:
                parent[find(i)] = find(first[ref])
            else:
                first[ref] = i
    groups = defaultdict(list)
    for i in range(len(recs)):
        groups[find(i)].append(i)
    profiles = []
    for g in groups.values():
        ev = pool([recs[i]["ev"] for i in g])
        p = att.attack(ev) if len(g) > 1 else recs[g[0]]["p"]
        for i in g:
            recs[i]["risk"] = max(recs[i]["p"].get(recs[i]["rid"], 0.0), p.get(recs[i]["rid"], 0.0))
        rids = Counter(recs[i]["rid"] for i in g)
        profiles.append({"idx": g, "ev": ev, "p": p, "rid": rids.most_common(1)[0][0],
                         "hosp": set().union(*(recs[i]["hosp"] for i in g))})
    pats = defaultdict(float)
    for r in recs:
        pats[r["pid"]] = max(pats[r["pid"]], r.get("risk", 0.0))
    a4 = mean(1.0 if v >= 0.5 else 0.0 for v in pats.values())
    # A5 targeted, with global-shift recovery
    kf_by = {k["rid"]: k for k in kf}
    offsets = defaultdict(set)
    for pr in profiles:
        if not pr["p"]:
            continue
        top, conf = max(pr["p"].items(), key=lambda x: x[1])
        if conf >= 0.9 and top in kf_by:
            for vd in kf_by[top]["visit_dates"]:
                for d in pr["ev"].get("dates", ()):
                    offsets[(date.fromisoformat(vd) - date.fromisoformat(d)).days].add(top)
    best = max(offsets.items(), key=lambda x: (len(x[1]), x[0] == 0), default=(None, set()))
    glob = best[0] if len(best[1]) >= 2 and best[0] != 0 else None
    cond_count = Counter()
    for k in kf:
        if k.get("condition_hint"):
            c = C.norm(k["condition_hint"])
            cond_count[c] = sum(1 for pr in profiles if c in next(iter(pr["ev"].get("text", {""}))))
    succ, decoy_claims = [], 0
    patient_rids = set(pid_rid.values())
    for k in kf:
        weights = []
        for pr in profiles:
            dates_ = set(pr["ev"].get("dates", ()))
            if glob is not None:
                dates_ = {(date.fromisoformat(d) + __import__("datetime").timedelta(days=glob)).isoformat()
                          for d in dates_}
            txt = next(iter(pr["ev"].get("text", {""})))
            wgt = 0.0
            if any(vd in dates_ for vd in k["visit_dates"]):
                wgt += 1
            if k.get("condition_hint") and C.norm(k["condition_hint"]) in txt:
                wgt += 8 if cond_count[C.norm(k["condition_hint"])] <= 3 else 1
            if k.get("stay_days") is not None:
                ds = sorted(date.fromisoformat(d) for d in pr["ev"].get("dates", ()))
                if any((b - a).days == k["stay_days"] for a, b in itertools.combinations(ds, 2)):
                    wgt += 1
            if wgt == 0:
                continue
            # consistency: this person must survive the profile's evidence filters
            if pr["p"] and k["rid"] not in pr["p"]:
                continue
            if HOSP_FILE.get(next((h for h in HOSP_FILE if h in C.norm(k["hospital"]).replace(" ", "")), ""), "") in pr["hosp"] \
                    or any(h in C.norm(k["hospital"]) for h in pr["hosp"]):
                wgt *= 2
            weights.append((pr["rid"], wgt))
        if k["rid"] not in patient_rids:
            decoy_claims += bool(weights)
            continue
        tot = sum(w for _, w in weights)
        succ.append(sum(w for r, w in weights if r == k["rid"]) / tot if tot else 0.0)
    a5 = mean(succ)
    return {"tag": release_tag, "A2_3": a23, "A4": a4, "A5": a5, "records": len(recs),
            "patients": len(pats), "patients_reid": sum(1 for v in pats.values() if v >= 0.5),
            "profiles": len(profiles), "global_shift": glob, "decoy_claims": decoy_claims,
            "targets": len(succ), "targets_hit": sum(1 for s in succ if s >= 0.5)}


def a1_direct(units, side_hits):
    exposed = set()
    unique_ids, unique_names = set(), set()
    for it in units.items:
        for e, lk in it.get("leaks", []):
            if lk <= 0 or e.get("canary") or e["type"] == "CANARY":
                continue
            pid = e.get("person") or it["u"].get("patient")
            if e.get("match") == "name":
                _, ls = leak_of_mention(it, e)
                if e.get("full") and ls and all(x > 0 for x in ls):
                    exposed.add(pid)
                    unique_names.add(tuple(k for k, _ in entity_keys(e)))
            elif e.get("critical"):
                exposed.add(pid)
                unique_ids.add((e["type"], entity_keys(e)[0][0]))
    return exposed, unique_ids, unique_names


def a6_inversion(truth, units, rel_out):
    orig = defaultdict(set)
    for pid, p in truth["patients"].items():
        for lst in (p.get("uhids") or {}).values():
            for x in lst:
                orig[pid].add(str(x))
    for it in units.items:
        for e in it["u"]["entities"]:
            pid = e.get("person")
            if pid not in truth["patients"]:
                continue
            if e["type"] in ("AADHAAR", "PHONE", "ABHA_NUMBER", "MRN"):
                orig[pid].add(str(e.get("key") or e["surface"]))
            if e["type"] == "PATIENT_NAME" and e.get("full") and e["script"] == "latin":
                orig[pid].add(e["surface"])
    psn_of = defaultdict(set)
    for it in units.items:
        pid = it["u"].get("patient")
        if pid and it["orel"]:
            y = rel_out.pseudonym(it["orel"], it["loc"])
            if y:
                psn_of[pid].add(y)
    inv = 0
    for pid, ys in psn_of.items():
        trans = set()
        digits = set()
        for o in orig[pid]:
            base = [o, o.lower(), o.upper(), re.sub(r"\D", "", o), o[::-1]]
            if re.sub(r"\D", "", o):
                digits.add(re.sub(r"\D", "", o))
            for b in base:
                if not b:
                    continue
                trans.add(b.lower())
                bb = b.encode()
                for h in (hashlib.md5, hashlib.sha1, hashlib.sha256, hashlib.sha512):
                    trans.add(h(bb).hexdigest())
                trans.add(base64.b64encode(bb).decode().lower())
        hit = False
        for y in ys:
            for cand in (y.lower(), y.lower().replace("psn-", "")):
                if cand in trans or (len(cand) >= 8 and any(t.startswith(cand) for t in trans)):
                    hit = True
                if any(len(d) >= 4 and d in re.sub(r"\D", "", cand) for d in digits):
                    hit = True
        inv += hit
    return inv / len(psn_of) if psn_of else 0.0, len(psn_of)


def a7_cross(truth, units_a, rel_a, rel_b, work):
    pa, pb = defaultdict(set), defaultdict(set)
    for it in units_a.items:
        pid = it["u"].get("patient")
        if pid and it["orel"]:
            ya, yb = rel_a.pseudonym(it["orel"], it["loc"]), rel_b.pseudonym(it["orel"], it["loc"])
            if ya:
                pa[pid].add(ya)
            if yb:
                pb[pid].add(yb)
    common = [p for p in pa if p in pb]
    stable_psn = mean((1.0 if pa[p] & pb[p] else 0.0) for p in common) if common else 0.0
    shifted = same = 0
    for it in units_a.items:
        if not it["u"].get("dates") or it["orel"] is None:
            continue
        pb_ = rel_b.parsed(it["rel"], it["f"])
        if pb_ is None:
            continue
        tb, _, _ = pb_.record(rel_b.recs_out.get(it["orel"], {}).get(it["loc"], it["loc"]))
        din = C.DATE_TOKEN.findall(it["in"])
        da, db = C.DATE_TOKEN.findall(it["out"]), C.DATE_TOKEN.findall(tb)
        if len(din) == len(da) == len(db):
            for x, y, z in zip(din, da, db):
                if x != y:
                    shifted += 1
                    same += y == z
    stable_dates = same / shifted if shifted else 0.0
    return max(stable_psn, stable_dates), stable_psn, stable_dates, len(common), shifted


# ============================================================== main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", default=r"..\Secret-Wards-ToolKit")
    ap.add_argument("--work", required=True)
    ap.add_argument("--input", default=None)
    ap.add_argument("--truth", default=None)
    ap.add_argument("--attacker", default=None)
    ap.add_argument("--json", default=None, help="write the full result here")
    a = ap.parse_args()
    kit, work = Path(a.kit).resolve(), Path(a.work).resolve()
    inp = Path(a.input).resolve() if a.input else kit / "dev" / "input"
    truth = json.loads(Path(a.truth).read_text(encoding="utf-8")) if a.truth else C.load_truth(kit)
    att_dir = Path(a.attacker) if a.attacker else kit / "dev" / "attacker"
    cfg = tomllib.loads((kit / "scoring.toml").read_text(encoding="utf-8"))
    rehearsal = json.loads((work / "rehearsal.json").read_text(encoding="utf-8"))
    reg_rows = list(csv.DictReader((att_dir / "registry.csv").open(encoding="utf-8")))
    reg = {r["rid"]: r for r in reg_rows}
    kf = [json.loads(x) for x in (att_dir / "known_facts.jsonl").read_text(encoding="utf-8").splitlines() if x]

    raw = Release(truth, inp, None)
    ours = Release(truth, inp, work / "out_A1")
    ours_b = Release(truth, inp, work / "out_B")
    units = Units(truth, raw, ours)
    units.truth_traps = truth["traps"]

    det = detection(units, cfg)
    uti = utility(units, reg, truth, cfg)
    ide = identity(units, ours)
    integ = integrity(truth, inp, work / "out_A1", ours, rehearsal, units, cfg)
    prof = json.loads((kit / "dev" / "dataset_manifest.json").read_text(encoding="utf-8"))["profile"]
    perf = performance(rehearsal, prof, cfg)
    perf_std = performance(rehearsal, "standard", cfg)

    # privacy
    side_hits = sum(v["hits"] for v in rehearsal["side_channels"].values())
    exposed, uniq_ids, uniq_names = a1_direct(units, side_hits)
    n_pat = len({it["u"]["patient"] for it in units.items if it["u"].get("patient") in truth["patients"]})
    a1 = len(exposed) / n_pat if n_pat else 0.0
    p_our = privacy(truth, units, "out", reg_rows, kf, "ours", ours, cfg)
    p_raw = privacy(truth, units, "in", reg_rows, kf, "raw", None, cfg)
    a6, n_psn = a6_inversion(truth, units, ours)
    a7, st_psn, st_dates, n_common, n_shift = a7_cross(truth, units, ours, ours_b, work)
    pw = cfg["privacy"]["weights"]

    def ratio(x, y):
        return min(1.0, x / y) if y else 0.0
    risks = {"direct_exposure": a1, "record_linkage": ratio(p_our["A2_3"], p_raw["A2_3"]),
             "profile_reidentification": ratio(p_our["A4"], p_raw["A4"]),
             "targeted_attack": ratio(p_our["A5"], p_raw["A5"]),
             "pseudonym_inversion": a6, "cross_release": a7}
    risk = sum(pw[k] * risks[k] for k in risks) / sum(pw[k] for k in risks)
    coupling = min(1.0, uti["score"] / cfg["privacy"]["utility_coupling_threshold"])
    priv_score = (1 - risk) * coupling

    # penalties
    pc = cfg["penalties"]
    scan = C.SideChannelScanner(truth)
    out = work / "out_A1"
    everything = []
    for p in out.rglob("*"):
        if p.is_file() and p.relative_to(out).parts[0] != "quarantine":
            everything.append(p.relative_to(out).as_posix())
            everything.append(C.read_any(p))
    for n in ("stdout_A1.txt", "stderr_A1.txt"):
        everything.append(C.read_any(work / n))
    allt = "\n".join(everything)
    can_ids = set()
    an = C.nz(allt)
    words = set(C._WORD.findall(an))
    runs = C.digit_runs(an)
    for f in truth["files"].values():
        for u in f["units"].values():
            for e in u["entities"]:
                if not (e.get("canary") or e["type"] == "CANARY"):
                    continue
                ks = entity_keys(e)
                if e.get("match") == "name":
                    hit = ks and all(k in words for k, _ in ks)
                elif e["match"].startswith("digits"):
                    hit = any(ks[0][0] in r for r in runs)
                else:
                    hit = ks[0][0] in an
                if hit:
                    can_ids.add(e["person"])
    n_leak = len(uniq_ids) + len(uniq_names)
    pen = {"leaked_identifiers": min(pc["leaked_identifier_cap"], n_leak * pc["per_leaked_identifier"]),
           "canaries": min(pc["canary_cap"], len(can_ids) * pc["per_canary_leak"]),
           "raw_copies": min(pc["unprocessed_cap"], integ["raw_copies"] * pc["per_unprocessed_export"]),
           "false_success": pc["false_success"] if any(r["exit"] == 0 for r in rehearsal["runs"].values())
           and not (out / "report.json").exists() else 0,
           "input_tampering": pc["input_tampering"] if rehearsal["checks"]["input_unchanged"] != "PASS" else 0}
    W = cfg["weights"]
    cats = {"detection": det["score"], "utility": uti["score"], "identity_resolution": ide["score"],
            "integrity": integ["score"], "performance": perf["score"], "privacy": priv_score}
    pts = {k: 100 * W[k] * v for k, v in cats.items()}
    total = sum(pts.values()) - sum(pen.values())

    res = {"categories": cats, "points": pts, "penalties": pen, "total": total,
           "detection": det, "utility": uti, "identity": ide, "integrity": integ,
           "performance": perf, "performance_standard_profile": perf_std,
           "privacy": {"risks": risks, "risk": risk, "coupling": coupling, "ours": p_our, "raw": p_raw,
                       "A1_patients_exposed": len(exposed), "patients": n_pat,
                       "A6_pseudonymised_patients": n_psn, "A7_stable_psn": st_psn,
                       "A7_stable_dates": st_dates, "A7_patients_compared": n_common,
                       "A7_shifted_dates": n_shift},
           "leaks": {"unique_direct_ids": len(uniq_ids), "unique_full_names": len(uniq_names),
                     "unique_ids_by_type": dict(Counter(t for t, _ in uniq_ids)),
                     "canary_identities_found": len(can_ids), "canary_identities": len(truth["canaries"])},
           "assumptions": ASSUMPTIONS}
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")

    f3 = lambda x: f"{x:.3f}"  # noqa: E731
    print("SECRET WARDS SCORE **ESTIMATE** (not the official evaluator)")
    print(f"profile {prof}: perf uses {prof}; standard-profile perf would be {perf_std['score']:.3f}")
    print("\nDETECTION  recall", f3(det["recall"]), "(type", f3(det["macro_type"]), "script", f3(det["macro_script"]),
          ") precision", f3(det["precision"]), "F2", f3(det["score"]))
    print("  per-type recall:", {k: round(v, 3) for k, v in sorted(det["type_recall"].items())})
    print("  per-script recall:", {k: round(v, 3) for k, v in det["script_recall"].items()})
    print("  precision groups:", {k: round(v, 3) for k, v in det["precision_groups"].items()})
    print("  mentions with any leak:", det["mentions_leaked"])
    print("UTILITY", f3(uti["score"]), {k: round(v, 3) for k, v in uti["parts"].items()})
    print("  intervals", f3(uti["interval"]), "over", uti["date_pairs"], "pairs; LOS", f3(uti["los"]),
          "; generalisation by kind", {k: round(v, 3) for k, v in uti["gen_by_kind"].items()},
          "; untruthful bands", uti["untruthful_bands"])
    print("  statistics", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in uti["stats"].items()})
    print("IDENTITY", f3(ide["score"]), {k: (round(v, 3) if isinstance(v, float) else v) for k, v in ide.items() if k != "score"})
    print("INTEGRITY", f3(integ["score"]), {k: round(v, 3) for k, v in integ["parts"].items()},
          "fhir problems", integ["fhir_problems"])
    print("PERFORMANCE", f3(perf["score"]), {k: round(v, 3) for k, v in perf["parts"].items()},
          f"(wall {perf['wall_s']} s, rss {perf['rss_mb']} MB)")
    print("PRIVACY", f3(priv_score), "risk", f3(risk), "coupling", f3(coupling))
    print("  risks:", {k: round(v, 3) for k, v in risks.items()})
    for p in (p_our, p_raw):
        print(f"  [{p['tag']}] A2/3 mean p(true) {p['A2_3']:.3f}; A4 {p['patients_reid']}/{p['patients']} patients "
              f"re-identified (>=0.5); A5 {p['targets_hit']}/{p['targets']} targets hit, mean {p['A5']:.3f}; "
              f"global shift recovered {p['global_shift']}; decoy claims {p['decoy_claims']}")
    print(f"  A1 patients exposed {len(exposed)}/{n_pat}; A6 inverted {a6:.3f} of {n_psn}; "
          f"A7 stable psn {st_psn:.3f} ({n_common} patients), stable shifted dates {st_dates:.3f} ({n_shift})")
    print("PENALTIES", pen, "| unique leaked ids", len(uniq_ids), dict(Counter(t for t, _ in uniq_ids)),
          "full names", len(uniq_names), "canaries", f"{len(can_ids)}/{len(truth['canaries'])}")
    print("\ncategory | max | estimate (points)")
    for k in ("privacy", "detection", "utility", "identity_resolution", "integrity", "performance"):
        print(f"  {k:<20} {100 * W[k]:>4.0f}  {pts[k]:6.2f}   (score {cats[k]:.3f})")
    print(f"  penalties            -    {-sum(pen.values()):6.2f}")
    print(f"  TOTAL ESTIMATE           {total:6.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
