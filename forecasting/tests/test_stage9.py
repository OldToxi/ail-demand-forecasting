"""Stage-9 tests: acceptance tests for the Checkpoint-2 fixes + repository hygiene."""
from __future__ import annotations

import glob
import os
import subprocess

import pandas as pd
import pytest

from forecasting import config
from forecasting.fva import forecast_value_added
from forecasting.stage4 import select_top_accounts


def test_account_selection_uses_only_past():
    """P0.2: top-account selection at an origin must not use data after that origin."""
    months = pd.period_range("2023-01", periods=36, freq="M")
    piv = pd.DataFrame({
        "AIL|account|Corporate|a": [100.0] * 36,
        "AIL|account|Corporate|b": [90.0] * 36,
        "AIL|account|Corporate|spike": [0.0] * 30 + [100000.0] * 6,   # big only in the future
    }, index=months)
    origin = pd.Period("2024-12", "M")            # before the spike
    top = select_top_accounts(piv, origin, top_n=2)
    assert "AIL|account|Corporate|spike" not in top, "selection used data after the origin"
    assert set(top) == {"AIL|account|Corporate|a", "AIL|account|Corporate|b"}


def _latest_stage4():
    ds = [d for d in sorted(glob.glob(str(config.OUTPUTS_DIR / "stage4" / "run_*")))
          if os.path.exists(os.path.join(d, "forecasts.parquet"))]
    return ds[-1]


def test_scenario_uses_same_ensemble_as_base():
    """P0.3: scenario rows must carry the same ensemble (model column) as base."""
    fc = pd.read_parquet(os.path.join(_latest_stage4(), "forecasts.parquet"))
    for sid, g in fc.groupby("series_id"):
        models = {sc: set(m.split(",")) for sc, m in g.groupby("scenario")["model"].first().items()}
        base = models.get("base", set())
        for sc, ms in models.items():
            assert ms == base, f"{sid}/{sc}: scenario ensemble {ms} != base {base}"


def test_forecast_value_added():
    """P1.12: FVA compares statistical vs adjusted WAPE and reports the improvement."""
    records = [
        {"series_id": "AIL|sbu|external", "month": "2026-10", "statistical": 1000, "adjusted": 1100,
         "actual": 1090, "entered_by": "planner1"},
        {"series_id": "AIL|sbu|external", "month": "2026-11", "statistical": 1000, "adjusted": 1050,
         "actual": 1055, "entered_by": "planner1"},
    ]
    out = forecast_value_added(records)
    assert len(out) == 1 and out.iloc[0]["n"] == 2
    assert out.iloc[0]["wape_adjusted"] <= out.iloc[0]["wape_statistical"]


def test_registry_validates_against_catalog():
    """P1.10: every registry catalog_var_id must exist in the group catalog."""
    from forecasting.validate_registry import validate
    ok, df, errors = validate()
    assert ok, f"catalog var_id mismatches: {errors}"
    assert "catalog_var_id" in df.columns and len(df) >= 30


def test_repository_has_no_control_characters():
    """P1.13: no tracked text file may contain control characters (tab allowed only in code files)."""
    files = subprocess.check_output(["git", "ls-files"], text=True,
                                    cwd=str(config.APP_ROOT)).splitlines()
    bad = []
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        if ext in {".png", ".jpg", ".ico", ".parquet", ".xlsx"}:
            continue
        p = os.path.join(str(config.APP_ROOT), f)
        try:
            txt = open(p, encoding="utf-8").read()
        except Exception:
            continue
        allowed = {"\n", "\r"}
        if ext in {".py", ".ts", ".tsx", ".json", ".yaml", ".yml"}:
            allowed.add("\t")
        ctrl = sorted({hex(ord(c)) for c in txt if ord(c) < 32 and c not in allowed})
        if ctrl:
            bad.append((f, ctrl))
    assert not bad, f"control characters found: {bad}"
