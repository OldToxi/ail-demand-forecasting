"""Validate external_variables.yaml against the group catalog by var_id; emit a mapping table."""
from __future__ import annotations

import json
import os

import pandas as pd

from . import config


def validate() -> tuple[bool, pd.DataFrame, list]:
    reg = config.load_external_registry()
    cat = pd.read_csv(config.resolve(reg["catalog_file"]))
    cat_ids = set(cat.var_id.astype(str))
    rows, errors = [], []
    for v in reg["variables"]:
        vid = str(v.get("catalog_var_id", ""))
        ids = [x.strip() for x in vid.split("/") if x.strip() and x.strip().lower() != "none" and not x.startswith("none")]
        # keep only catalog-style ids
        ids = [x for x in ids if "-" in x]
        ok = all(i in cat_ids for i in ids) if ids else True
        if not ok:
            errors.append({"feature_key": v["feature_key"], "catalog_var_id": vid,
                           "unknown_ids": [i for i in ids if i not in cat_ids]})
        rows.append({"feature_key": v["feature_key"], "catalog_var_id": vid,
                     "in_catalog": ok, "status": v.get("status", "active" if v.get("enabled", True) else "disabled"),
                     "enabled": bool(v.get("enabled", True))})
    df = pd.DataFrame(rows)
    return (len(errors) == 0), df, errors


if __name__ == "__main__":
    ok, df, errors = validate()
    out = config.OUTPUTS_DIR / "state_check"
    os.makedirs(out, exist_ok=True)
    df.to_csv(out / "PC2_catalog.csv", index=False)
    print("registry validation:", "PASS" if ok else "FAIL", "| variables:", len(df),
          "| mismatches:", len(errors))
    if errors:
        print(json.dumps(errors, indent=2))
