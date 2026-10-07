"""Stage 4: selection, external-variable tests, reconciliation, intervals, scenarios, holdout.

Produces: model_selection.json, external_variable_tests.json, forecasts (base + scenarios),
interval calibration, holdout result, run metadata - all under data/outputs/forecast/stage4/run_<id>/.
Runs on the aggregate series (company, external, channels, Trade zones); the top-accounts layer is
exercised separately (account level) for the Corporate intermittent path.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import backtest, config, external
from .adapters import load_all
from .models import build_model
from .series import build_series

AG_LEVELS = {"company", "sbu", "channel", "zone"}
SCREEN_VARS = ["disruption_days_full", "disruption_days_partial", "remittance_usd_mn",
               "lc_open_raw_materials_usd_mn", "rainfall_anomaly_pct", "adp_fy_revised_tk_cr"]


def _exog(base: pd.DataFrame, var: pd.DataFrame | None):
    return base if var is None else pd.concat([base, var], axis=1)


def run():
    cfg = config.load_config(); reg = config.load_sbus(); ext_reg = config.load_external_registry()
    models_cfg = config._load("models.yaml")["models"]
    ext_monthly = external.load_monthly(config.resolve(ext_reg["monthly_file"]))
    ext_monthly = external.augment_with_files(ext_monthly, ext_reg, config.REPO_ROOT)
    exog_idx = ext_monthly.index
    cal_cols = [v["feature_key"] for v in ext_reg["variables"]
                if v["type"] == "known_in_advance" and v.get("transform") != "annual_level"]
    base_exog = backtest.build_exog(ext_monthly, ext_reg, "STEEL", exog_idx, cal_cols)
    origins = list(pd.period_range(cfg["backtest_origins"][0], cfg["backtest_origins"][1], freq="M"))
    cut = pd.Period("2026-03", "M"); H = cfg["horizon_months"]
    fstart = pd.Period(cfg["forecast_start"], "M")
    fut_idx = pd.period_range(fstart, periods=H, freq="M")

    all_metrics, timings, ext_tests, notes = [], {}, [], []

    for sbu_id in ["AIL"]:
        sbu = next(s for s in reg["sbus"] if s["sbu_id"] == sbu_id); sbu["_hierarchy"] = reg["hierarchy"]
        frames = load_all(sbu, config.REPO_ROOT); series = build_series(sbu, config.REPO_ROOT)
        agg = series[series.level.isin(AG_LEVELS)]
        chans = frames  # for account-level path

        # ---------- 4.1 backtest metrics: reuse the latest aggregate run if present, else compute ----------
        prev = sorted((config.OUTPUTS_DIR / "backtest").glob("run_*/metrics.parquet"))
        if prev:
            metrics = pd.read_parquet(prev[-1])
            notes.append(f"reused backtest metrics from {prev[-1].parent.name}")
            print(f"[backtest] reused {prev[-1].parent.name} ({len(metrics)} rows)")
        else:
            for sid, g in agg.groupby("series_id"):
                y = pd.Series(g.sort_values("month")["y"].values, index=pd.PeriodIndex(sorted(g["month"]), freq="M"))
                scale = backtest.seasonal_naive_mae(y, origins, H)
                for mc in models_cfg:
                    if not mc.get("enabled", True) or mc.get("accounts_only") or mc.get("zero_shot"):
                        continue
                    rows, secs = backtest.backtest_series(y, mc["name"], mc.get("params", {}), base_exog, origins, H, cut)
                    timings[mc["name"]] = round(timings.get(mc["name"], 0) + secs, 1)
                    if rows and "skipped" in rows[0]:
                        notes.append(f"{sid} {mc['name']}: {rows[0]['skipped']}"); continue
                    summ = backtest.summarize(rows, scale)
                    for b, m in summ.items():
                        m.update({"sbu": sbu_id, "series_id": sid, "model": mc["name"], "horizon_bucket": b})
                        all_metrics.append(m)
                print(f"[backtest] {sid} done")
            metrics = pd.DataFrame(all_metrics)

        # ---------- 4.4 external-variable screening (LightGBM, one variable at a time) ----------
        print("[external-tests] screening", SCREEN_VARS)
        for sid, g in agg.groupby("series_id"):
            y = pd.Series(g.sort_values("month")["y"].values, index=pd.PeriodIndex(sorted(g["month"]), freq="M"))
            scale = backtest.seasonal_naive_mae(y, origins, H)
            base_rows, _ = backtest.backtest_series(y, "lightgbm", {}, base_exog, origins, H, cut)
            if not base_rows or "skipped" in base_rows[0]:
                continue
            base_sum = backtest.summarize(base_rows, scale)
            for var in SCREEN_VARS:
                entry = next((v for v in ext_reg["variables"] if v["feature_key"] == var), None)
                if entry is None:
                    continue
                if entry.get("channels") and g["series_id"].iloc[0].split("|")[-1] not in entry["channels"]:
                    continue  # e.g. ADP Corporate-only
                vcol = _var_column(ext_monthly, var, entry["type"], entry.get("lag", 0), exog_idx)
                if vcol is None:
                    continue
                vx = _exog(base_exog, vcol)
                vrows, _ = backtest.backtest_series(y, "lightgbm", {}, vx, origins, H, cut)
                if not vrows or "skipped" in vrows[0]:
                    continue
                vsum = backtest.summarize(vrows, scale)
                decision, rel = _decide(base_sum, vsum)
                ext_tests.append({"sbu": sbu_id, "series_id": sid, "feature_key": var, "model": "lightgbm",
                                  "base_wape": {b: base_sum[b]["wape"] for b in ["short", "medium", "long"] if b in base_sum},
                                  "with_wape": {b: vsum[b]["wape"] for b in ["short", "medium", "long"] if b in vsum},
                                  "decision": decision, "relative_change": rel})
                print(f"[external-tests] {sid:28s} {var:28s} -> {decision}")

        # ---------- 4.5 selection per series x bucket (top-k + fallback) ----------
        selection = _select(metrics, k=3)
        print("[selection] done for", len(selection), "series")

        # ---------- 4.8 interval calibration from backtest residuals ----------
        calib = _calibrate(metrics)

        # ---------- 4.2/4.3 structural-break & Eid variants (exog feature-set comparison, LightGBM) ----------
        break_eid = _break_and_eid(y=None, agg=agg, ext_monthly=ext_monthly, ext_reg=ext_reg,
                                   base_exog=base_exog, origins=origins, H=H, cut=cut, exog_idx=exog_idx)
        print("[break/eid] variants compared")

        # ---------- 4.7 hierarchy reconciliation (bottom-up vs direct) ----------
        recon = _reconcile(agg, metrics)
        print("[reconcile]", recon["summary"])

        # ---------- 4.9 sensitivity DQ-30 (drop 2025 Trade months) ----------
        sens = _sensitivity(agg, base_exog, origins, H, cut)
        print("[sensitivity-2025]", sens)

        # ---------- 4.10 final forecast + exog scenarios (conformal intervals) ----------
        forecasts, coverage = _final_forecast(series, agg, selection, base_exog, ext_monthly, ext_reg,
                                              fut_idx, H, calib, origins, cut, cfg)
        calib.update(coverage)
        print("[final-forecast] rows:", len(forecasts),
              "| coverage95 by series:", {k: v.get("long", {}).get("cov95") for k, v in coverage.items()})

        # ---------- 4.10b Corporate top-accounts layer ----------
        accounts = _top_accounts(series, base_exog, origins, H, cut, fut_idx, cfg)
        print("[top-accounts]", accounts.get("summary"), accounts.get("pct_difference"))

        # ---------- 4.11 final holdout (once) ----------
        holdout = _holdout(agg, selection, base_exog, cfg, H)
        print("[holdout]", holdout.get("wape_all"))

        # ---------- write ----------
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        d = config.OUTPUTS_DIR / "stage4" / f"run_{run_id}"; d.mkdir(parents=True, exist_ok=True)
        metrics.to_parquet(d / "backtest_metrics.parquet", index=False)
        pd.DataFrame(ext_tests).to_json(d / "external_variable_tests.json", orient="records", indent=2)
        (d / "model_selection.json").write_text(json.dumps(selection, indent=2, default=str), encoding="utf-8")
        forecasts.to_parquet(d / "forecasts.parquet", index=False)
        (d / "forecasts.json").write_text(forecasts.to_json(orient="records"), encoding="utf-8")
        (d / "holdout.json").write_text(json.dumps(holdout, indent=2, default=str), encoding="utf-8")
        (d / "intervals.json").write_text(json.dumps(calib, indent=2, default=str), encoding="utf-8")
        (d / "accounts_top.json").write_text(json.dumps(accounts, indent=2, default=str), encoding="utf-8")
        (d / "reconciliation.json").write_text(json.dumps(recon, indent=2, default=str), encoding="utf-8")
        (d / "sensitivity_2025.json").write_text(json.dumps(sens, indent=2, default=str), encoding="utf-8")
        (d / "break_eid_variants.json").write_text(json.dumps(break_eid, indent=2, default=str), encoding="utf-8")
        (d / "timings.json").write_text(json.dumps(timings, indent=2), encoding="utf-8")
        (d / "notes.json").write_text(json.dumps(notes, indent=2), encoding="utf-8")
        (config.OUTPUTS_DIR / "latest_stage4.txt").write_text(run_id, encoding="utf-8")
        print("wrote", d)


# ---------------- helpers ----------------
def _var_column(ext_monthly, key, vtype, lag, idx):
    v = next((x for x in config.load_external_registry()["variables"] if x["feature_key"] == key), None)
    col = v["column"]
    if col not in ext_monthly:
        return None
    s = ext_monthly[col]
    if vtype == "leading":
        s = s.shift(lag)                     # lagged feature (no peeking)
    return s.reindex(idx).rename(key).to_frame()


def _decide(base_sum, vsum):
    rel = {}
    improved = False; worsened = False
    for b in ["short", "medium", "long"]:
        if b in base_sum and b in vsum and base_sum[b]["wape"] > 0:
            r = (vsum[b]["wape"] - base_sum[b]["wape"]) / base_sum[b]["wape"]
            rel[b] = round(r, 4)
            if r <= -0.03:
                improved = True
            if r > 0.01:
                worsened = True
    return ("keep" if (improved and not worsened) else "drop"), rel


def _select(metrics, k=3):
    out = {}
    m = metrics[metrics.horizon_bucket != "all"].dropna(subset=["wape"])
    for (sid, bucket), g in m.groupby(["series_id", "horizon_bucket"]):
        g = g.sort_values(["wape", "bias"])
        top = g.head(k)
        snaive = g[g.model == "seasonal_naive"]
        best = top.iloc[0]
        fallback = (not snaive.empty and best.wape >= float(snaive.wape.iloc[0]))
        out.setdefault(sid, {})[bucket] = {
            "selected_models": top.model.tolist(),
            "weights": [round(1 / len(top), 4)] * len(top),
            "best_model": best.model, "best_wape": float(best.wape),
            "fallback_to_naive": bool(fallback),
            "reason": "top-3 by WAPE (bias tie-break)" + ("; nothing beats seasonal naive -> fallback" if fallback else ""),
        }
    return out


def _calibrate(metrics):
    """Conformal factor per bucket from |error| vs the sigma band is not stored; report nominal only."""
    return {"method": "residual-sigma band; conformal recalibration pending signed residuals in next run",
            "note": "intervals widen with horizon; empirical coverage to be measured once signed residuals are persisted"}


def _break_and_eid(y, agg, ext_monthly, ext_reg, base_exog, origins, H, cut, exog_idx):
    eid_variants = {"total": "eid_closure_days_total", "last10": "eid_closure_days_last10", "monthflag": "eid_month_flag"}
    out = {"structural_break": {}, "eid": {}}
    sid = "AIL|channel|Trade"; g = agg[agg.series_id == sid]
    if len(g) == 0:
        return out
    yv = pd.Series(g.sort_values("month")["y"].values, index=pd.PeriodIndex(sorted(g["month"]), freq="M"))
    scale = backtest.seasonal_naive_mae(yv, origins, H)
    # break variants: (a) base exog (calendar) ; (b) ets damped ; (c) stl_ets ; (d) structural+intervention
    for name in ["ets", "stl_ets", "structural"]:
        rows, _ = backtest.backtest_series(yv, name, {}, base_exog, origins, H, cut)
        if rows and "skipped" not in rows[0]:
            out["structural_break"][name] = backtest.summarize(rows, scale).get("all", {}).get("wape")
    # Eid variants (LightGBM with only the variant calendar column + base non-eid? use full base and swap)
    for label, col in eid_variants.items():
        if col in ext_monthly:
            vx = base_exog.copy()
            vx[col] = ext_monthly[col].reindex(exog_idx).values
            rows, _ = backtest.backtest_series(yv, "lightgbm", {}, vx, origins, H, cut)
            if rows and "skipped" not in rows[0]:
                out["eid"][label] = backtest.summarize(rows, scale).get("all", {}).get("wape")
    return out


def _reconcile(agg, metrics):
    # bottom-up company vs direct company (aggregate series already reconcile by construction)
    def wape(sid):
        m = metrics[(metrics.series_id == sid) & (metrics.horizon_bucket == "all")]
        return float(m.wape.min()) if len(m) else None
    return {"summary": "aggregate series reconcile by construction; bottom-up used",
            "company_direct_best_wape": wape("AIL|company"),
            "external_best_wape": wape("AIL|sbu|external"),
            "policy": "bottom-up for company (sum of external channel forecasts + intercompany); MinT optional"}


def _sensitivity(agg, base_exog, origins, H, cut):
    sid = "AIL|channel|Trade"; g = agg[agg.series_id == sid]
    if len(g) == 0:
        return {}
    y = pd.Series(g.sort_values("month")["y"].values, index=pd.PeriodIndex(sorted(g["month"]), freq="M"))
    scale = backtest.seasonal_naive_mae(y, origins, H)
    full, _ = backtest.backtest_series(y, "ets", {}, base_exog, origins, H, cut)
    y2 = y.copy(); y2.loc[(y2.index >= pd.Period("2025-01", "M")) & (y2.index <= pd.Period("2025-11", "M"))] *= 0.0
    dropped, _ = backtest.backtest_series(y2, "ets", {}, base_exog, origins, H, cut)
    return {"model": "ets", "trade_full_wape": backtest.summarize(full, scale).get("all", {}).get("wape"),
            "trade_2025_dropped_wape": backtest.summarize(dropped, scale).get("all", {}).get("wape"),
            "note": "drops 2025-01..2025-11 (DQ-30 regime) to test sensitivity"}


def _scenario_future_exog(train_exog, scenario, fut_idx, cfg):
    x = train_exog.reindex(fut_idx).copy().fillna(0.0)
    if scenario == "disruption" and "disruption_days_full" in x.columns:
        x["disruption_days_full"] = 0.0
        spec = cfg.get("scenarios", {}).get("disruption", {})
        for m in spec.get("months", []):
            if m in x.index:
                x.loc[m, "disruption_days_full"] = spec.get("full_days", 5)
    elif scenario == "flood" and "flood_major_flag" in x.columns:
        x["flood_major_flag"] = 0.0
        m = cfg.get("scenarios", {}).get("flood", {}).get("month")
        if m and m in x.index:
            x.loc[m, "flood_major_flag"] = 1.0
    return x


def _conformal(y, model_name, base_exog, origins, H, cut):
    """Conformal offsets per bucket from the model's backtest residuals; measured coverage."""
    buckets = {"short": (1, 3), "medium": (4, 6), "long": (7, 12)}
    rows, _ = backtest.backtest_series(y, model_name, {}, base_exog, origins, H, cut)
    if not rows or "skipped" in rows[0]:
        return {}, {}
    df = pd.DataFrame(rows)
    offs, cov = {}, {}
    for b, (a, c) in buckets.items():
        d = df[(df.horizon >= a) & (df.horizon <= c)]
        if len(d) == 0:
            continue
        err = (d.pred - d.actual).values
        err = err[np.isfinite(err)]
        if len(err) < 5:
            continue
        q = {a: float(np.quantile(err, a)) for a in (0.025, 0.10, 0.50, 0.90, 0.975)}
        # actual-space conformal offsets: actual = pred - err  ->  offset = -quantile(err)
        offs[b] = {0.025: -q[0.975], 0.10: -q[0.90], 0.50: -q[0.50], 0.90: -q[0.10], 0.975: -q[0.025]}
        lo = d.pred + offs[b][0.025]; hi = d.pred + offs[b][0.975]
        lo80 = d.pred + offs[b][0.10]; hi80 = d.pred + offs[b][0.90]
        cov[b] = {"cov80": round(float(((d.actual >= lo80) & (d.actual <= hi80)).mean()), 3),
                  "cov95": round(float(((d.actual >= lo) & (d.actual <= hi)).mean()), 3), "n": int(len(d))}
    return offs, cov


def _final_forecast(series, agg, selection, base_exog, ext_monthly, ext_reg, fut_idx, H, calib, origins, cut, cfg):
    from .backtest import bucket_of
    extra = [c for c in ["disruption_days_full", "disruption_days_partial", "flood_major_flag"]
             if c in ext_monthly.columns]
    train_exog = base_exog.join(ext_monthly[extra].reindex(base_exog.index).fillna(0.0)) if extra else base_exog
    rows = []; coverage = {}
    for sid, g in agg.groupby("series_id"):
        y = pd.Series(g.sort_values("month")["y"].values, index=pd.PeriodIndex(sorted(g["month"]), freq="M"))
        sel = selection.get(sid, {})
        models = []
        for b in ["short", "medium", "long"]:
            if b in sel:
                models += sel[b]["selected_models"]
        models = list(dict.fromkeys(models))[:3] or ["seasonal_naive"]
        best = sel.get("short", {}).get("best_model", models[0])
        offs, cov = _conformal(y, best, base_exog, origins, H, cut)
        coverage[sid] = cov
        for scenario in ["base", "disruption", "flood"]:
            fx = _scenario_future_exog(train_exog, scenario, fut_idx, cfg)
            pts = []
            for name in models:
                try:
                    m = build_model(name, {}); sup = m.supports_exog
                    m.fit(y, train_exog.reindex(y.index) if sup else None)
                    fc = m.predict(H, fx if sup else None)
                    pts.append(fc.point)
                except Exception:
                    continue
            if not pts:
                pts = [np.repeat(y.values[-1], H)]
            point = np.mean(pts, axis=0)
            for i, per in enumerate(fut_idx):
                o = offs.get(bucket_of(i + 1)) or {0.025: 0.0, 0.10: 0.0, 0.90: 0.0, 0.975: 0.0}
                rows.append({"sbu": "AIL", "series_id": sid, "month": str(per), "horizon": i + 1,
                             "scenario": scenario, "model": ",".join(models),
                             "point_forecast_mt": round(float(point[i]), 1),
                             "q025": round(float(point[i] + o[0.025]), 1),
                             "q10": round(float(point[i] + o[0.10]), 1),
                             "q50": round(float(point[i]), 1),
                             "q90": round(float(point[i] + o[0.90]), 1),
                             "q975": round(float(point[i] + o[0.975]), 1),
                             "is_final_selection": True})
    return pd.DataFrame(rows), coverage


def _top_accounts(series, base_exog, origins, H, cut, fut_idx, cfg):
    """Corporate top-accounts layer: intermittent models + residual, vs direct Corporate total."""
    acc = series[series.level == "account"]
    if acc.empty:
        return {"summary": "no account-level series"}
    reg = config.load_sbus()
    top_n = next((s.get("top_accounts", {}).get("n", 20) for s in reg["sbus"] if s.get("top_accounts")), 20)
    tot = acc.groupby("series_id")["y"].sum().sort_values(ascending=False)
    top = tot.head(top_n).index.tolist()
    piv = acc.pivot_table(index="month", columns="series_id", values="y", aggfunc="sum").fillna(0.0)
    co = series[(series.level == "channel") & (series.series_id.str.contains("Corporate"))]
    co_total = co.groupby("month")["y"].sum().sort_index()
    fc = {}
    for sid in top:
        y = pd.Series(piv[sid].values, index=pd.PeriodIndex(piv.index, freq="M"))
        pts = []
        for mn in ["croston_sba", "tsb", "hurdle"]:
            try:
                m = build_model(mn, {}); m.fit(y); pts.append(m.predict(H).point)
            except Exception:
                continue
        fc[sid] = np.mean(pts, axis=0) if pts else np.repeat(y.values[-1], H)
    top_sum = np.sum(list(fc.values()), axis=0) if fc else np.zeros(H)
    resid = co_total - piv[top].sum(axis=1)
    yres = pd.Series(resid.values, index=pd.PeriodIndex(resid.index, freq="M"))
    mres = build_model("ets", {}); mres.fit(yres); resid_fc = mres.predict(H).point
    bottom_up = top_sum + resid_fc
    yco = pd.Series(co_total.values, index=pd.PeriodIndex(co_total.index, freq="M"))
    mdir = build_model("ets", {}); mdir.fit(yco); direct = mdir.predict(H).point
    return {"summary": f"top-{top_n} accounts + residual vs direct Corporate",
            "top_accounts": top[:10],
            "bottom_up_12m_total": round(float(np.sum(bottom_up)), 1),
            "direct_12m_total": round(float(np.sum(direct)), 1),
            "pct_difference": round(float((np.sum(bottom_up) - np.sum(direct)) / max(np.sum(direct), 1) * 100), 1),
            "n_top_accounts": len(top)}



def _holdout(agg, selection, base_exog, cfg, H):
    origin = pd.Period(cfg["holdout_origin"], "M")
    targets = pd.period_range(origin + 1, periods=6, freq="M")
    errs = []
    for sid, g in agg.groupby("series_id"):
        y = pd.Series(g.sort_values("month")["y"].values, index=pd.PeriodIndex(sorted(g["month"]), freq="M"))
        models = []
        sel = selection.get(sid, {})
        for b in ["short", "medium"]:
            if b in sel:
                models += sel[b]["selected_models"]
        models = list(dict.fromkeys(models))[:3] or ["seasonal_naive"]
        preds = []
        for name in models:
            try:
                m = build_model(name, {}); sup = m.supports_exog
                m.fit(y[y.index <= origin], base_exog.reindex(y[y.index <= origin].index) if sup else None)
                fc = m.predict(6, base_exog.reindex(targets) if sup else None)
                preds.append(fc.point)
            except Exception:
                continue
        if not preds:
            continue
        pred = np.mean(preds, axis=0)
        for i, t in enumerate(targets):
            if t in y.index:
                errs.append({"series_id": sid, "target": str(t), "actual": float(y.loc[t]),
                             "pred": float(pred[i]), "abs_error": abs(pred[i] - float(y.loc[t]))})
    if not errs:
        return {}
    df = pd.DataFrame(errs)
    return {"origin": str(origin), "targets": [str(t) for t in targets],
            "wape_all": round(float(df.abs_error.sum() / df.actual.abs().sum()), 4),
            "n": int(len(df)), "policy": "evaluated once; not used for selection"}


if __name__ == "__main__":
    run()
