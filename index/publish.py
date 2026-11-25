"""Add an approved draft to the published record.

Run by the monthly workflow on its own branch; the change goes live only when
the pull request is merged. Published values are never changed afterwards: this
script refuses to write a month that is already published.

Run: python -m index.publish 2026-09
"""
import csv
import datetime as _dt
import os
import sys

from marketdata import months, store

from .inputs import ROOT, load_config

SITE_DATA = os.path.join(ROOT, "site", "data")


def next_publication(cfg, after=None):
    today = after or _dt.date.today()
    day = cfg["publication_day"]
    target = _dt.date(today.year, today.month, day)
    if target <= today:
        y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        target = _dt.date(y, m, day)
    return target.isoformat()


def empty_record(cfg):
    return {
        "name": cfg["name"], "short_name": cfg["short_name"], "status": cfg["status"],
        "methodology_version": cfg["methodology_version"], "base_month": cfg["base_month"],
        "base_value": cfg["base_value"], "next_publication": None, "latest": None, "history": [],
    }


def write_csv(record):
    with open(os.path.join(SITE_DATA, "history.csv"), "w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["month", "value", "published", "methodology_version", "note"])
        for h in record["history"]:
            wr.writerow([h["month"], f"{h['value']:.2f}", h["published"], h["methodology_version"], h.get("note", "")])


def refresh_meta(cfg):
    """Keep name, status and version in step with the config without touching published values."""
    f = os.path.join(SITE_DATA, "index.json")
    record = store.load(f) or empty_record(cfg)
    for k in ("name", "short_name", "status", "methodology_version", "base_month", "base_value"):
        record[k] = cfg[k]
    record["next_publication"] = next_publication(cfg) if cfg["status"] == "live" else None
    store.save(f, record)
    write_csv(record)
    store.save(os.path.join(SITE_DATA, "methodology.json"), {
        "version": cfg["methodology_version"],
        "status": cfg["status"],
        "base_month": cfg["base_month"],
        "weights": cfg["weights"],
        # Weights stay off the public pages until the backtest has set them and v1.0 is live.
        "weights_published": cfg["status"] == "live",
    })
    return record


def publish(month, today=None):
    cfg = load_config()
    if cfg["status"] != "live":
        raise SystemExit("Methodology is not in effect yet (config status is not 'live'); nothing published.")
    draft = store.load(os.path.join(ROOT, "drafts", f"{month}.json"))
    if not draft:
        raise SystemExit(f"No draft for {month}.")
    f = os.path.join(SITE_DATA, "index.json")
    record = store.load(f) or empty_record(cfg)
    if any(h["month"] == month for h in record["history"]):
        raise SystemExit(f"{month} is already published; published values are never revised.")
    published = (today or _dt.date.today()).isoformat()
    entry = {
        "month": month, "value": draft["value"], "published": published,
        "methodology_version": draft["methodology_version"], "components": draft["components"],
    }
    prev = record["history"][-1] if record["history"] else None
    record["history"].append(entry)
    record["history"].sort(key=lambda h: h["month"])
    record["latest"] = {
        **entry,
        "label": months.label(month),
        "change_pct": round((entry["value"] / prev["value"] - 1) * 100, 2) if prev else None,
    }
    record["next_publication"] = next_publication(cfg, today)
    store.save(f, record)
    write_csv(record)
    return entry


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--meta":
        refresh_meta(load_config())
    elif len(sys.argv) == 2:
        print(publish(sys.argv[1]))
    else:
        sys.exit("usage: python -m index.publish YYYY-MM | --meta")
