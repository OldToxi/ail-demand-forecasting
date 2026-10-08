"""Run manifests: every run writes run_<id>/manifest.json; later stages consume an EXPLICIT run id and
only accept manifests with status == "ok". Failed/partial runs are marked "failed" and never picked up.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_manifest(run_dir, stage: str, status: str, artifacts: list, extra: dict | None = None) -> str:
    os.makedirs(run_dir, exist_ok=True)
    m = {
        "stage": stage,
        "run_id": os.path.basename(str(run_dir)).replace("run_", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,                       # "ok" | "failed"
        "artifacts": [str(a) for a in artifacts],
    }
    if extra:
        m.update(extra)
    p = os.path.join(str(run_dir), "manifest.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2)
    return p


def read_manifest(run_dir) -> dict | None:
    p = os.path.join(str(run_dir), "manifest.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def require_ok(run_dir) -> dict:
    m = read_manifest(run_dir)
    if m is None:
        raise FileNotFoundError(f"no manifest in {run_dir}")
    if m.get("status") != "ok":
        raise RuntimeError(f"run {run_dir} status={m.get('status')} - not consumable")
    return m
