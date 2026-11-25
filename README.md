# Uncured Rubber Scrap Index — market-recycle.com

A monthly movement index for U.S. uncured rubber scrap, computed **only from public data**. This repository is meant to be public: its code, inputs and published values let anyone check any value.

```
config/index.json      name, status, base month, weights, sources
marketdata/            public-data fetchers (Census, World Bank, FRED, TCMB)
index/inputs.py        download inputs -> data/inputs/
index/compute.py       compute components and candidate index -> research/, drafts/
index/publish.py       add an approved draft to site/data (refuses to revise a published month)
index/backtest.py      PRIVATE backtest against your own purchase prices (file stays off GitHub)
site/                  the website (no build step)
```

## Status: pre-launch
`config/index.json` has `"status": "prelaunch"` and placeholder weights. While the status is pre-launch, nothing is published: the site explains the methodology draft, and the monthly job only updates the research series.

## Going live
1. **Backtest.** Export monthly average purchase prices by grade to a CSV on your own computer, with columns `month,grade,price` (for example `2024-03,Grade AB,0.42`). Keep the file outside this folder, then run:
   `python -m index.backtest --prices ~/Desktop/purchase_prices.csv`
   It prints how well each candidate weighting tracks each grade. It refuses to read or write files inside the repository.
2. **Set weights** in `config/index.json` to the chosen weighting. Set `methodology_version` to `"1.0"`, update the Weights section of `site/methodology.html`, and remove the draft notice.
3. **Counsel review** of the methodology page before any contract cites the index.
4. Set `"status": "live"`. From then on, the monthly job opens a pull request with each new value. **Merging the pull request publishes it**; closing it holds the value back.

## One-time setup
1. **GitHub.** Create an organization for the publisher and a **public** repository `market-recycle` in it. Upload this folder.
   - Under **Settings → Actions → General**, turn on "Allow GitHub Actions to create and approve pull requests".
   - Under **Settings → Secrets → Actions**, add `FRED_API_KEY`, plus `CENSUS_API_KEY` (optional).
   - Under **Actions → Monthly index update → Run workflow**, start the first run.
2. **Hosting: GitHub Pages.** Under **Settings → Pages**, Source is **GitHub Actions**; `.github/workflows/pages.yml` publishes `site/`. Custom domain `market-recycle.com`, **Enforce HTTPS** on.
3. **DNS at Network Solutions** (nameservers unchanged): A records for `@` → 185.199.108.153, 185.199.109.153, 185.199.110.153, 185.199.111.153; CNAME `www` → `market-recycle.github.io`.
4. **Email.** Set up forwarding for `index@market-recycle.com` to a monitored inbox. The site lists that address for comments and complaints.
5. When a separate publisher LLC exists, name it in `site/about.html` under "Publisher".

## Rules this code enforces
- Published values are never changed. `publish.py` refuses to write a month that's already published.
- Inputs are stored exactly as downloaded on each run, so any value can be traced to its inputs.
- No private data. `.gitignore` blocks common price-file names, and the backtest refuses files inside the repository.

## Panjiva shipment data

The publisher's Panjiva license allows publishing figures derived from it. Each month:

1. In Panjiva, export the saved U.S.-exports search (HS 4004, plus 4005 and 4006 if wanted) as CSV or Excel.
2. Run `python -m index.panjiva path/to/export.csv`. It sorts every shipment into uncured / cured /
   unclassified from its description (rules in `config/panjiva.json`), and writes monthly aggregates to
   `data/inputs/panjiva/YYYY-MM.json`. Descriptions it couldn't place are printed for tuning the rules.
   Workbooks with one tab per company are fine: every tab is read and duplicates are dropped.
   Affiliates to leave out are listed in a file kept outside the repo; point `PANJIVA_EXCLUDE_FILE` at it.
3. Commit only the aggregates. The raw export names shippers and consignees and is git-ignored.

Panjiva covers ocean bills of lading; truck and rail to Mexico and Canada largely don't appear.
