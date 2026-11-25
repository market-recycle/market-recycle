"""Turn a Panjiva shipment export into publishable monthly aggregates.

    python -m index.panjiva path/to/export.csv [more files ...]

Reads CSV or XLSX as Panjiva exports them, sorts each shipment into uncured / cured /
unclassified from its written description (rules in config/panjiva.json), and writes
data/inputs/panjiva/YYYY-MM.json for every month found: shipment counts, kilograms and,
where Panjiva carries a value, US dollars, by class, form and destination country.

The raw export is never written into the repository: it names shippers and consignees.
Only the aggregates are saved. Descriptions the rules could not place are printed so
the rules can be tightened.
"""
import csv
import datetime as _dt
import io
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "inputs", "panjiva")
LB_TO_KG = 0.45359237


def load_rules(path=None):
    with open(path or os.path.join(ROOT, "config", "panjiva.json")) as f:
        return json.load(f)


def _find_header(raw):
    # The header is the first row with at least three non-empty cells, one of them naming a date.
    for i, r in enumerate(raw[:30]):
        cells = [str(c).strip().lower() for c in r if str(c).strip()]
        if len(cells) >= 3 and any("date" in c for c in cells):
            return i
    return None


def read_tables(path):
    """Yield (header, rows) for every sheet in an XLSX, or the one table in a CSV.
    Sheets without a recognisable header (summaries, notes) are skipped."""
    if path.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheets = [[[("" if v is None else v) for v in r] for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets]
    else:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8-sig", "replace")
        sheets = [list(csv.reader(io.StringIO(text)))]
    found = False
    for raw in sheets:
        i = _find_header(raw)
        if i is None:
            continue
        header = [str(c).strip() for c in raw[i]]
        low = [h.lower() for h in header]
        if not any("goods" in h or "description" in h for h in low):
            continue
        found = True
        yield header, raw[i + 1:]
    if not found:
        raise ValueError(f"No shipment table found in {os.path.basename(path)}")


def load_exclusions():
    """Names of the publisher's affiliates, kept outside the repository (one per line).
    Set PANJIVA_EXCLUDE_FILE to its path. Matching is case-insensitive and by substring."""
    p = os.environ.get("PANJIVA_EXCLUDE_FILE")
    if not p or not os.path.exists(p):
        return []
    with open(p) as f:
        return [ln.strip().lower() for ln in f if ln.strip() and not ln.startswith("#")]


def map_columns(header, rules):
    low = [h.lower() for h in header]
    found = {}
    for field, names in rules["columns"].items():
        for name in names:  # exact name first, then contains
            if name in low:
                found[field] = low.index(name)
                break
        else:
            for name in names:
                hit = next((i for i, h in enumerate(low) if name in h and i not in found.values()), None)
                if hit is not None:
                    found[field] = hit
                    break
    missing = [f for f in ("date", "description") if f not in found]
    if missing:
        raise ValueError(f"Missing column(s) {missing}. Columns seen: {header}")
    if not any(k in found for k in ("weight_kg", "weight_lb", "weight_t")):
        raise ValueError(f"No weight column. Columns seen: {header}")
    return found


def num(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.\-]", "", str(v))
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def month_of(v):
    if isinstance(v, (_dt.date, _dt.datetime)):
        return f"{v.year:04d}-{v.month:02d}"
    s = str(v).strip()
    for cand in (s, s.split(" ")[0], s.split("T")[0]):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y"):
            try:
                d = _dt.datetime.strptime(cand, fmt)
                return f"{d.year:04d}-{d.month:02d}"
            except ValueError:
                continue
    m = re.match(r"(\d{4})-(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _has(text, kw):
    """Keyword at the start of a word, so 'cured' doesn't match inside 'uncured'."""
    return re.search(r"(?<![a-z])" + re.escape(kw), text) is not None


def classify(desc, rules, hs=""):
    d = " ".join(str(desc).lower().split())
    cls = "unclassified"
    for c in rules["classes"]:
        if any(_has(d, k) for k in c["keywords"]):
            cls = c["class"]
            break
    if cls == "unclassified":
        h4 = re.sub(r"\D", "", str(hs))[:4]
        cls = rules.get("hs_overrides", {}).get(h4, cls) if h4 else cls
    form = next((f["form"] for f in rules["forms"] if any(_has(d, k) for k in f["keywords"])), None)
    if cls != "uncured scrap":
        form = None  # forms describe uncured scrap only
    return cls, form


def weight_kg(row, cols):
    if "weight_kg" in cols and num(row[cols["weight_kg"]]):
        return num(row[cols["weight_kg"]])
    if "weight_lb" in cols and num(row[cols["weight_lb"]]):
        return num(row[cols["weight_lb"]]) * LB_TO_KG
    if "weight_t" in cols and num(row[cols["weight_t"]]):
        return num(row[cols["weight_t"]]) * 1000
    return None


def _bucket():
    return {"shipments": 0, "kg": 0.0, "value_usd": 0.0, "kg_with_value": 0.0}


def _add(b, kg, val):
    b["shipments"] += 1
    b["kg"] += kg
    if val:
        b["value_usd"] += val
        b["kg_with_value"] += kg


def _cell(r, cols, field):
    return r[cols[field]] if field in cols and cols[field] < len(r) else ""


def aggregate(paths, rules, exclude=None):
    exclude = exclude if exclude is not None else load_exclusions()
    sources = [x.lower() for x in rules.get("sources", [])]
    months, unplaced, skipped, seen = {}, Counter(), Counter(), set()
    for path in paths:
        for header, rows in read_tables(path):
            cols = map_columns(header, rules)
            for r in rows:
                if not any(str(c).strip() for c in r):
                    continue
                r = list(r) + [""] * (len(header) - len(r))
                src = str(_cell(r, cols, "source")).strip().lower()
                if sources and src and src not in sources:
                    skipped["other data source"] += 1
                    continue
                # Mexico's import records also cover shipments from other countries: keep U.S.-origin only.
                if str(_cell(r, cols, "origin")).strip().lower() not in ("", "united states", "usa", "us"):
                    skipped["not from the U.S."] += 1
                    continue
                prefixes = rules.get("hs_prefixes")
                h = re.sub(r"\D", "", str(_cell(r, cols, "hs")))
                if prefixes and h and not any(h.startswith(x) for x in prefixes):
                    skipped["other HS code"] += 1
                    continue
                parties = (str(_cell(r, cols, "shipper")) + " " + str(_cell(r, cols, "consignee"))).lower()
                if any(x in parties for x in exclude):
                    skipped["excluded party"] += 1
                    continue
                m = month_of(r[cols["date"]])
                kg = weight_kg(r, cols)
                if not m or not kg or kg <= 0:
                    skipped["no date or weight"] += 1
                    continue
                val = num(r[cols["value_usd"]]) if "value_usd" in cols else None
                country = str(_cell(r, cols, "country")).strip().title() or "Unknown"
                # The same shipment can sit on several tabs (e.g. one per company tracked).
                key = (str(_cell(r, cols, "shipper")).lower()[:24], str(r[cols["date"]])[:10], round(kg), val, country)
                if key in seen:
                    skipped["duplicate"] += 1
                    continue
                seen.add(key)
                desc = r[cols["description"]]
                cls, form = classify(desc, rules, _cell(r, cols, "hs"))
                if cls == "unclassified":
                    unplaced[" ".join(str(desc).split())[:120]] += 1
                rec = months.setdefault(m, {"classes": {}, "forms": {}, "countries": {}})
                _add(rec["classes"].setdefault(cls, _bucket()), kg, val)
                if form:
                    _add(rec["forms"].setdefault(form, _bucket()), kg, val)
                _add(rec["countries"].setdefault(country, {}).setdefault(cls, _bucket()), kg, val)
    return months, unplaced, skipped


def _finish(b):
    b["kg"] = round(b["kg"], 1)
    b["usd_per_kg"] = round(b["value_usd"] / b["kg_with_value"], 4) if b["kg_with_value"] else None
    b["value_usd"] = round(b["value_usd"], 2)
    del b["kg_with_value"]
    return b


def write(months, rules, sources, out_dir=OUT_DIR):
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for m, rec in sorted(months.items()):
        doc = {
            "month": m, "source": "Panjiva (S&P Global) U.S. export shipments", "rules_version": rules["rules_version"],
            "files": sorted(os.path.basename(s) for s in sources),
            "classes": {k: _finish(v) for k, v in rec["classes"].items()},
            "forms": {k: _finish(v) for k, v in rec["forms"].items()},
            "countries": {c: {k: _finish(v) for k, v in d.items()} for c, d in sorted(rec["countries"].items())},
        }
        p = os.path.join(out_dir, f"{m}.json")
        with open(p, "w") as f:
            json.dump(doc, f, indent=1, sort_keys=True)
            f.write("\n")
        written.append(p)
    return written


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    rules = load_rules()
    months, unplaced, skipped = aggregate(argv, rules)
    for p in write(months, rules, argv):
        print("wrote", os.path.relpath(p, ROOT))
    for m, rec in sorted(months.items()):
        tot = sum(b["kg"] for b in rec["classes"].values()) or 1
        parts = ", ".join(f"{k} {b['kg'] / 1000:,.0f} t ({b['kg'] / tot * 100:.0f}%)" for k, b in sorted(rec["classes"].items()))
        print(f"{m}: {parts}")
    if skipped:
        print("skipped rows:", dict(skipped))
    if unplaced:
        print("\nDescriptions the rules could not place (most common first):")
        for d, n in unplaced.most_common(25):
            print(f"  {n:4d}  {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
