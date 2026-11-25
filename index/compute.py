"""Compute the index from the public inputs in data/inputs/.

Formula (methodology section 3):
    I_t = base_value * sum_k  w_k * R_k,t
where each component R_k,t is that input's level in month t divided by its level
in the base month. Components:
    scrap_export  U.S. export unit value, HTS 4004.00.00, trailing 3-month value / quantity
    virgin        mean of TSR20, RSS3 (World Bank) and SBR, BR import unit values (Census, 3-month)
    fx            buyer currencies vs USD, base-rate / current-rate, weighted by each country's share
                  of U.S. 4004 export value in the 12 months ending in the base month
    energy        mean of Brent and WTI monthly averages (World Bank)

Run: python -m index.compute        writes research/components.csv and research/candidate.csv
     python -m index.compute --draft writes drafts/<latest month>.json for approval
"""
import csv
import json
import os
import statistics
import sys

from marketdata import census, fx, months, store

from .inputs import ROOT, load_config, path

COMPONENTS = ("scrap_export", "virgin", "fx", "energy")


def load_inputs(cfg):
    codes = cfg["codes"]
    return {
        "scrap": (store.load(path(f"census_{census.file_key(codes['scrap_export'])}_exports.json")) or {}).get("months", {}),
        "sbr": (store.load(path(f"census_{census.file_key(codes['sbr_import'])}_imports.json")) or {}).get("months", {}),
        "br": (store.load(path(f"census_{census.file_key(codes['br_import'])}_imports.json")) or {}).get("months", {}),
        "wb": store.load(path("worldbank_monthly.json")) or {},
        "fx": {c: fx.monthly_average(store.load(path(f"fx_{c}_daily.json")) or {}) for c in cfg["fx_currencies"]},
    }


def _rel(series, month, base):
    a, b = series.get(month), series.get(base)
    if a is None or not b:
        return None
    return a / b


def fx_shares(cfg, inp):
    """Each buyer country's share of U.S. 4004 export value, 12 months ending at the base month."""
    base = cfg["base_month"]
    window = months.span(months.add(base, -11), base)
    totals = {}
    for cur, meta in cfg["fx_currencies"].items():
        totals[cur] = sum(inp["scrap"].get(m, {}).get("countries", {}).get(meta["census_country"], {}).get("value", 0.0)
                          for m in window)
    s = sum(totals.values())
    if s <= 0:
        return None
    return {c: v / s for c, v in totals.items()}


def components_for(month, cfg, inp, shares):
    base, w = cfg["base_month"], cfg["census_window_months"]

    def uv(series, m):
        return census.unit_value(series, m, w)

    out = {}
    a, b = uv(inp["scrap"], month), uv(inp["scrap"], base)
    out["scrap_export"] = a / b if a and b else None

    parts = []
    for key in ("tsr20", "rss3"):
        parts.append(_rel(inp["wb"].get(key, {}).get("months", {}), month, base))
    for key in ("sbr", "br"):
        a, b = uv(inp[key], month), uv(inp[key], base)
        parts.append(a / b if a and b else None)
    out["virgin"] = statistics.fmean(parts) if parts and None not in parts else None

    if shares:
        total = 0.0
        for cur, share in shares.items():
            r_base, r_now = inp["fx"][cur].get(base), inp["fx"][cur].get(month)
            if not r_base or not r_now:
                total = None
                break
            total += share * (r_base / r_now)  # a stronger buyer currency (fewer units per USD) raises the index
        out["fx"] = total
    else:
        out["fx"] = None

    e = [_rel(inp["wb"].get(k, {}).get("months", {}), month, base) for k in ("brent", "wti")]
    out["energy"] = statistics.fmean(e) if None not in e else None
    return out


def index_value(comps, cfg):
    if any(comps.get(k) is None for k in COMPONENTS):
        return None
    return round(cfg["base_value"] * sum(cfg["weights"][k] * comps[k] for k in COMPONENTS), 2)


def compute_series(cfg=None, inp=None):
    cfg = cfg or load_config()
    inp = inp or load_inputs(cfg)
    shares = fx_shares(cfg, inp)
    first = months.add(cfg["base_month"], -24)
    rows = []
    for m in months.span(first, months.add(months.current(), -1)):
        comps = components_for(m, cfg, inp, shares)
        rows.append({"month": m, **comps, "index": index_value(comps, cfg)})
    return rows, shares


def write_research(rows):
    os.makedirs(os.path.join(ROOT, "research"), exist_ok=True)
    with open(os.path.join(ROOT, "research", "components.csv"), "w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["month", *COMPONENTS, "index"])
        for r in rows:
            if any(r[k] is not None for k in COMPONENTS):
                wr.writerow([r["month"], *[("" if r[k] is None else f"{r[k]:.6f}") for k in COMPONENTS],
                             "" if r["index"] is None else f"{r['index']:.2f}"])


def latest_complete(rows):
    done = [r for r in rows if r["index"] is not None]
    return done[-1] if done else None


def write_draft(row, cfg, shares):
    draft = {
        "month": row["month"],
        "value": row["index"],
        "components": {k: round(row[k], 6) for k in COMPONENTS},
        "weights": cfg["weights"],
        "fx_shares": {k: round(v, 6) for k, v in (shares or {}).items()},
        "base_month": cfg["base_month"],
        "methodology_version": cfg["methodology_version"],
        "computed_at": store.now_iso(),
        "inputs_fetched": (store.load(path("fetched.json")) or {}).get("at"),
    }
    f = os.path.join(ROOT, "drafts", f"{row['month']}.json")
    store.save(f, draft)
    return f, draft


def main(argv):
    cfg = load_config()
    rows, shares = compute_series(cfg)
    write_research(rows)
    last = latest_complete(rows)
    if not last:
        print("No month has all inputs yet.")
        return 0
    print(f"Latest complete month: {last['month']}  index {last['index']}")
    if "--draft" in argv:
        f, _ = write_draft(last, cfg, shares)
        print(f"Draft written: {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
