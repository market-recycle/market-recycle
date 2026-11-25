import json
import os
import tempfile
import unittest

from index import panjiva

CSV = """Panjiva export,,,,,
Generated 2026-11-25,,,,,
Shipment Date,Shipper,Goods Shipped,Weight (kg),Value of Goods (USD),Shipment Destination
2026-09-03,ACME,UNCURED RUBBER COMPOUND SCRAP MIXED GRADE,20000,9000,Mexico
09/15/2026,ACME,Uncured steel friction scrap,18000,,Turkey
2026-09-20,BETA,CRUMB RUBBER 10 MESH,22000,2200,India
2026-09-21,BETA,UNVULCANIZED GREEN TIRES SCRAP,15000,6000,India
2026-10-01,GAMMA,MISC SCRAP,5000,,Canada
2026-10-02,GAMMA,,,,
"""


class PanjivaTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "export.csv")
        with open(self.path, "w") as f:
            f.write(CSV)
        self.rules = panjiva.load_rules()

    def test_unvulcanized_is_uncured_not_cured(self):
        self.assertEqual(panjiva.classify("UNVULCANIZED GREEN TIRES", self.rules), ("uncured", "Green tires"))
        self.assertEqual(panjiva.classify("vulcanized crumb", self.rules), ("cured", None))

    def test_forms(self):
        self.assertEqual(panjiva.classify("uncured steel friction", self.rules)[1], "Steel friction")
        self.assertEqual(panjiva.classify("uncured fabric friction rolls", self.rules)[1], "Fabric friction")

    def test_aggregate_and_write(self):
        months, unplaced, skipped = panjiva.aggregate([self.path], self.rules)
        sep = months["2026-09"]["classes"]
        self.assertEqual(sep["uncured"]["shipments"], 3)
        self.assertAlmostEqual(sep["uncured"]["kg"], 53000)
        self.assertEqual(sep["cured"]["shipments"], 1)
        self.assertIn("MISC SCRAP", next(iter(unplaced)))
        self.assertEqual(skipped["no date or weight"], 1)
        out = panjiva.write(months, self.rules, [self.path], out_dir=self.dir)
        doc = json.load(open(next(p for p in out if p.endswith("2026-09.json"))))
        # price per kg uses only shipments that carry a value: (9000 + 6000) / 35000
        self.assertAlmostEqual(doc["classes"]["uncured"]["usd_per_kg"], 15000 / 35000, places=4)
        self.assertNotIn("ACME", json.dumps(doc))  # no shipper names in published output


if __name__ == "__main__":
    unittest.main()
