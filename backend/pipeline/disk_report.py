"""Disk use of the project against DISK_BUDGET_GB. Pure Python; works on Windows.

The budget covers project artifacts only (PROJECT_REPORT.md section 16): .venv, frontend/node_modules, data/,
the MongoDB image and the MongoDB volume. Docker Desktop, WSL2 and other projects' images are not counted.

    python -m pipeline.disk_report
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from app.config import REPO_ROOT, get_settings
from pipeline.dq import dir_size_gb

MONGO_IMAGE = "mongo:7"
VOLUME_SUFFIX = "_mongo_data"


def _docker(*args: str) -> str:
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return ""


def docker_sizes_gb() -> dict[str, float]:
    out: dict[str, float] = {}
    if not shutil.which("docker"):
        return out
    size = _docker("image", "inspect", MONGO_IMAGE, "--format", "{{.Size}}").strip()
    if size.isdigit():
        out[f"docker image {MONGO_IMAGE}"] = int(size) / 1024 ** 3
    for line in _docker("system", "df", "-v", "--format", "{{json .}}").splitlines():
        try:
            vols = json.loads(line).get("Volumes") or []
        except json.JSONDecodeError:
            continue
        for v in vols:
            if str(v.get("Name", "")).endswith(VOLUME_SUFFIX) and "caselens" in str(v.get("Name", "")):
                out[f"docker volume {v['Name']}"] = _parse_size(v.get("Size", "0B"))
    return out


def _parse_size(s: str) -> float:
    units = {"B": 1, "kB": 1e3, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}
    for u in sorted(units, key=len, reverse=True):
        if s.endswith(u):
            try:
                return float(s[: -len(u)]) * units[u] / 1024 ** 3
            except ValueError:
                return 0.0
    return 0.0


def mongo_collections() -> list[tuple[str, float, float]]:
    from app.db import get_db, ping
    if not ping():
        return []
    db = get_db()
    rows = []
    for name in sorted(db.list_collection_names()):
        st = db.command("collStats", name)
        rows.append((name, st.get("storageSize", 0) / 1024 ** 2, st.get("totalIndexSize", 0) / 1024 ** 2))
    return rows


def main() -> int:
    s = get_settings()
    items = {
        "data/ (total)": dir_size_gb(s.data_dir),
        ".venv": dir_size_gb(REPO_ROOT / ".venv"),
        "frontend/node_modules": dir_size_gb(REPO_ROOT / "frontend" / "node_modules"),
    }
    print(f"{'item':45} {'GB':>8}")
    for k, v in items.items():
        print(f"{k:45} {v:8.3f}")
    print(f"{'  of which data/chroma':45} {dir_size_gb(s.chroma_path):8.3f}")
    print(f"{'  of which data/ibm (raw cache)':45} {dir_size_gb(s.data_dir / 'ibm'):8.3f}")
    dk = docker_sizes_gb()
    for k, v in dk.items():
        print(f"{k:45} {v:8.3f}")
    if not dk:
        print("docker: not available (image and volume not counted)")
    cols = mongo_collections()
    if cols:
        print("\nMongoDB collections (MB): storage / indexes")
        for name, st, ix in cols:
            print(f"  {name:30} {st:9.1f} {ix:9.1f}")
    total = sum(items.values()) + sum(dk.values())
    pct = 100 * total / s.disk_budget_gb
    print(f"\nTOTAL {total:.2f} GB of DISK_BUDGET_GB={s.disk_budget_gb} ({pct:.0f}%)")
    if pct > 70:
        print("WARNING above 70% of the budget. Cleanup options: delete data/ibm (raw files are in S3); lower "
              "SLICE_HOURS; docker image prune -f; docker builder prune -f; docker compose down -v (deletes MongoDB data)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
