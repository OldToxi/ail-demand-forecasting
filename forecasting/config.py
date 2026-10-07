"""Config loading for the forecasting module.

All paths/horizon/seeds live in config/*.yaml; code reads them here. Nothing is hard-coded in modules.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

# planning-app/forecasting/config.py -> parents[0]=forecasting, [1]=planning-app, [2]=repo root
FORECASTING_DIR = Path(__file__).resolve().parent
APP_ROOT = FORECASTING_DIR.parent
REPO_ROOT = APP_ROOT.parent

CONFIG_DIR = FORECASTING_DIR / "config"
OUTPUTS_DIR = APP_ROOT / "data" / "outputs" / "forecast"


def _load(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))


def load_config() -> dict:
    return _load("config.yaml")


def load_sbus() -> dict:
    return _load("sbus.yaml")


def load_external_registry() -> dict:
    return _load("external_variables.yaml")


def resolve(path: str) -> Path:
    """Resolve a config path: absolute as-is, else relative to the repo root."""
    p = Path(path)
    return p if p.is_absolute() else (REPO_ROOT / p)


def config_hash() -> str:
    parts = []
    for f in sorted(CONFIG_DIR.glob("*.yaml")):
        parts.append(f.name + ":" + hashlib.sha1(f.read_bytes()).hexdigest())
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def data_snapshot(paths) -> str:
    """A cheap content fingerprint (name:size:mtime) of the input files, for run metadata."""
    items = []
    for p in paths:
        p = Path(p)
        if p.exists():
            st = p.stat()
            items.append(f"{p.name}:{st.st_size}:{int(st.st_mtime)}")
    return hashlib.sha1("|".join(sorted(items)).encode()).hexdigest()[:16]


if __name__ == "__main__":
    print(json.dumps({"config_dir": str(CONFIG_DIR), "outputs_dir": str(OUTPUTS_DIR),
                      "config_hash": config_hash()}, indent=1))
