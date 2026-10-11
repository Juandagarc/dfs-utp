#!/usr/bin/env python3
"""Ping every node in config/nodes.json and call its /health endpoint.
Works on Windows, Linux and macOS:  python scripts/check_connectivity.py"""
import json
import platform
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

cfg = json.loads((Path(__file__).resolve().parent.parent / "config" / "nodes.json").read_text())
flag = "-n" if platform.system() == "Windows" else "-c"
for n in cfg["nodes"]:
    host = urllib.parse.urlparse(n["url"]).hostname
    try:
        ping_ok = subprocess.run(["ping", flag, "2", host], capture_output=True, timeout=10).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        ping_ok = False
    try:
        h = json.load(urllib.request.urlopen(n["url"] + "/health", timeout=3))
        app = f"HTTP OK   host={h['hostname']} files={h['files']}"
    except Exception as e:
        app = f"HTTP FAIL ({type(e).__name__})"
    print(f"{n['id']:<6} {host:<16} ping={'OK  ' if ping_ok else 'FAIL'} {app}")
