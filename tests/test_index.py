import datetime as _dt
import os
import tempfile
import unittest
from unittest import mock

from index import compute, publish


def flat_inputs(cfg, scale_after=None):
    """Synthetic inputs: every input constant, optionally scaled by 1.1 from a given month."""
    ms = [f"{y}-{m:02d}" for y in (2023, 2024, 2025) for m in range(1, 13)]
    f = lambda m: 1.1 if scale_after and m >= scale_after else 1.0
    country = {meta["census_country"]: {"value": 25.0, "qty": 10.0} for meta in cfg["fx_currencies"].values()}
    scrap = {m: {"value": 100.0 * f(m), "qty": 100.0, "countries": country} for m in ms}
    trade = {m: {"value": 200.0 * f(m), "qty": 100.0} for m in ms}
    wb = {k: {"months": {m: 2.0 * f(m) for m in ms}} for k in ("tsr20", "rss3", "brent", "wti")}
    fxm = {c: {m: 10.0 / f(m) for m in ms} for c in cfg["fx_currencies"]}  # currency strengthens by 10%
    return {"scrap": scrap, "sbr": trade, "br": trade, "wb": wb, "fx": fxm}


class Compute(unittest.TestCase):
    def setUp(self):
        self.cfg = compute.load_config()

    def test_base_month_is_base_value(self):
        inp = flat_inputs(self.cfg)
        shares = compute.fx_shares(self.cfg, inp)
        self.assertAlmostEqual(sum(shares.values()), 1.0)
        comps = compute.components_for(self.cfg["base_month"], self.cfg, inp, shares)
        self.assertEqual(compute.index_value(comps, self.cfg), 100.0)

    def test_uniform_ten_percent_rise(self):
        inp = flat_inputs(self.cfg, scale_after="2024-07")
        shares = compute.fx_shares(self.cfg, inp)
        comps = compute.components_for("2024-12", self.cfg, inp, shares)
        self.assertAlmostEqual(compute.index_value(comps, self.cfg), 110.0, places=2)

    def test_missing_input_gives_no_value(self):
        inp = flat_inputs(self.cfg)
        inp["wb"]["rss3"]["months"].pop("2025-06")
        comps = compute.components_for("2025-06", self.cfg, inp, compute.fx_shares(self.cfg, inp))
        self.assertIsNone(compute.index_value(comps, self.cfg))


class Publish(unittest.TestCase):
    def test_next_publication(self):
        cfg = {"publication_day": 10}
        self.assertEqual(publish.next_publication(cfg, _dt.date(2026, 11, 24)), "2026-12-10")
        self.assertEqual(publish.next_publication(cfg, _dt.date(2026, 12, 3)), "2026-12-10")

    def test_never_revises(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "drafts"))
            os.makedirs(os.path.join(tmp, "site", "data"))
            cfg = dict(compute.load_config(), status="live")
            from marketdata import store
            store.save(os.path.join(tmp, "drafts", "2026-09.json"),
                       {"value": 103.2, "methodology_version": "1.0", "components": {}})
            with mock.patch.object(publish, "ROOT", tmp), \
                 mock.patch.object(publish, "SITE_DATA", os.path.join(tmp, "site", "data")), \
                 mock.patch.object(publish, "load_config", return_value=cfg):
                publish.publish("2026-09", today=_dt.date(2026, 11, 10))
                with self.assertRaises(SystemExit):
                    publish.publish("2026-09", today=_dt.date(2026, 11, 11))
                rec = store.load(os.path.join(tmp, "site", "data", "index.json"))
                self.assertEqual(rec["latest"]["value"], 103.2)
                self.assertEqual(rec["next_publication"], "2026-12-10")


if __name__ == "__main__":
    unittest.main()
