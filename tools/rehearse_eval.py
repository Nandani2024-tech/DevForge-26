#!/usr/bin/env python3
"""Rehearse the organisers' evaluator on Windows (measurement only, not in the run path).

Follows Secret-Wards-ToolKit docs/SPEC.md + docs/SANDBOX.md as closely as Windows allows:
  * fresh `git clone` of origin/main into a temp folder (never the working tree)
  * private .venv, then the raksha.toml `setup` command (timed, 30 min limit)
  * read-only copy of dev/input, empty output, fresh empty TMP/TEMP/TMPDIR/HOME/USERPROFILE
  * SPEC env vars; the raksha.toml `run` command 3x: secret A, secret A, secret B
  * 50 ms process-tree RSS sampler (psutil), wall time, exit codes
  * determinism, A-vs-B unlinkability, input hashes, secret scan, temp leftovers,
    truth-surface/canary scan of every side channel (counts + file:line only),
    validate_output.py, report.json honesty (recount)

Linux-only isolation (network namespace, tmpfs masks, CPU affinity, /proc hiding) is
NOT reproduced; those checks are reported as NOT TESTABLE HERE.

Usage (repo root):  python tools/rehearse_eval.py --kit ..\\Secret-Wards-ToolKit --work <dir>
Writes <work>/rehearsal.json and prints a PASS/FAIL table.  Prints no PII values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sw_common as C  # noqa: E402


def sh(cmd, cwd=None, env=None, timeout=None):
    p = subprocess.run(cmd, cwd=cwd, env=env, shell=isinstance(cmd, str), capture_output=True,
                       timeout=timeout)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def run_sampled(cmd: str, cwd: Path, env: dict, timeout: float, interval=0.05):
    """Start cmd through the shell; sample whole-tree RSS every 50 ms like the judges' watchdog."""
    t0 = time.perf_counter()
    proc = psutil.Popen(cmd, cwd=str(cwd), env=env, shell=True,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    peak = [0]
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            try:
                tot = proc.memory_info().rss
                for ch in proc.children(recursive=True):
                    try:
                        tot += ch.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                peak[0] = max(peak[0], tot)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            stop.wait(interval)

    th = threading.Thread(target=sample, daemon=True)
    th.start()
    status = "ok"
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        for ch in proc.children(recursive=True):
            ch.kill()
        proc.kill()
        out, err = proc.communicate()
        status = "timeout"
    stop.set()
    th.join(1)
    wall = time.perf_counter() - t0
    return {"exit": proc.returncode, "status": status, "wall_s": round(wall, 2),
            "peak_rss_mb": round(peak[0] / 1024 / 1024, 1)}, out, err


def tree_hashes(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def list_files(root: Path) -> list[str]:
    return [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()] if root.exists() else []


def make_readonly(root: Path):
    for p in root.rglob("*"):
        if p.is_file():
            os.chmod(p, stat.S_IREAD)


def make_writable(root: Path):
    for p in root.rglob("*"):
        try:
            os.chmod(p, stat.S_IREAD | stat.S_IWRITE)
        except OSError:
            pass


def quote(p: Path) -> str:
    # The evaluator shell-quotes paths. On Windows cmd.exe double quotes are the shell quoting.
    return f'"{p}"'


def base_env(venv_scripts: Path, tmp: Path, home: Path) -> dict:
    """Only what SPEC passes, plus the minimum Windows needs to start a process."""
    keep = ["SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "WINDIR", "NUMBER_OF_PROCESSORS",
            "PROCESSOR_ARCHITECTURE"]
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PATH"] = str(venv_scripts) + os.pathsep + os.environ.get("PATH", "")
    for k in ("TMP", "TEMP", "TMPDIR"):
        env[k] = str(tmp)
    env["HOME"] = env["USERPROFILE"] = str(home)
    env["RAKSHA_CPUS"] = "2"
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[k] = "2"
    env["HF_HUB_OFFLINE"] = env["TRANSFORMERS_OFFLINE"] = "1"
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", default=r"..\Secret-Wards-ToolKit")
    ap.add_argument("--work", required=True, help="empty scratch folder (created)")
    ap.add_argument("--repo-url", default=None, help="default: git remote get-url origin")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--input", default=None, help="default: <kit>/dev/input")
    ap.add_argument("--truth", default=None, help="default: <kit>/dev/truth/truth.json")
    a = ap.parse_args()
    kit = Path(a.kit).resolve()
    work = Path(a.work).resolve()
    if work.exists():
        make_writable(work)
        shutil.rmtree(work)
    work.mkdir(parents=True)
    res: dict = {"checks": {}}
    chk = res["checks"]

    url = a.repo_url or sh(["git", "remote", "get-url", "origin"])[1].strip()
    repo = work / "repo"
    rc, _, err = sh(["git", "clone", "--quiet", "--depth", "1", "--branch", a.branch, url, str(repo)])
    if rc:
        print("clone failed:", err.strip()[:300])
        return 2
    res["clone_head"] = sh(["git", "-C", str(repo), "rev-parse", "HEAD"])[1].strip()
    toml = tomllib.loads((repo / "raksha.toml").read_text(encoding="utf-8"))["submission"]
    res["raksha_toml"] = toml

    # ---- setup: private venv first, then the setup command, network allowed -------------
    t0 = time.perf_counter()
    rc1, _, e1 = sh([sys.executable, "-m", "venv", str(repo / ".venv")])
    venv_scripts = repo / ".venv" / "Scripts"
    senv = dict(os.environ)
    senv["PATH"] = str(venv_scripts) + os.pathsep + senv.get("PATH", "")
    senv.pop("PYTHONHOME", None)
    rc2, so, se = sh(toml.get("setup") or "pip install -r requirements.txt", cwd=repo, env=senv,
                     timeout=1800)
    setup_s = time.perf_counter() - t0
    frz = sh([str(venv_scripts / "python.exe"), "-m", "pip", "freeze"], cwd=repo)[1].split()
    res["setup"] = {"exit": rc2, "seconds": round(setup_s, 1), "venv_exit": rc1, "freeze": frz}
    chk["setup_exit0_under_30min"] = "PASS" if rc1 == 0 and rc2 == 0 and setup_s < 1800 else "FAIL"

    # ---- read-only input copy --------------------------------------------------------------
    inp = work / "input"
    shutil.copytree(Path(a.input).resolve() if a.input else kit / "dev" / "input", inp)
    make_readonly(inp)
    h_before = tree_hashes(inp)
    truth = (json.loads(Path(a.truth).read_text(encoding="utf-8")) if a.truth else C.load_truth(kit))
    truth_hash_ok = all(h_before.get(rel) == f["sha256"] for rel, f in truth["files"].items())
    chk["input_copy_matches_truth_sha"] = "PASS" if truth_hash_ok and len(h_before) == 200 else "FAIL"

    secrets_ = {"A": "rehearsal-A-" + secrets.token_hex(12), "B": "rehearsal-B-" + secrets.token_hex(12)}
    runs = {}
    for name, sec in (("A1", "A"), ("A2", "A"), ("B", "B")):
        out, tmp, home = work / f"out_{name}", work / f"tmp_{name}", work / f"home_{name}"
        for d in (out, tmp, home):
            d.mkdir()
        env = base_env(venv_scripts, tmp, home)
        env["RAKSHA_SECRET"] = secrets_[sec]
        env["RAKSHA_INPUT"], env["RAKSHA_OUTPUT"] = str(inp), str(out)
        for k, v in (toml.get("env") or {}).items():
            env[k] = str(v)
        cmd = toml["run"].replace("{input}", quote(inp)).replace("{output}", quote(out))
        info, so, se = run_sampled(cmd, repo, env, timeout=900)
        (work / f"stdout_{name}.txt").write_bytes(so)
        (work / f"stderr_{name}.txt").write_bytes(se)
        info["tmp_files"] = list_files(tmp)
        info["home_files"] = list_files(home)
        info["stdout_lines"] = so.decode("utf-8", "replace").strip().splitlines()[-3:]
        info["stderr_bytes"] = len(se)
        runs[name] = info
    res["runs"] = runs
    res["secrets_prefixes"] = {k: v[:11] + "…" for k, v in secrets_.items()}

    h_after = tree_hashes(inp)
    chk["input_unchanged"] = "PASS" if h_after == h_before else "FAIL"
    chk["exit_codes_0"] = "PASS" if all(r["exit"] == 0 for r in runs.values()) else "FAIL"

    # ---- determinism A1 vs A2 -------------------------------------------------------------
    hA1 = tree_hashes(work / "out_A1" / "sanitized")
    hA2 = tree_hashes(work / "out_A2" / "sanitized")
    rA1 = hashlib.sha256((work / "out_A1" / "records.jsonl").read_bytes()).hexdigest()
    rA2 = hashlib.sha256((work / "out_A2" / "records.jsonl").read_bytes()).hexdigest()
    same = sum(1 for k in hA1 if hA2.get(k) == hA1[k])
    res["determinism"] = {"sanitized_files": len(hA1), "identical": same,
                          "only_in_one": len(set(hA1) ^ set(hA2)), "records_identical": rA1 == rA2,
                          "share": round((same + (rA1 == rA2)) / (len(hA1) + 1), 4)}
    chk["determinism_A_vs_A"] = "PASS" if same == len(hA1) == len(hA2) and rA1 == rA2 else "FAIL"

    # ---- unlinkability A vs B -------------------------------------------------------------
    def recs(p):
        return {(r["file"], r["loc"]): r.get("patient") for r in map(json.loads,
                (p / "records.jsonl").read_text(encoding="utf-8").splitlines()) if r}
    ra, rb = recs(work / "out_A1"), recs(work / "out_B")
    common = [k for k in ra if k in rb and ra[k] and rb[k]]
    same_psn = sum(1 for k in common if ra[k] == rb[k])
    examples = [{"file": k[0], "loc": k[1], "A": ra[k], "B": rb[k]} for k in common[:3]]
    # dates: align date tokens file by file
    dA = dB = dsame = 0
    pair = None
    hB = tree_hashes(work / "out_B" / "sanitized")
    for rel in hA1:
        if rel not in hB:
            continue
        ta = C.decode_bytes((work / "out_A1" / "sanitized" / rel).read_bytes())
        tb = C.decode_bytes((work / "out_B" / "sanitized" / rel).read_bytes())
        da, db = C.DATE_TOKEN.findall(ta), C.DATE_TOKEN.findall(tb)
        if len(da) != len(db):
            continue
        for x, y in zip(da, db):
            dA += 1
            if x == y:
                dsame += 1
            elif pair is None and rel.startswith(("opd/", "lab/")):
                pair = {"file": rel, "A": x, "B": y}
    res["unlinkability"] = {"records_compared": len(common), "same_pseudonym": same_psn,
                            "date_tokens_compared": dA, "date_tokens_equal": dsame,
                            "examples": examples, "date_pair": pair}
    chk["different_secret_changes_psn"] = "PASS" if common and same_psn == 0 else "FAIL"
    chk["different_secret_changes_dates"] = "PASS" if dA and dsame / dA < 0.2 else "FAIL"

    # ---- secret never written -------------------------------------------------------------
    hits = []
    for name, sec in (("A1", "A"), ("A2", "A"), ("B", "B")):
        needles = [secrets_[sec].encode(), secrets_[sec].encode("utf-16-le")]
        roots = [work / f"out_{name}", work / f"tmp_{name}", work / f"home_{name}"]
        files = [p for r in roots for p in r.rglob("*") if p.is_file()]
        files += [work / f"stdout_{name}.txt", work / f"stderr_{name}.txt"]
        for p in files:
            b = p.read_bytes()
            if any(n in b for n in needles) or secrets_[sec] in p.name:
                hits.append(str(p.relative_to(work)))
    res["secret_hits"] = hits
    chk["secret_never_written"] = "PASS" if not hits else "FAIL"

    # ---- temp/home leftovers --------------------------------------------------------------
    left = {n: len(r["tmp_files"]) + len(r["home_files"]) for n, r in runs.items()}
    chk["tmp_home_empty"] = "PASS" if not any(left.values()) else "FAIL"

    # ---- side-channel PII scan (counts + file:line only) ----------------------------------
    scan = C.SideChannelScanner(truth)
    out = work / "out_A1"
    chans = {
        "report.json": [out / "report.json"],
        "records.jsonl": [out / "records.jsonl"],
        "logs/": [p for p in (out / "logs").rglob("*") if p.is_file()] if (out / "logs").exists() else [],
        "other_output_files": [p for p in out.rglob("*") if p.is_file()
                               and p.relative_to(out).parts[0] not in ("sanitized", "quarantine", "logs")
                               and p.name not in ("report.json", "records.jsonl")],
        "stdout/stderr": [work / "stdout_A1.txt", work / "stderr_A1.txt"],
        "TMPDIR/HOME": [p for d in (work / "tmp_A1", work / "home_A1") for p in d.rglob("*") if p.is_file()],
    }
    sc = {}
    for ch, files in chans.items():
        hits = []
        for p in files:
            hits += scan.scan_text(C.read_any(p), str(p.relative_to(work)))
        sc[ch] = {"files": len(files), "hits": len(hits), "where": sorted({h for h in hits})[:10]}
    names = "\n".join(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()
                      and p.relative_to(out).parts[0] != "quarantine")
    fn_hits = scan.scan_text(names, "output file names")
    sc["output_file_names"] = {"files": names.count("\n") + 1, "hits": len(fn_hits),
                               "where": sorted(set(fn_hits))[:10]}
    res["side_channels"] = sc
    for ch, v in sc.items():
        chk[f"pii_free:{ch}"] = "PASS" if v["hits"] == 0 else "FAIL"

    # ---- validate_output.py ---------------------------------------------------------------
    rc, vo, ve = sh([sys.executable, str(kit / "validate_output.py"), "--input", str(inp),
                     "--output", str(out)])
    res["validate_output"] = {"exit": rc, "lines": vo.strip().splitlines()[-6:]}
    chk["validate_output_CONTRACT_OK"] = "PASS" if "CONTRACT OK" in vo else "FAIL"

    # ---- report.json honesty --------------------------------------------------------------
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    real_san = len(list_files(out / "sanitized"))
    recl = [json.loads(x) for x in (out / "records.jsonl").read_text(encoding="utf-8").splitlines() if x]
    statuses = [f.get("status") for f in rep.get("files", [])]
    real = {"files_total": len(h_before), "files_sanitized": real_san,
            "files_quarantined": statuses.count("quarantined"),
            "records_processed": len(recl), "records_linked": sum(1 for r in recl if r.get("patient"))}
    claimed = {k: rep.get("counts", {}).get(k) for k in real}
    res["report_honesty"] = {"claimed": claimed, "recounted": real,
                             "listed_files": len(statuses),
                             "missing_count_keys": [k for k in C.COUNT_KEYS if k not in rep.get("counts", {})],
                             "has_entities": "entities" in rep,
                             "timing": rep.get("timing"), "resources": rep.get("resources")}
    chk["report_counts_honest"] = "PASS" if all(claimed[k] == real[k] for k in real) else "FAIL"

    # ---- limits ---------------------------------------------------------------------------
    worst_wall = max(r["wall_s"] for r in runs.values())
    worst_rss = max(r["peak_rss_mb"] for r in runs.values())
    chk["score_profile_60s_512MB"] = "PASS" if worst_wall <= 60 and worst_rss <= 512 else "FAIL"
    chk["hard_limit_900s_4GB"] = "PASS" if worst_wall <= 900 and worst_rss <= 4096 else "FAIL"

    # ---- network: static scan of the run path ----------------------------------------------
    net = []
    pat = re.compile(r"^\s*(?:import|from)\s+(socket|urllib|http|requests|ftplib|smtplib|ssl|asyncio|"
                     r"xmlrpc|telnetlib|websocket|aiohttp|httpx|urllib3)\b|socket\.|urlopen\(", re.M)
    for p in [repo / "main.py", *sorted((repo / "wards").glob("*.py"))]:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line):
                net.append(f"{p.relative_to(repo).as_posix()}:{i}")
    res["network_scan"] = net
    chk["no_network_code_in_run_path"] = "PASS" if not net else "FAIL"
    for k in ("network_namespace_blocks_connections", "tmpfs_masks_hide_truth",
              "cpu_affinity_2_cores", "proc_hidden"):
        chk[k] = "NOT TESTABLE HERE"

    (work / "rehearsal.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"clone {res['clone_head'][:7]}  setup {res['setup']['seconds']} s exit {rc2}")
    for n, r in runs.items():
        print(f"run {n}: exit {r['exit']} {r['status']} wall {r['wall_s']} s  peak {r['peak_rss_mb']} MB  "
              f"tmp/home files {len(r['tmp_files']) + len(r['home_files'])}  stdout: {r['stdout_lines'][-1:]}")
    print("determinism:", res["determinism"])
    u = res["unlinkability"]
    print(f"A vs B: {u['same_pseudonym']}/{u['records_compared']} same PSN; "
          f"{u['date_tokens_equal']}/{u['date_tokens_compared']} date tokens equal")
    print("side channels:", {k: v["hits"] for k, v in sc.items()})
    print("validate_output:", res["validate_output"]["lines"])
    print("report honesty:", res["report_honesty"]["claimed"], "vs", real)
    print("network scan hits:", net)
    print("-" * 60)
    for k, v in chk.items():
        print(f"{v:<18} {k}")
    ready = all(v != "FAIL" for v in chk.values())
    print("READY TO CONNECT:", "yes" if ready else "no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
