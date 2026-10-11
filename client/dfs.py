#!/usr/bin/env python3
"""
DFS-UTP command line client.

The user only talks to the coordinator; it never needs to know which node
holds a file. The `direct` command exists only for the coordinator-failure
analysis: it uses locations cached from earlier calls to reach a node
without the coordinator.

Usage:
    python client/dfs.py --coordinator http://100.64.0.1:8000 upload report.pdf
    python client/dfs.py download report.pdf -o copy.pdf
    python client/dfs.py ls | nodes | locate report.pdf | repair | rm report.pdf
    python client/dfs.py direct report.pdf      # bypass the coordinator
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import httpx

CACHE = Path.home() / ".dfs_cache.json"


def load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except Exception:
        return {}


def save_cache(files: list[dict]) -> None:
    cache = load_cache()
    for f in files:
        if "replica_urls" in f:
            cache[f["name"]] = {"sha256": f["sha256"], "urls": f["replica_urls"]}
    CACHE.write_text(json.dumps(cache, indent=2))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(description="DFS-UTP client")
    p.add_argument("--coordinator", "-c", default=os.getenv("DFS_COORDINATOR", "http://127.0.0.1:8000"))
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("upload"); s.add_argument("path")
    s = sub.add_parser("download"); s.add_argument("name"); s.add_argument("-o", "--out")
    sub.add_parser("ls")
    sub.add_parser("nodes")
    s = sub.add_parser("locate"); s.add_argument("name")
    sub.add_parser("repair")
    s = sub.add_parser("rm"); s.add_argument("name")
    s = sub.add_parser("direct", help="download straight from a node using cached locations"); s.add_argument("name"); s.add_argument("-o", "--out")
    a = p.parse_args()
    base = a.coordinator.rstrip("/")
    c = httpx.Client(timeout=httpx.Timeout(60, connect=3))

    try:
        if a.cmd == "upload":
            path = Path(a.path)
            if not path.is_file():
                die(f"{path} not found")
            with open(path, "rb") as f:
                r = c.post(f"{base}/upload", files={"file": (path.name, f)})
            r.raise_for_status()
            j = r.json()
            print(f"Uploaded {j['name']} ({j['size']} bytes)")
            print(f"  stored on : {', '.join(j['replicas'])}")
            print(f"  sha256    : {j['sha256']}")
            if j["under_replicated"]:
                print("  WARNING   : fewer replicas than the replication factor")
            save_cache([c.get(f"{base}/locate/{quote(j['name'], safe='')}").json()])

        elif a.cmd in ("download", "direct"):
            out = Path(a.out or a.name)
            if a.cmd == "download":
                with c.stream("GET", f"{base}/download/{quote(a.name, safe='')}") as r:
                    if r.status_code != 200:
                        r.read()
                        die(f"HTTP {r.status_code}: {r.text}")
                    with open(out, "wb") as f:
                        for chunk in r.iter_bytes():
                            f.write(chunk)
                    served, failed, expected = r.headers.get("X-Served-By"), r.headers.get("X-Failed-Replicas"), r.headers.get("X-SHA256")
                print(f"Downloaded {a.name} -> {out}")
                print(f"  served by : {served} ({r.headers.get('X-Served-By-Url')})")
                if failed:
                    print(f"  failover  : skipped {failed}")
            else:
                entry = load_cache().get(a.name) or die(f"No cached location for {a.name}; run 'ls' while the coordinator is up")
                expected, served = entry["sha256"], None
                for nid, url in entry["urls"].items():
                    try:
                        r = c.get(url)
                        if r.status_code == 200:
                            out.write_bytes(r.content)
                            served = nid
                            break
                        print(f"  {nid}: HTTP {r.status_code}")
                    except httpx.HTTPError as e:
                        print(f"  {nid}: {type(e).__name__}")
                if not served:
                    die("No replica reachable")
                print(f"Downloaded {a.name} -> {out} DIRECTLY from {served} (coordinator bypassed)")
            ok = sha256_file(out) == expected
            print(f"  integrity : {'OK' if ok else 'MISMATCH'} (sha256)")

        elif a.cmd == "ls":
            files = c.get(f"{base}/files").json()
            if not files:
                print("(no files)")
            for f in files:
                reps = " ".join(f"{n}[{s}]" for n, s in f["replica_status"].items())
                print(f"{f['name']:<30} {f['size']:>10} B   {reps}")
            save_cache([c.get(f"{base}/locate/{quote(f['name'], safe='')}").json() for f in files])

        elif a.cmd == "nodes":
            for nid, n in c.get(f"{base}/nodes").json().items():
                info = n["info"] or {}
                state = "UP  " if n["alive"] else "DOWN"
                print(f"{nid:<8} {state} {n['url']:<28} host={info.get('hostname', '-'):<16} files={info.get('files', '-')}")

        elif a.cmd == "locate":
            r = c.get(f"{base}/locate/{quote(a.name, safe='')}")
            if r.status_code != 200:
                die(r.text)
            j = r.json()
            save_cache([j])
            print(json.dumps({k: j[k] for k in ("name", "size", "sha256", "replica_status", "replica_urls")}, indent=2))

        elif a.cmd == "repair":
            acts = c.post(f"{base}/repair").json()["actions"]
            print("\n".join(f"copied {x['file']}: {x['copied_from']} -> {x['to']}" for x in acts) or "Nothing to repair")

        elif a.cmd == "rm":
            print(c.delete(f"{base}/files/{quote(a.name, safe='')}").json())

    except httpx.ConnectError:
        die(f"Cannot reach coordinator at {base}. If it is down, try: dfs.py direct <name>")


if __name__ == "__main__":
    main()
