"""Adapter registry: maps an adapter name to its loader. New layouts add a function here."""
from __future__ import annotations

from .base import load_source as _tabular

ADAPTERS = {"tabular": _tabular}


def get_adapter(name: str):
    if name not in ADAPTERS:
        raise KeyError(f"unknown adapter '{name}' (have {sorted(ADAPTERS)})")
    return ADAPTERS[name]


def load_all(sbu_cfg: dict, base_dir) -> dict:
    """Return {source_name: standard_frame} for every source of the SBU."""
    frames = {}
    for src in sbu_cfg["sources"]:
        frames[src["name"]] = get_adapter(src["adapter"])(sbu_cfg["sbu_id"], src, base_dir)
    return frames
