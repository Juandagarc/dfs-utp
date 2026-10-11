"""
End-to-end test of the full lab sequence, run on one machine with 4 processes
(development check only - the real demo uses 4 hosts).

    python tests/test_e2e.py

Covers: upload -> distribution -> replica files physically on disk ->
node failure -> download served by the surviving replica -> repair ->
coordinator failure -> direct download from a node.
"""

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.mkdtemp(prefix="dfs-e2e-"))
COORD = "http://127.0.0.1:8000"
procs: dict[str, subprocess.Popen] = {}


def start(name: str, env: dict, module: str, port: int) -> None:
    e = {**os.environ, **env}
    procs[name] = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", module, "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=e, stdout=open(WORK / f"{name}.log", "w"), stderr=subprocess.STDOUT,
    )


def stop(name: str) -> None:
    procs[name].send_signal(signal.SIGTERM)
    procs[name].wait(5)


def wait_for(url: str, timeout: float = 15) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            httpx.get(url, timeout=1)
            return
        except httpx.HTTPError:
            time.sleep(0.2)
    raise RuntimeError(f"{url} did not start")


def check(cond: bool, msg: str) -> None:
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


def main() -> None:
    os.environ["HOME"] = str(WORK)  # isolate the client's location cache
    for i in (1, 2, 3):
        start(f"node{i}", {"NODE_ID": f"node{i}", "STORAGE_DIR": str(WORK / f"node{i}")}, "node.main:app", 8000 + i)
    start("coordinator", {"DFS_CONFIG": str(ROOT / "config/nodes.local.json"), "DFS_METADATA": str(WORK / "meta.json")},
          "coordinator.main:app", 8000)
    for p in (8001, 8002, 8003, 8000):
        wait_for(f"http://127.0.0.1:{p}/health" if p != 8000 else f"{COORD}/nodes")
    time.sleep(1.5)

    print("1. Nodes reachable")
    nodes = httpx.get(f"{COORD}/nodes").json()
    check(all(n["alive"] for n in nodes.values()), "all 3 nodes UP via heartbeat")

    print("2. Upload & distribution")
    placements = {}
    for i in range(6):
        data = os.urandom(20_000 + i)
        r = httpx.post(f"{COORD}/upload", files={"file": (f"doc{i}.bin", data)}).json()
        placements[r["name"]] = (r["replicas"], hashlib.sha256(data).hexdigest())
        check(len(r["replicas"]) == 2, f"{r['name']} -> {r['replicas']}")
    used = {n for reps, _ in placements.values() for n in reps}
    check(used == {"node1", "node2", "node3"}, f"files spread across all nodes {sorted(used)}")

    print("3. Replicas exist physically on each node's disk")
    for name, (reps, digest) in placements.items():
        for n in reps:
            p = WORK / n / name
            check(p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == digest, f"{p} ok")

    print("3b. Unusual filenames and delete")
    import urllib.parse
    for odd in ("informe final ñ.pdf", "reporte→日本.txt", "a#b?c&d.txt"):
        data = odd.encode() * 50
        httpx.post(f"{COORD}/upload", files={"file": (odd, data)}).raise_for_status()
        r = httpx.get(f"{COORD}/download/{urllib.parse.quote(odd, safe='')}")
        check(r.status_code == 200 and r.content == data, f"round trip '{odd}'")
        r = httpx.delete(f"{COORD}/files/{urllib.parse.quote(odd, safe='')}")
        check(r.status_code == 200 and not any((WORK / n / odd).exists() for n in ("node1", "node2", "node3")),
              f"deleted '{odd}' from every node")

    print("4. Node failure")
    target = "doc0.bin"
    reps, digest = placements[target]
    victim, survivor = reps
    stop(victim)
    time.sleep(2.5)
    check(not httpx.get(f"{COORD}/nodes").json()[victim]["alive"], f"{victim} detected DOWN")
    r = httpx.get(f"{COORD}/download/{target}")
    check(r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == digest, "file still downloadable, integrity OK")
    check(r.headers["X-Served-By"] == survivor, f"served by surviving replica {survivor}")

    print("5. Repair restores replication factor")
    acts = httpx.post(f"{COORD}/repair").json()["actions"]
    check(any(a["file"] == target for a in acts), f"{len(acts)} replica(s) re-created")
    live = httpx.get(f"{COORD}/locate/{target}").json()["live_replicas"]
    check(live == 2, f"{target} back to 2 live replicas")

    print("6. Coordinator failure (SPOF analysis)")
    subprocess.run([sys.executable, "client/dfs.py", "-c", COORD, "ls"], cwd=ROOT, check=True, capture_output=True)
    stop("coordinator")
    r = subprocess.run([sys.executable, "client/dfs.py", "-c", COORD, "ls"], cwd=ROOT, capture_output=True, text=True)
    check(r.returncode != 0, "normal client operations fail without coordinator")
    out = WORK / "direct.bin"
    r = subprocess.run([sys.executable, "client/dfs.py", "direct", "doc1.bin", "-o", str(out)], cwd=ROOT, capture_output=True, text=True)
    check(r.returncode == 0 and "integrity : OK" in r.stdout, "nodes still serve data directly (cached locations)")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    try:
        main()
    finally:
        for p in procs.values():
            if p.poll() is None:
                p.kill()
        shutil.rmtree(WORK, ignore_errors=True)
