"""
Coordinator - Distributed File Storage (DFS-UTP)

Single entry point for users. It hides where files physically live:
  * decides which nodes store each file (hash ring + replication),
  * keeps the metadata index (file -> nodes),
  * monitors node liveness with heartbeats,
  * serves downloads from any live replica (failover),
  * re-replicates under-replicated files on demand (/repair).

Run:
    uvicorn coordinator.main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote as _quote

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.getenv("DFS_CONFIG", BASE_DIR.parent / "config" / "nodes.json"))
METADATA_PATH = Path(os.getenv("DFS_METADATA", BASE_DIR / "metadata.json"))

config = json.loads(CONFIG_PATH.read_text())
NODES: dict[str, str] = {n["id"]: n["url"].rstrip("/") for n in config["nodes"]}
REPLICATION_FACTOR: int = int(config.get("replication_factor", 2))
HEARTBEAT_INTERVAL: float = float(config.get("heartbeat_interval_s", 3))
HEARTBEAT_TIMEOUT: float = float(config.get("heartbeat_timeout_s", 2))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [coordinator] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("coordinator")
logging.getLogger("httpx").setLevel(logging.WARNING)  # hide per-heartbeat request lines

# ---------------------------------------------------------------- state
node_status: dict[str, dict] = {nid: {"alive": False, "last_seen": None, "info": None} for nid in NODES}
events: deque = deque(maxlen=60)
metadata_lock = asyncio.Lock()


def event(msg: str) -> None:
    log.info(msg)
    events.appendleft({"t": time.strftime("%H:%M:%S"), "msg": msg})


def load_metadata() -> dict:
    if METADATA_PATH.exists():
        return json.loads(METADATA_PATH.read_text())
    return {}


def save_metadata() -> None:
    tmp = METADATA_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(metadata, indent=2))
    os.replace(tmp, METADATA_PATH)


metadata: dict[str, dict] = load_metadata()
http: httpx.AsyncClient  # created in lifespan


# ---------------------------------------------------------------- placement
def ring_order(filename: str) -> list[str]:
    """Deterministic order of nodes for a file: hash the name onto a ring
    of the configured nodes and walk clockwise."""
    ids = sorted(NODES)
    start = int(hashlib.sha256(filename.encode()).hexdigest(), 16) % len(ids)
    return ids[start:] + ids[:start]


def quote(name: str) -> str:
    """URL-encode a filename for use as a path segment (spaces, #, ?, accents...)."""
    return _quote(name, safe="")


def content_disposition(name: str) -> str:
    """RFC 6266 header that works for any filename, including non-Latin ones."""
    ascii_name = name.encode("ascii", "replace").decode().replace('"', "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def mark_down(nid: str, reason: str) -> None:
    if node_status[nid]["alive"]:
        event(f"DETECTED {nid} is DOWN ({reason})")
    node_status[nid]["alive"] = False


def alive_nodes() -> list[str]:
    return [nid for nid, s in node_status.items() if s["alive"]]


def choose_targets(filename: str, k: int, exclude: set[str] = frozenset()) -> list[str]:
    return [nid for nid in ring_order(filename) if node_status[nid]["alive"] and nid not in exclude][:k]


# ---------------------------------------------------------------- heartbeats
async def check_node(nid: str) -> None:
    url = NODES[nid]
    was_alive = node_status[nid]["alive"]
    try:
        r = await http.get(f"{url}/health", timeout=HEARTBEAT_TIMEOUT)
        r.raise_for_status()
        node_status[nid].update(alive=True, last_seen=time.time(), info=r.json())
        if not was_alive:
            event(f"HEARTBEAT {nid} is UP ({url})")
    except Exception:
        node_status[nid]["alive"] = False
        if was_alive or node_status[nid]["last_seen"] is None:
            event(f"HEARTBEAT {nid} is DOWN ({url})")
            node_status[nid]["last_seen"] = node_status[nid]["last_seen"] or 0


async def heartbeat_loop() -> None:
    while True:
        await asyncio.gather(*(check_node(nid) for nid in NODES))
        await asyncio.sleep(HEARTBEAT_INTERVAL)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global http
    http = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=3))
    event(f"Coordinator started: {len(NODES)} nodes, replication factor {REPLICATION_FACTOR}")
    await asyncio.gather(*(check_node(nid) for nid in NODES))
    task = asyncio.create_task(heartbeat_loop())
    yield
    task.cancel()
    await http.aclose()


app = FastAPI(title="DFS-UTP Coordinator", version="1.0", lifespan=lifespan)


# ---------------------------------------------------------------- helpers
async def push_to_node(nid: str, name: str, path: Path, digest: str) -> bool:
    async def chunks():
        # Stream from disk in 1 MB pieces so large files never sit fully in RAM.
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                yield chunk

    try:
        r = await http.put(
            f"{NODES[nid]}/files/{quote(name)}",
            content=chunks(),
            headers={"X-SHA256": digest, "Content-Length": str(path.stat().st_size)},
        )
        if r.status_code != 200:
            event(f"WRITE FAILED {name} -> {nid}: HTTP {r.status_code}")
            return False
        return True
    except httpx.HTTPError as e:
        event(f"WRITE FAILED {name} -> {nid}: {type(e).__name__}")
        mark_down(nid, "write failed")
        return False


def file_view(name: str, meta: dict) -> dict:
    return {
        "name": name,
        **meta,
        "replica_status": {nid: ("up" if node_status[nid]["alive"] else "down") for nid in meta["replicas"]},
        "available": any(node_status[n]["alive"] for n in meta["replicas"]),
        "live_replicas": sum(node_status[n]["alive"] for n in meta["replicas"]),
    }


# ---------------------------------------------------------------- API
@app.get("/", response_class=HTMLResponse)
def dashboard():
    return (BASE_DIR / "dashboard.html").read_text(encoding="utf-8")


@app.get("/nodes")
def nodes():
    return {
        nid: {
            "url": NODES[nid],
            "alive": s["alive"],
            "last_seen_ago_s": round(time.time() - s["last_seen"], 1) if s["last_seen"] else None,
            "info": s["info"],
        }
        for nid, s in node_status.items()
    }


@app.get("/files")
def files():
    return [file_view(n, m) for n, m in sorted(metadata.items())]


@app.get("/locate/{name}")
def locate(name: str):
    if name not in metadata:
        raise HTTPException(404, "Unknown file")
    v = file_view(name, metadata[name])
    v["replica_urls"] = {nid: f"{NODES[nid]}/files/{quote(name)}" for nid in v["replicas"]}
    return v


@app.get("/state")
def state():
    """Everything the dashboard needs in one call."""
    return {
        "replication_factor": REPLICATION_FACTOR,
        "nodes": nodes(),
        "files": files(),
        "events": list(events),
    }


@app.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    name = os.path.basename(file.filename or "")
    if not name:
        raise HTTPException(400, "Missing filename")

    # Spool to a temp file and hash it.
    h = hashlib.sha256()
    size = 0
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        while chunk := await file.read(1 << 20):
            tmp.write(chunk)
            h.update(chunk)
            size += len(chunk)
    tmp_path = Path(tmp.name)
    digest = h.hexdigest()

    try:
        targets = choose_targets(name, REPLICATION_FACTOR)
        if not targets:
            raise HTTPException(503, "No storage nodes available")
        results = await asyncio.gather(*(push_to_node(n, name, tmp_path, digest) for n in targets))
        stored = [n for n, ok in zip(targets, results) if ok]
        if not stored:
            raise HTTPException(503, "All replica writes failed")
    finally:
        tmp_path.unlink(missing_ok=True)

    async with metadata_lock:
        metadata[name] = {"size": size, "sha256": digest, "replicas": stored, "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        save_metadata()

    who = request.client.host if request.client else "?"
    under = len(stored) < REPLICATION_FACTOR
    event(f"UPLOAD {name} ({size} B) from {who} -> {', '.join(stored)}" + (" [UNDER-REPLICATED]" if under else ""))
    return {"name": name, "size": size, "sha256": digest, "replicas": stored, "under_replicated": under}


@app.get("/download/{name}")
async def download(name: str, request: Request):
    if name not in metadata:
        raise HTTPException(404, "Unknown file")
    meta = metadata[name]
    who = request.client.host if request.client else "?"

    # Prefer replicas the heartbeat says are alive, but still try the others.
    alive = [n for n in meta["replicas"] if node_status[n]["alive"]]
    dead = [n for n in meta["replicas"] if not node_status[n]["alive"]]
    # Replicas the heartbeat already marked DOWN are skipped (tried last, as a fallback).
    tried = [f"{n}:DOWN(heartbeat)" for n in dead] if alive else []
    for nid in alive + dead:
        try:
            req = http.build_request("GET", f"{NODES[nid]}/files/{quote(name)}")
            resp = await http.send(req, stream=True)
            if resp.status_code != 200:
                await resp.aclose()
                tried.append(f"{nid}:HTTP{resp.status_code}")
                continue
        except Exception as e:
            mark_down(nid, f"download: {type(e).__name__}")
            tried.append(f"{nid}:{type(e).__name__}")
            continue

        tried = [t for t in tried if not t.startswith(f"{nid}:")]
        if tried:
            event(f"FAILOVER {name}: {', '.join(tried)} -> served by {nid}")
        event(f"DOWNLOAD {name} to {who} served by {nid}")

        async def body():
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk
            finally:
                await resp.aclose()

        return StreamingResponse(
            body(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": content_disposition(name),
                "X-Served-By": nid,
                "X-Served-By-Url": NODES[nid],
                "X-Failed-Replicas": ",".join(tried),
                "Content-Length": str(meta["size"]),
                "X-SHA256": meta["sha256"],
            },
        )

    event(f"UNAVAILABLE {name}: all replicas failed ({', '.join(tried)})")
    raise HTTPException(503, f"No replica available for {name}. Tried: {tried}")


@app.post("/repair")
async def repair():
    """Restore the replication factor for files that lost replicas."""
    actions = []
    for name, meta in list(metadata.items()):
        live = [n for n in meta["replicas"] if node_status[n]["alive"]]
        missing = REPLICATION_FACTOR - len(live)
        if missing <= 0 or not live:
            continue
        new_targets = choose_targets(name, missing, exclude=set(meta["replicas"]))
        if not new_targets:
            continue
        # Stream the surviving replica to a temp file (no full copy in RAM).
        fd, tmp_name = tempfile.mkstemp()
        tmp_path = Path(tmp_name)
        ok = False
        try:
            with os.fdopen(fd, "wb") as tmp:
                async with http.stream("GET", f"{NODES[live[0]]}/files/{quote(name)}") as r:
                    if r.status_code == 200:
                        async for chunk in r.aiter_bytes():
                            tmp.write(chunk)
                        ok = True
        except httpx.HTTPError:
            mark_down(live[0], "repair read failed")
        if not ok:
            tmp_path.unlink(missing_ok=True)
            continue
        for nid in new_targets:
            if await push_to_node(nid, name, tmp_path, meta["sha256"]):
                meta["replicas"].append(nid)
                actions.append({"file": name, "copied_from": live[0], "to": nid})
                event(f"REPAIR {name}: copied {live[0]} -> {nid}")
        tmp_path.unlink(missing_ok=True)
    async with metadata_lock:
        save_metadata()
    return {"actions": actions}


@app.delete("/files/{name}")
async def delete(name: str):
    if name not in metadata:
        raise HTTPException(404, "Unknown file")
    results = {}
    for nid in metadata[name]["replicas"]:
        try:
            r = await http.delete(f"{NODES[nid]}/files/{quote(name)}")
            results[nid] = r.status_code
        except Exception as e:
            results[nid] = type(e).__name__
    async with metadata_lock:
        del metadata[name]
        save_metadata()
    event(f"DELETE {name}: {results}")
    return {"deleted": name, "nodes": results}
