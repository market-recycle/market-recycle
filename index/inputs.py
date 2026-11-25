"""Download every public input the index uses into data/inputs/.

Run: python -m index.inputs
Needs env vars CENSUS_API_KEY (optional) and FRED_API_KEY (required).
"""
import datetime as _dt
import json
import os
import sys
import time

from marketdata import census, fx, months, store, worldbank

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUTS = os.path.join(ROOT, "data", "inputs")


def path(name):
    return os.path.join(INPUTS, name)


def load_config():
    with open(os.path.join(ROOT, "config", "index.json"), encoding="utf-8") as fh:
        return json.load(fh)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run():
    cfg = load_config()
    n = cfg["history_months"]
    errors = []
    census_key = os.environ.get("CENSUS_API_KEY") or None

    for name, code in cfg["codes"].items():
        flow = "exports" if name.endswith("export") else "imports"
        f = path(f"census_{census.file_key(code)}_{flow}.json")
        log(f"Census {code} {flow}...")
        try:
            store.save(f, census.update_series(store.load(f), flow, code, census_key, history_months=n))
        except Exception as err:
            errors.append(f"Census {code} {flow}: {err}")

    log("World Bank Pink Sheet...")
    try:
        wb = worldbank.fetch(cfg["worldbank_monthly_url"])
        store.save(path("worldbank_monthly.json"), wb)
    except Exception as err:
        errors.append(f"World Bank Pink Sheet: {err} (update worldbank_monthly_url in config/index.json if the link moved)")

    start = (_dt.date.fromisoformat(months.add(months.current(), -n) + "-01")).isoformat()
    fred_key = os.environ.get("FRED_API_KEY")
    # The lira backfill is slow (one request per day), so it goes last and can't starve the others.
    for cur in sorted(cfg["fx_currencies"], key=lambda c: c == "TRY"):
        f = path(f"fx_{cur}_daily.json")
        log(f"FX {cur}...")
        try:
            if cur == "TRY":
                daily = fx.fetch_tcmb_range(start, _dt.date.today().isoformat(), have=store.load(f, {}),
                                            checkpoint=lambda d, f=f: store.save(f, d))
            elif fred_key:
                daily = fx.fetch_fred(cur, fred_key, start)
            else:
                errors.append(f"FX {cur}: FRED_API_KEY is not set")
                continue
            store.save(f, daily)
        except Exception as err:
            errors.append(f"FX {cur}: {err}")

    log("Done.")
    store.save(path("fetched.json"), {"at": store.now_iso(), "errors": errors})
    for e in errors:
        print("ERROR:", e, file=sys.stderr)
    return errors


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
