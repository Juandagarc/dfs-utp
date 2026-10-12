"""
Storage Node - Distributed File Storage (DFS-UTP)

Each node runs on an independent host. It stores file replicas on its own
local disk (./storage/<NODE_ID>/) and exposes them over HTTP so the
coordinator (or a client, in degraded mode) can read and write them.

Run:
    NODE_ID=node1 uvicorn node.main:app --host 0.0.0.0 --port 8001
"""

import hashlib
import logging
import os
import shutil
import socket
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

NODE_ID = os.getenv("NODE_ID", "node1")
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", f"./storage/{NODE_ID}")).resolve()
def _check_writable(d: Path) -> None:
    probe = d / ".write_test"
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as e:
        raise SystemExit(
            f"\nERROR: cannot write to {d}\n  {e}\n"
            "  Move the project to a folder you own (e.g. your user folder, not C:\\Windows\\System32)\n"
            "  or set STORAGE_DIR to a writable folder.\n"
        )


_check_writable(STORAGE_DIR)
STARTED_AT = time.time()

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [{NODE_ID}] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("node")

app = FastAPI(title=f"DFS Storage Node ({NODE_ID})", version="1.0")


def safe_path(filename: str) -> Path:
    """Resolve a filename inside STORAGE_DIR, rejecting path traversal."""
    name = os.path.basename(filename)
    if not name or name in (".", ".."):
        raise HTTPException(400, "Invalid filename")
    return STORAGE_DIR / name


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@app.get("/health")
def health():
    """Heartbeat endpoint polled by the coordinator."""
    files = [p for p in STORAGE_DIR.iterdir() if p.is_file()]
    usage = shutil.disk_usage(STORAGE_DIR)
    return {
        "node_id": NODE_ID,
        "hostname": socket.gethostname(),
        "status": "up",
        "files": len(files),
        "bytes_stored": sum(p.stat().st_size for p in files),
        "disk_free_bytes": usage.free,
        "storage_dir": str(STORAGE_DIR),
        "uptime_s": round(time.time() - STARTED_AT, 1),
    }


@app.get("/files")
def list_files():
    """List what is physically stored on this host."""
    out = []
    for p in sorted(STORAGE_DIR.iterdir()):
        if p.is_file():
            out.append({"name": p.name, "size": p.stat().st_size, "sha256": sha256_of(p)})
    return {"node_id": NODE_ID, "storage_dir": str(STORAGE_DIR), "files": out}


@app.put("/files/{filename}")
async def store_file(filename: str, request: Request):
    """Store a replica. The raw request body is the file content."""
    path = safe_path(filename)
    tmp = path.with_suffix(path.suffix + ".part")
    h = hashlib.sha256()
    size = 0
    with open(tmp, "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
            h.update(chunk)
            size += len(chunk)
    digest = h.hexdigest()
    expected = request.headers.get("X-SHA256")
    if expected and expected != digest:
        tmp.unlink(missing_ok=True)
        log.warning("REJECTED %s from %s: checksum mismatch", path.name, client_ip(request))
        raise HTTPException(422, "Checksum mismatch")
    os.replace(tmp, path)  # atomic: a reader never sees a half-written file
    log.info("STORED   %s (%d bytes) from %s -> %s", path.name, size, client_ip(request), path)
    return {"node_id": NODE_ID, "name": path.name, "size": size, "sha256": digest, "path": str(path)}


@app.get("/files/{filename}")
def read_file(filename: str, request: Request):
    path = safe_path(filename)
    if not path.is_file():
        log.info("MISS     %s requested by %s", path.name, client_ip(request))
        raise HTTPException(404, f"{path.name} not on {NODE_ID}")
    log.info("SERVED   %s to %s", path.name, client_ip(request))
    return FileResponse(
        path,
        filename=path.name,
        headers={"X-Node-Id": NODE_ID, "X-SHA256": sha256_of(path)},
    )


@app.delete("/files/{filename}")
def delete_file(filename: str, request: Request):
    path = safe_path(filename)
    if not path.is_file():
        raise HTTPException(404, "Not found")
    path.unlink()
    log.info("DELETED  %s by %s", path.name, client_ip(request))
    return {"node_id": NODE_ID, "deleted": path.name}
