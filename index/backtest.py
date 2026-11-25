"""Private backtest: how well do candidate index weightings track what you actually pay?

YOUR PRICE FILE NEVER GOES INTO THIS REPOSITORY. Keep it on your own computer.
The .gitignore blocks the usual names, but check before you commit anything.

Price file: a CSV with columns  month,grade,price
    month  YYYY-MM
    grade  your grade name (e.g. "Grade AB")
    price  average price paid that month, in any one consistent unit per grade

Run:  python -m index.backtest --prices ~/Desktop/purchase_prices.csv
It reads research/components.csv (public), tries every weighting in 10% steps,
and prints, for each grade, how closely month-to-month and quarter-to-quarter
changes in the index move with changes in your price, at lags of 0-3 months.
Nothing is written unless you pass --out.
"""
import argparse
import csv
import itertools
import os
import statistics
import sys

from marketdata import months

from .compute import COMPONENTS
from .inputs import ROOT, load_config


def read_components():
    f = os.path.join(ROOT, "research", "components.csv")
    rows = {}
    with open(f, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if all(r[k] for k in COMPONENTS):
                rows[r["month"]] = {k: float(r[k]) for k in COMPONENTS}
    return rows


def read_prices(path):
    by_grade = {}
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            try:
                by_grade.setdefault(r["grade"].strip(), {})[r["month"].strip()[:7]] = float(r["price"])
            except (KeyError, ValueError):
                continue
    return by_grade


def pct_changes(series, step=1):
    out = {}
    for m, v in series.items():
        prev = series.get(months.add(m, -step))
        if prev:
            out[m] = v / prev - 1
    return out


def fit(index, prices, lag, step):
    """Correlation of index changes (led by `lag` months) with price changes. Returns (r, n)."""
    ic, pc = pct_changes(index, step), pct_changes(prices, step)
    pairs = [(ic[months.add(m, -lag)], pc[m]) for m in pc if months.add(m, -lag) in ic]
    if len(pairs) < 8:
        return None, len(pairs)
    xs, ys = zip(*pairs)
    if statistics.pstdev(xs) == 0 or statistics.pstdev(ys) == 0:
        return None, len(pairs)
    return statistics.correlation(xs, ys), len(pairs)


def weightings(step=0.1):
    n = round(1 / step)
    for combo in itertools.product(range(n + 1), repeat=len(COMPONENTS)):
        if sum(combo) == n:
            yield dict(zip(COMPONENTS, (c / n for c in combo)))


def series_for(comps, w):
    return {m: 100 * sum(w[k] * c[k] for k in COMPONENTS) for m, c in comps.items()}


def best_lag(index, prices, step):
    best = (None, None, 0)
    for lag in range(4):
        r, n = fit(index, prices, lag, step)
        if r is not None and (best[0] is None or r > best[0]):
            best = (r, lag, n)
    return best


def fmt_w(w):
    return " ".join(f"{k}={w[k]:.0%}" for k in COMPONENTS)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prices", required=True, help="CSV of your monthly purchase prices (stays private)")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--out", help="optional path for the report; keep it outside the repository")
    args = ap.parse_args(argv)

    real = os.path.realpath(args.prices)
    if real.startswith(os.path.realpath(ROOT) + os.sep):
        sys.exit("Refusing: move your price file outside the repository folder first.")

    cfg = load_config()
    comps = read_components()
    lines = [f"Backtest over {len(comps)} months of public components ({min(comps)} to {max(comps)}).", ""]
    for grade, prices in sorted(read_prices(args.prices).items()):
        lines.append(f"== {grade}  ({len(prices)} months of prices)")
        cur = series_for(comps, cfg["weights"])
        for step, label in ((1, "monthly"), (3, "quarterly")):
            r, lag, n = best_lag(cur, prices, step)
            lines.append(f"  current weights, {label}: " + ("not enough overlap" if r is None else f"r={r:+.2f} at {lag}-month lead (n={n})"))
        ranked = []
        for w in weightings():
            r, lag, n = best_lag(series_for(comps, w), prices, 3)
            if r is not None:
                ranked.append((r, sum(1 for v in w.values() if v > 0), lag, n, w))
        ranked.sort(key=lambda t: (-round(t[0], 2), t[1]))  # ties go to the simpler weighting
        lines.append(f"  best weightings by quarterly fit (simplest first on ties):")
        for r, _, lag, n, w in ranked[: args.top]:
            lines.append(f"    r={r:+.2f} lead={lag}m n={n}  {fmt_w(w)}")
        if ranked and ranked[0][0] < 0.5:
            lines.append("  note: no weighting tracks this grade well (r < 0.50). Don't index this grade yet.")
        lines.append("")
    report = "\n".join(lines)
    print(report)
    if args.out:
        if os.path.realpath(args.out).startswith(os.path.realpath(ROOT) + os.sep):
            sys.exit("Refusing to write the report inside the repository.")
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
