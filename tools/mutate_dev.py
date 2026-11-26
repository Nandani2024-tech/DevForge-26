#!/usr/bin/env python3
"""Build a mutated copy of the practice data + a matching truth.json (measurement only).

START_HERE.md section 8: "test on data you didn't tune on: rename columns, swap in new names,
change date formats, then run check_dev.py again".

  EXACT    header renames (CSV/TSV) and key renames (plain JSON, never FHIR), using synonyms
           that do not occur in dev/input; truth `col:` paths, JSON-pointer locs/paths and
           `generalizable` entries are renamed the same way.
  EXACT    patient/relative/canary Latin name tokens are replaced, case-preserving, by invented
           names (built from syllables, in no name list) in file contents AND file names; the same
           replacement is applied to every truth string, so truth stays consistent.
           Base64 payloads are left encoded, so base64-channel entities keep their original text.
  APPROX   date formats: in day-first files (not FHIR) dd/mm/yyyy -> dd-Mon-yyyy and
           yyyy-mm-dd -> dd.mm.yyyy; DOB surfaces / preserve texts are rewritten the same way.
           Truth `dates.true` stays ISO, so it still resolves; ambiguous tokens may be missed.
Files the kit marks `expect: either` (malformed/unsupported) and binaries are copied unchanged.

Usage: python tools/mutate_dev.py --kit ..\\Secret-Wards-ToolKit --out <dir>
Writes <dir>/input/ and <dir>/truth/truth.json. Prints counts only.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sw_common as C  # noqa: E402

HEADER_SYN = {
    "Patient Name": "Name of Patient", "patient_name": "pt_full_name", "Mobile": "Contact Number",
    "Mobile No": "Cell No", "Phone": "Tel", "Age": "Age (yrs)", "DOB": "Birth Date",
    "Gender": "M/F", "Sex": "Gender Code", "UHID": "Hospital No", "uhid": "hosp_no",
    "Aadhaar No": "UID Number", "Aadhar": "UID", "ABHA No": "Health ID",
    "Village/Mohalla": "Locality/Village", "District": "Dist", "PIN": "Postal Code",
    "Pin Code": "Postcode", "Relative Name": "Next of Kin", "Guardian": "Attendant",
    "Address": "Residence", "Email": "E-mail ID", "FirstName": "Given", "LastName": "Family",
    "Reg No": "Registration Number", "PatientID": "Pt Id", "ref_doctor": "referring_physician",
    "test": "investigation", "result": "observed_value", "admission_date": "doa",
    "discharge_date": "dod", "Naam": "Rogi ka Naam", "Umar": "Aayu",
}
KEY_SYN = {
    "name": "full_name", "patient_name": "pt_name", "mobile": "contact_no", "phone": "tel",
    "uhid": "hosp_id", "dob": "birth_date", "age": "age_years", "gender": "gndr",
    "sex": "gender_code", "village": "locality_name", "district": "dist", "pin": "postal_code",
    "guardian": "next_of_kin", "aadhar_no": "uid_no", "abha": "health_id", "email": "e_mail",
    "doctor": "physician", "drug": "medicine", "visit_date": "seen_on", "patient_ref": "subject_ref",
}
SYL_A = ["Zor", "Vel", "Kav", "Thir", "Mol", "Dren", "Quil", "Brav", "Sol", "Yar", "Fen", "Gul",
         "Hesh", "Jor", "Lum", "Nev", "Pax", "Rud", "Tov", "Wex"]
SYL_B = ["ani", "oru", "eth", "ilan", "ovar", "esh", "umi", "arix", "eno", "ulai", "imor", "aven",
         "oshi", "erak", "unda", "ilet"]
MONS = [calendar.month_abbr[i] for i in range(1, 13)]


def invented(i: int) -> str:
    a, b = divmod(i, len(SYL_B))
    return SYL_A[a % len(SYL_A)] + SYL_B[b] + ("" if a < len(SYL_A) else SYL_B[(a // len(SYL_A)) % len(SYL_B)])


def case_like(src: str, new: str) -> str:
    if src.isupper():
        return new.upper()
    if src.islower():
        return new.lower()
    return new[0].upper() + new[1:].lower()


class NameSwap:
    def __init__(self, truth):
        toks = set()
        for f in truth["files"].values():
            for u in f["units"].values():
                for e in u["entities"]:
                    if e.get("match") == "name" and e["script"] in ("latin", "hinglish"):
                        for t in e.get("tokens") or []:
                            if re.fullmatch(r"[A-Za-z]{3,}", t):
                                toks.add(t.casefold())
        self.map = {t: invented(i) for i, t in enumerate(sorted(toks))}
        alt = "|".join(sorted((re.escape(t) for t in self.map), key=len, reverse=True))
        self.rx = re.compile(r"(?<![A-Za-z])(" + alt + r")(?![A-Za-z])", re.I) if alt else None
        self.n = 0

    def __call__(self, s: str) -> str:
        if not self.rx or not isinstance(s, str):
            return s

        def rep(m):
            self.n += 1
            return case_like(m.group(0), self.map[m.group(0).casefold()])
        return self.rx.sub(rep, s)


_DMY = re.compile(r"(?<![\d/])(\d{2})/(\d{2})/(\d{4})(?![\d/])")
_ISO = re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d-]|T)")


def redate(s: str) -> tuple[str, int]:
    n = 0

    def a(m):
        nonlocal n
        d, mo, y = m.groups()
        if not 1 <= int(mo) <= 12:
            return m.group(0)
        n += 1
        return f"{d}-{MONS[int(mo) - 1]}-{y}"

    def b(m):
        nonlocal n
        y, mo, d = m.groups()
        if not 1 <= int(mo) <= 12:
            return m.group(0)
        n += 1
        return f"{d}.{mo}.{y}"
    s = _DMY.sub(a, s)
    s = _ISO.sub(b, s)
    return s, n


def rename_ptr(ptr: str, ks: dict) -> str:
    return "/".join(ks.get(p, p) for p in ptr.split("/"))


def rename_keys(obj, ks):
    if isinstance(obj, dict):
        return {ks.get(k, k): rename_keys(v, ks) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rename_keys(v, ks) for v in obj]
    return obj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", default=r"..\Secret-Wards-ToolKit")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    kit, out = Path(a.kit).resolve(), Path(a.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    (out / "truth").mkdir(parents=True)
    src = kit / "dev" / "input"
    truth = C.load_truth(kit)
    swap = NameSwap(truth)
    stats = {"files": 0, "renamed_headers": 0, "renamed_keys": 0, "dates_rewritten": 0,
             "renamed_files": 0, "unchanged_files": 0}
    new_files = {}
    for rel, f in truth["files"].items():
        data = (src / rel).read_bytes()
        new_rel = "/".join(swap(p) for p in rel.split("/"))
        stats["renamed_files"] += new_rel != rel
        fmt = f["format"]
        mutable = f.get("expect") == "sanitize" and fmt in ("csv", "tsv", "json", "fhir", "text")
        hdr_map, key_map, date_ok = {}, {}, False
        if mutable:
            bom = data.startswith(b"\xef\xbb\xbf")
            u16 = data.startswith((b"\xff\xfe", b"\xfe\xff"))
            text = C.decode_bytes(data, f.get("encoding"))
            hdr_pii = bool(f["units"].get("@header", {}).get("entities"))
            if fmt in ("csv", "tsv") and not hdr_pii:
                first, nl, rest = text.partition("\n")
                delim = f.get("delimiter") or ("\t" if fmt == "tsv" else ",")
                cells = first.rstrip("\r").split(delim)
                newc = []
                for c in cells:
                    q = c.strip('"')
                    if q in HEADER_SYN:
                        hdr_map[q] = HEADER_SYN[q]
                        newc.append(c.replace(q, HEADER_SYN[q]))
                    else:
                        newc.append(c)
                text = delim.join(newc) + ("\r" if first.endswith("\r") else "") + nl + rest
                stats["renamed_headers"] += len(hdr_map)
            if fmt == "json":
                try:
                    tree = json.loads(text)
                    keys = {p.rsplit("/", 1)[-1] for p, v in C.flatten(tree) if v == "\x00KEY"}
                    key_map = {k: v for k, v in KEY_SYN.items() if k in keys and v not in keys}
                    if key_map:
                        text = json.dumps(rename_keys(tree, key_map), ensure_ascii="\\u0" in text,
                                          indent=2 if "\n  " in text else None)
                        stats["renamed_keys"] += len(key_map)
                except (ValueError, RecursionError):
                    key_map = {}
            text = swap(text)
            if (f.get("date_hint") or "dmy") == "dmy" and fmt != "fhir":
                text, n = redate(text)
                stats["dates_rewritten"] += n
                date_ok = n > 0
            if u16:
                data = text.encode("utf-16")
            else:
                enc = f.get("encoding") or "utf-8"
                enc = "utf-8" if "utf" in enc else enc
                data = (b"\xef\xbb\xbf" if bom else b"") + text.encode(enc, "replace")
        else:
            stats["unchanged_files"] += 1
        dst = out / "input" / new_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        stats["files"] += 1
        # ---- truth for this file
        f = json.loads(json.dumps(f))
        f["path"] = new_rel
        f["sha256"] = hashlib.sha256(data).hexdigest()
        f["size"] = len(data)

        def path_fix(p):
            if not p:
                return p
            if p.startswith("col:") and p[4:] in hdr_map:
                return "col:" + hdr_map[p[4:]]
            if p.startswith("/") and key_map:
                return rename_ptr(p, key_map)
            return p
        f["generalizable"] = [path_fix(g) for g in f.get("generalizable") or []]
        units = {}
        for loc, u in f["units"].items():
            nloc = rename_ptr(loc, key_map) if loc.startswith("/") and key_map else loc
            u["loc"] = nloc
            for e in u["entities"]:
                if e["channel"] != "base64" and (mutable or e["channel"] == "filename"):
                    e["surface"] = swap(e["surface"])
                    if e.get("tokens"):
                        e["tokens"] = [swap(t) for t in e["tokens"]]
                    if date_ok and e["type"] == "DOB":
                        e["surface"] = redate(e["surface"])[0]
            if mutable:
                for p in u.get("preserve") or []:
                    p["text"] = swap(p["text"])
                    if date_ok:
                        p["text"] = redate(p["text"])[0]
                    p["path"] = path_fix(p.get("path"))
                for d in u.get("dates") or []:
                    d["path"] = path_fix(d.get("path"))
                for x in u.get("fields") or []:
                    x["path"] = path_fix(x.get("path"))
                u["exclude"] = [swap(x) for x in u.get("exclude") or []]
            units[nloc] = u
        f["units"] = units
        new_files[new_rel] = f
    truth["files"] = new_files
    (out / "truth" / "truth.json").write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")
    print("mutated set:", stats, "| invented names:", len(swap.map), "| name replacements:", swap.n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
