"""Stage 4: selection, external-variable candidates, backtest-vs-holdout, conformal intervals,
scenarios (SARIMAX-delta), reconciliation, provisional-anchor sensitivity, clipping audit.

Consumes an EXPLICIT backtest run (manifest status ok). Writes run_<id>/manifest.json.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

from . import backtest, config, external, run_manifest
from .adapters import load_all
from .models import build_model
from .models import statistical
from .series import build_series

AG = {"company", "sbu", "channel", "zone"}
LEVEL_TRACKERS = {"naive", "ma3", "ma6"}
# external-variable candidate models (kept by the strict test in report_extra item2)
CANDIDATES = [
    ("lightgbm", "remittance_usd_mn_yoy", "AIL|channel|Corporate"),
    ("lightgbm", "remittance_usd_mn", "AIL|zone|Trade|Dhaka"),
    ("lightgbm", "lc_open_raw_materials_usd_mn", "AIL|zone|Trade|Dhaka"),
    ("lightgbm", "remittance_usd_mn", "AIL|zone|Trade|North East"),
]


def _yser(g):
    return pd.Series(g.sort_values("month")["y"].values, index=pd.PeriodIndex(sorted(g["month"]), freq="M"))


def _var_series(ext_monthly, er, key, lag):
    is_yoy = key.endswith("_yoy")
    base_key = key[:-4] if is_yoy else key
    entry = next(v for v in er["variables"] if v["feature_key"] == base_key)
    s = ext_monthly[entry["column"]]
    if is_yoy:
        s = s.pct_change(12) * 100
    if entry["type"] == "leading":
        s = s.shift(lag)
    return s.rename(key)


def _select(metrics, k=3):
    out = {}
    m = metrics[metrics.horizon_bucket != "all"].dropna(subset=["wape"])
    for (sid, bucket), g in m.groupby(["series_id", "horizon_bucket"]):
        g = g.sort_values(["wape", "bias"])
        top = g.head(k)
        out.setdefault(sid, {})[bucket] = {
            "selected_models": top.model.tolist(),
            "weights": [round(1 / len(top), 4)] * len(top),
            "external_variables_used": {r.model: ([getattr(r, "ext_vars")] if ("+" in str(r.model) and getattr(r, "ext_vars", None)) else [])
                                        for r in top.itertuples()},
            "best_model": top.iloc[0].model, "best_wape": float(top.iloc[0].wape),
            "fallback_to_naive": bool((g[g.model == "seasonal_naive"].wape.min() if (g.model == "seasonal_naive").any() else 9) <= top.iloc[0].wape),
            "reason": "top-3 by WAPE (bias tie-break)",
        }
    return out


def _conformal(y, model_name, base_exog, origins, H, cut):
    buckets = {"short": (1, 3), "medium": (4, 6), "long": (7, 12)}
    rows, _ = backtest.backtest_series(y, model_name, {}, base_exog, origins, H, cut)
    if not rows or "skipped" in rows[0]:
        return {}, {}
    df = pd.DataFrame(rows)
    offs, cov = {}, {}
    for b, (a, c) in buckets.items():
        d = df[(df.horizon >= a) & (df.horizon <= c)]
        err = (d.pred - d.actual).values
        err = err[np.isfinite(err)]
        if len(err) < 5:
            continue
        q = {al: float(np.quantile(err, al)) for al in (0.025, 0.10, 0.50, 0.90, 0.975)}
        offs[b] = {0.025: -q[0.975], 0.10: -q[0.90], 0.50: -q[0.50], 0.90: -q[0.10], 0.975: -q[0.025]}
        lo = d.pred + offs[b][0.025]; hi = d.pred + offs[b][0.975]
        lo80 = d.pred + offs[b][0.10]; hi80 = d.pred + offs[b][0.90]
        cov[b] = {"cov80": round(float(((d.actual >= lo80) & (d.actual <= hi80)).mean()), 3),
                  "cov95": round(float(((d.actual >= lo) & (d.actual <= hi)).mean()), 3), "n": int(len(d))}
    return offs, cov


def _model_for(name):
    """Resolve a (possibly synthetic) candidate name to (base_model_name, extra_var or None)."""
    if "+" in name:
        base, var = name.split("+", 1)
        return base, var
    return name, None


def _exog_with(train_exog, var, ext_monthly, er):
    if not var:
        return train_exog
    base_key = var[:-4] if var.endswith("_yoy") else var
    lag = next(v["lag"] for v in er["variables"] if v["feature_key"] == base_key)
    s = _var_series(ext_monthly, er, var, lag)
    return train_exog.join(s.reindex(train_exog.index).rename(var))


def _fit_predict(name, y, train_exog, fut_exog, ext_monthly, er, H):
    base, var = _model_for(name)
    m = build_model(base, {})
    X = _exog_with(train_exog, var, ext_monthly, er) if m.supports_exog else None
    Xf = _exog_with(fut_exog, var, ext_monthly, er) if m.supports_exog else None
    m.fit(y, X)
    return m.predict(H, Xf)


def select_top_accounts(piv: pd.DataFrame, origin: pd.Period, top_n: int = 20) -> list:
    """Top-N accounts by trailing 24m volume AS OF origin (uses only data <= origin)."""
    hist = piv[piv.index <= origin].tail(24)
    return hist.sum().sort_values(ascending=False).head(top_n).index.tolist()


def _top_accounts_backtest(series, base_exog, origins, cut, H, top_n=20):
    """Per-origin top-N selection (trailing 24m as of origin), bottom-up vs direct WAPE, h1-6."""
    acc = series[series.level == "account"]
    co = series[(series.level == "channel") & (series.series_id.str.contains("Corporate"))]
    piv = acc.pivot_table(index="month", columns="series_id", values="y", aggfunc="sum").fillna(0.0)
    yco = _yser(co)
    bu_err = di_err = denom = 0.0
    for o in origins:
        if o not in yco.index:
            continue
        hist = piv[piv.index <= o].tail(24)
        top = select_top_accounts(piv, o, top_n)
        targets = pd.period_range(o + 1, periods=H, freq="M")
        keep = [t for t in targets if t <= cut and t in yco.index]
        if not keep:
            continue
        top_sum = np.zeros(H)
        for sid in top:
            s = pd.Series(piv[sid].values, index=pd.PeriodIndex(piv.index, freq="M"))
            s = s[s.index <= o]
            pts = []
            for mn in ["croston_sba", "tsb", "hurdle"]:
                try:
                    mm = build_model(mn, {}); mm.fit(s); pts.append(mm.predict(H).point)
                except Exception:
                    continue
            top_sum += np.mean(pts, axis=0) if pts else np.repeat(s.values[-1], H)
        resid = yco[yco.index <= o] - piv[top][piv[top].index <= o].sum(axis=1)
        mr = build_model("ets", {}); mr.fit(pd.Series(resid.values, index=resid.index)); bu = top_sum + mr.predict(H).point
        md = build_model("ets", {}); md.fit(yco[yco.index <= o]); di = md.predict(H).point
        for i, t in enumerate(targets):
            if t in yco.index and (i + 1) <= 6:
                a = float(yco.loc[t]); denom += abs(a)
                bu_err += abs(bu[i] - a); di_err += abs(di[i] - a)
    return {"bottom_up_wape_h1_6": round(bu_err / max(denom, 1), 4),
            "direct_wape_h1_6": round(di_err / max(denom, 1), 4),
            "selected": "bottom_up" if bu_err <= di_err else "direct", "n": int(denom > 0),
            "policy": "top-20 re-selected per origin (trailing 24m as of origin)"}


def _scenario_coefficients(y, exog_s, H, fut_idx):
    """SARIMAX coefficients (with 95% CI) for disruption_days_full and flood_major_flag."""
    from statsmodels.tsa.statespace.sarimax import SARIMAX as SM
    cols = [c for c in ["eid_closure_days_total", "working_days_6day", "fy_end_flag", "monsoon_flag",
                        "dry_season_flag", "slump", "disruption_days_full", "flood_major_flag"] if c in exog_s.columns]
    X = exog_s[cols].reindex(y.index)
    mu, sd = X.mean(), X.std().replace(0, 1)
    res = {}
    try:
        m = SM(y.values, exog=((X - mu) / sd).values, order=(1, 1, 1), seasonal_order=(0, 1, 1, 12),
               enforce_stationarity=True, enforce_invertibility=True).fit(disp=False, maxiter=100)
        ci = m.conf_int(); names = list(X.columns)
        for name in ["disruption_days_full", "flood_major_flag"]:
            if name in names:
                i = names.index(name)
                coef = float(m.params[len(m.params) - len(names) + i]); lo, hi = ci[len(m.params) - len(names) + i]
                res[name] = {"coef": round(coef, 5), "ci95": [round(float(lo), 5), round(float(hi), 5)]}
    except Exception as e:
        res["error"] = type(e).__name__
    return res


def _scenario_delta(y, exog_s, fut_idx, cfg, H):
    """delta = SARIMAX(scenario exog) - SARIMAX(base exog), same data; None if effect not estimable."""
    from statsmodels.tsa.statespace.sarimax import SARIMAX as SM
    cols = [c for c in ["eid_closure_days_total", "working_days_6day", "fy_end_flag", "monsoon_flag",
                        "dry_season_flag", "slump", "disruption_days_full", "flood_major_flag"] if c in exog_s.columns]
    X = exog_s[cols].reindex(y.index); mu, sd = X.mean(), X.std().replace(0, 1)
    try:
        m = SM(y.values, exog=((X - mu) / sd).values, order=(1, 1, 1), seasonal_order=(0, 1, 1, 12),
               enforce_stationarity=True, enforce_invertibility=True).fit(disp=False, maxiter=100)
    except Exception:
        return None, None
    out = {}
    for scen in ["disruption", "flood"]:
        Xf = exog_s.reindex(fut_idx).fillna(0.0).copy()
        for c in cols:
            if c not in Xf:
                Xf[c] = 0.0
        if scen == "disruption" and "disruption_days_full" in Xf:
            Xf["disruption_days_full"] = 0.0
            for mm in cfg.get("scenarios", {}).get("disruption", {}).get("months", []):
                if mm in Xf.index:
                    Xf.loc[mm, "disruption_days_full"] = cfg["scenarios"]["disruption"].get("full_days", 5)
        if scen == "flood" and "flood_major_flag" in Xf:
            Xf["flood_major_flag"] = 0.0
            mm = cfg.get("scenarios", {}).get("flood", {}).get("month")
            if mm and mm in Xf.index:
                Xf.loc[mm, "flood_major_flag"] = 1.0
        Xb = exog_s.reindex(fut_idx).fillna(0.0)[cols]
        try:
            pb = np.asarray(m.forecast(H, exog=((Xb - mu) / sd).values), float)
            ps = np.asarray(m.forecast(H, exog=((Xf[cols] - mu) / sd).values), float)
            out[scen] = (ps - pb)
        except Exception:
            out[scen] = None
    return out, m


def run(backtest_run: str, run_id: str | None = None) -> str:
    cfg = config.load_config(); reg = config.load_sbus(); er = config.load_external_registry()
    models_cfg = config._load("models.yaml")["models"]
    run_manifest.require_ok(backtest_run)                       # P0.1: explicit, ok-only
    metrics = pd.read_parquet(os.path.join(backtest_run, "metrics.parquet"))
    ext_monthly = external.augment_with_files(external.load_monthly(config.resolve(er["monthly_file"])), er, config.REPO_ROOT)
    cal_cols = [v["feature_key"] for v in er["variables"] if v["type"] == "known_in_advance" and v.get("transform") != "annual_level"]
    base_exog = backtest.build_exog(ext_monthly, er, "STEEL", ext_monthly.index, cal_cols)
    extra = [c for c in ["disruption_days_full", "disruption_days_partial", "flood_major_flag"] if c in ext_monthly.columns]
    train_exog = base_exog.join(ext_monthly[extra].reindex(base_exog.index).fillna(0.0))
    origins = list(pd.period_range(cfg["backtest_origins"][0], cfg["backtest_origins"][1], freq="M"))
    recent = [o for o in origins if o >= pd.Period("2025-07", "M")]
    cut = pd.Period("2026-03", "M"); H = cfg["horizon_months"]
    fut_idx = pd.period_range(cfg["forecast_start"], periods=H, freq="M")

    sbu = next(s for s in reg["sbus"] if s["sbu_id"] == "AIL"); sbu["_hierarchy"] = reg["hierarchy"]
    series = build_series(sbu, config.REPO_ROOT)
    agg = series[series.level.isin(AG)]

    statistical.reset_clip_log()
    # ---- P0.4 external-variable candidate models: evaluate and add to the selection table ----
    cand_rows, cand_usage = [], {}
    keep_series = {}
    for base, var, sid in CANDIDATES:
        keep_series.setdefault(sid, []).append(var)
        g = agg[agg.series_id == sid]
        if g.empty:
            continue
        y = _yser(g)
        exog_c = _exog_with(train_exog.join(external.intervention_frame(sid, cfg, train_exog.index)), var, ext_monthly, er)
        rows, _ = backtest.backtest_series(y, base, {}, exog_c, origins, H, cut, series_id=sid)
        if not rows or "skipped" in rows[0]:
            continue
        scale = backtest.seasonal_naive_mae(y, origins, H)
        summ = backtest.summarize(rows, scale)
        name = f"{base}+{var}"
        for b, m in summ.items():
            m.update({"sbu": "AIL", "series_id": sid, "model": name, "horizon_bucket": b, "ext_vars": var})
            cand_rows.append(m)
        # recent-origin WAPE (P1.6 support)
        rrows, _ = backtest.backtest_series(y, base, {}, exog_c, recent, H, cut, series_id=sid)
    if cand_rows:
        metrics = pd.concat([metrics, pd.DataFrame(cand_rows)], ignore_index=True)
    selection = _select(metrics, k=3)

    # ---- P1.6 recent-origin WAPE (report only) ----
    recent_rows = []
    for sid, g in agg.groupby("series_id"):
        y = _yser(g); exog_s = train_exog.join(external.intervention_frame(sid, cfg, train_exog.index))
        for name in [m["name"] for m in models_cfg if m.get("enabled", True) and not m.get("accounts_only")]:
            rows, _ = backtest.backtest_series(y, name, {}, exog_s, recent, H, cut, series_id=sid)
            if rows and "skipped" not in rows[0]:
                d = pd.DataFrame(rows); recent_rows.append({"series_id": sid, "model": name,
                    "wape_recent": round(float(d.abs_error.sum() / max(d.actual.abs().sum(), 1)), 4)})
    recent_df = pd.DataFrame(recent_rows)

    # ---- conformal intervals + coverage (P1.8) ----
    calib = {"method": "conformal on backtest residuals of the selected best model per series x bucket "
                       "(offsets = -quantile(pred-actual)); coverage measured on the same backtest residuals"}
    coverage = {}
    for sid, g in agg.groupby("series_id"):
        y = _yser(g); exog_s = train_exog.join(external.intervention_frame(sid, cfg, train_exog.index))
        best = selection.get(sid, {}).get("short", {}).get("best_model", "ets")
        offs, cov = _conformal(y, _model_for(best)[0], exog_s, origins, H, cut)
        calib[sid] = {"offsets": offs, "coverage": cov}

    # ---- final forecast (base + SARIMAX-delta scenarios) + reconciliation ----
    forecasts, provisional, levelweights, sc_coefs, sc_table = [], {}, {}, {}, []
    for sid, g in agg.groupby("series_id"):
        y = _yser(g); exog_s = train_exog.join(external.intervention_frame(sid, cfg, train_exog.index))
        sel = selection.get(sid, {})
        members = []
        for b in ["short", "medium", "long"]:
            if b in sel:
                members += sel[b]["selected_models"]
        members = list(dict.fromkeys(members))[:3] or ["seasonal_naive"]
        levelweights[sid] = round(sum(1 for m in members if m in LEVEL_TRACKERS) / len(members), 2)
        # base ensemble
        pts = []
        for name in members:
            try:
                pts.append(_fit_predict(name, y, exog_s, exog_s.reindex(fut_idx), ext_monthly, er, H).point)
            except Exception:
                continue
        base = np.mean(pts, axis=0) if pts else np.repeat(y.values[-1], H)
        # scenarios via SARIMAX delta (P0.3)
        delta, _m = _scenario_delta(y, exog_s, fut_idx, cfg, H)
        names = ["base"] + [s for s in ["disruption", "flood"] if delta and delta.get(s) is not None]
        offs_s = calib.get(sid, {}).get("offsets", {})
        for scen in names:
            arr = base + (delta.get(scen, 0.0) if scen != "base" and delta else 0.0)
            for i, per in enumerate(fut_idx):
                b = backtest.bucket_of(i + 1); o = offs_s.get(b) or {}
                forecasts.append({"sbu": "AIL", "series_id": sid, "month": str(per), "horizon": i + 1,
                                  "scenario": scen, "model": ",".join(members),
                                  "point_forecast_mt": round(float(arr[i]), 1),
                                  "q025": round(float(arr[i] + o.get(0.025, 0.0)), 1),
                                  "q10": round(float(arr[i] + o.get(0.10, 0.0)), 1),
                                  "q50": round(float(arr[i]), 1),
                                  "q90": round(float(arr[i] + o.get(0.90, 0.0)), 1),
                                  "q975": round(float(arr[i] + o.get(0.975, 0.0)), 1),
                                  "is_final_selection": True})
        # coefficients + non-positive rule (P0.3)
        coefs = _scenario_coefficients(y, exog_s, H, fut_idx)
        sc_coefs[sid] = coefs
        for name in ["disruption_days_full", "flood_major_flag"]:
            c = coefs.get(name)
            if c and (c["coef"] > 0 or c["ci95"][0] <= 0 <= c["ci95"][1]):
                sc_table.append({"series_id": sid, "feature": name, "coef": c["coef"], "ci95": c["ci95"],
                                 "verdict": "not estimable from history (non-negative / spans zero)"})
        # provisional-anchor sensitivity (P1.5)
        y2 = y[y.index < pd.Period("2026-09", "M")]
        pts2 = []
        for name in members:
            try:
                pts2.append(_fit_predict(name, y2, exog_s.reindex(y2.index), exog_s.reindex(fut_idx), ext_monthly, er, H).point)
            except Exception:
                continue
        base2 = np.mean(pts2, axis=0) if pts2 else np.repeat(y2.values[-1], H)
        ch = (base2.sum() - base.sum()) / max(base.sum(), 1) * 100
        provisional[sid] = {"base_12m": round(float(base.sum()), 1), "excl_sep2026_12m": round(float(base2.sum()), 1),
                            "pct_change": round(float(ch), 2), "flag_sensitive": bool(abs(ch) > 3)}
    fc = pd.DataFrame(forecasts)
    fc = _reconcile_forecasts(fc)

    # ---- top-accounts corrected comparison (P0.2) ----
    topacc = _top_accounts_backtest(series, train_exog, origins, cut, H)

    # ---- holdout per-series WAPE + coverage (P1.8) ----
    origin = pd.Period(cfg["holdout_origin"], "M"); targets = pd.period_range(origin + 1, periods=6, freq="M")
    holdout = {"origin": str(origin), "per_series": {}, "coverage": {}}
    allerr = []
    for sid, g in agg.groupby("series_id"):
        y = _yser(g); exog_s = train_exog.join(external.intervention_frame(sid, cfg, train_exog.index))
        sel = selection.get(sid, {}); members = []
        for b in ["short", "medium"]:
            if b in sel:
                members += sel[b]["selected_models"]
        members = list(dict.fromkeys(members))[:3] or ["seasonal_naive"]
        pts = []
        for name in members:
            try:
                pts.append(_fit_predict(name, y[y.index <= origin], exog_s.reindex(y[y.index <= origin].index),
                                        exog_s.reindex(targets), ext_monthly, er, 6).point)
            except Exception:
                continue
        if not pts:
            continue
        pred = np.mean(pts, axis=0)
        ae = av = 0.0; within80 = within95 = 0; nn = 0
        offs = calib.get(sid, {}).get("offsets", {})
        for i, t in enumerate(targets):
            if t in y.index:
                a = float(y.loc[t]); ae += abs(pred[i] - a); av += abs(a); nn += 1; allerr.append((pred[i], a))
                o = offs.get("short", {}) or {}
                lo95 = pred[i] + o.get(0.025, -1e9); hi95 = pred[i] + o.get(0.975, 1e9)
                lo80 = pred[i] + o.get(0.10, -1e9); hi80 = pred[i] + o.get(0.90, 1e9)
                within95 += int(lo95 <= a <= hi95); within80 += int(lo80 <= a <= hi80)
        holdout["per_series"][sid] = {"wape": round(ae / max(av, 1), 4), "n": nn,
                                      "cov80": round(within80 / nn, 3) if nn else None,
                                      "cov95": round(within95 / nn, 3) if nn else None}
    holdout["wape_all"] = round(float(np.mean([v["wape"] for v in holdout["per_series"].values()])), 4) if holdout["per_series"] else None
    cov80_all = [v["cov80"] for v in holdout["per_series"].values() if v["cov80"] is not None]
    holdout["cov80_all"] = round(float(np.mean(cov80_all)), 3) if cov80_all else None
    widen = None
    if holdout["cov80_all"] is not None and holdout["cov80_all"] < 0.65:
        widen = round(0.80 / max(holdout["cov80_all"], 1e-3), 2)

    # ---- clipping audit (P1.9) ----
    bt_clip = []
    try:
        with open(os.path.join(backtest_run, "clipping.json"), encoding="utf-8") as f:
            bt_clip = json.load(f)
    except Exception:
        pass
    clipping = {"backtest_events": len(bt_clip), "stage4_events": len(statistical.CLIP_LOG),
                "backtest_by_model": {}, "stage4_detail": statistical.CLIP_LOG[:50]}
    for e in bt_clip:
        mo = e.get("context", {}).get("model", "?")
        clipping["backtest_by_model"][mo] = clipping["backtest_by_model"].get(mo, 0) + e.get("n_clipped", 0)

    # ---- write ----
    run_id = run_id or run_manifest.new_run_id()
    d = config.OUTPUTS_DIR / "stage4" / f"run_{run_id}"; d.mkdir(parents=True, exist_ok=True)
    metrics.to_parquet(d / "backtest_metrics.parquet", index=False)
    fc.to_parquet(d / "forecasts.parquet", index=False)
    (d / "model_selection.json").write_text(json.dumps(selection, indent=2, default=str), encoding="utf-8")
    (d / "recent_origin_wape.json").write_text(recent_df.to_json(orient="records", indent=2), encoding="utf-8")
    (d / "intervals.json").write_text(json.dumps(calib, indent=2, default=str), encoding="utf-8")
    (d / "holdout.json").write_text(json.dumps(holdout, indent=2, default=str), encoding="utf-8")
    (d / "scenarios.json").write_text(json.dumps({"coefficients": sc_coefs, "notes": sc_table,
                                                  "method": "delta = SARIMAX(scenario exog) - SARIMAX(base exog), same fit"},
                                                 indent=2, default=str), encoding="utf-8")
    (d / "provisional_sensitivity.json").write_text(json.dumps({"per_series": provisional,
                                                                "level_tracking_weight": levelweights}, indent=2, default=str), encoding="utf-8")
    (d / "top_accounts.json").write_text(json.dumps(topacc, indent=2, default=str), encoding="utf-8")
    (d / "clipping.json").write_text(json.dumps(clipping, indent=2, default=str), encoding="utf-8")
    (d / "backtest_run.txt").write_text(str(backtest_run), encoding="utf-8")
    run_manifest.write_manifest(d, "stage4", "ok",
        [d / "forecasts.parquet", d / "model_selection.json", d / "holdout.json", d / "intervals.json",
         d / "scenarios.json", d / "provisional_sensitivity.json", d / "top_accounts.json", d / "clipping.json"],
        {"backtest_run": str(backtest_run), "widen_factor": widen})
    print("stage4 run:", d, "| holdout wape", holdout["wape_all"], "| cov80", holdout["cov80_all"], "| widen", widen)
    print("top accounts:", topacc)
    print("clipping:", clipping["backtest_events"], "backtest /", clipping["stage4_events"], "stage4")
    print("scenario non-estimable:", len(sc_table))
    return str(d)


def _reconcile_forecasts(df: pd.DataFrame) -> pd.DataFrame:
    qcols = ["point_forecast_mt", "q025", "q10", "q50", "q90", "q975"]
    zones = ["AIL|zone|Trade|Dhaka", "AIL|zone|Trade|North", "AIL|zone|Trade|North East", "AIL|zone|Trade|South"]
    for sc in df["scenario"].unique():
        for q in qcols:
            piv = df[df.scenario == sc].pivot_table(index="month", columns="series_id", values=q, aggfunc="sum")
            z = [c for c in zones if c in piv.columns]
            if z and "AIL|channel|Trade" in piv.columns:
                piv["AIL|channel|Trade"] = piv[z].sum(axis=1)
            if {"AIL|channel|Corporate", "AIL|channel|Trade"} <= set(piv.columns):
                piv["AIL|sbu|external"] = piv["AIL|channel|Corporate"] + piv["AIL|channel|Trade"]
            if {"AIL|sbu|external", "AIL|channel|Intercompany"} <= set(piv.columns):
                piv["AIL|company"] = piv["AIL|sbu|external"] + piv["AIL|channel|Intercompany"]
            for sid in piv.columns:
                for m in piv.index:
                    df.loc[(df.scenario == sc) & (df.series_id == sid) & (df.month == m), q] = round(float(piv.loc[m, sid]), 1)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest-run", required=True)
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args()
    run(a.backtest_run, a.run_id)


if __name__ == "__main__":
    main()
