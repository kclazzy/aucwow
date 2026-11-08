import json, tempfile, unittest
from pathlib import Path
from forever_deals import vendors, links


class VendorTest(unittest.TestCase):
    def test_csv_import_with_npc_and_location(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "v.csv"
            p.write_text("item_id;price;vendor;npc_id;location;stock\n"
                         "2320;8;Stephanie Turner;1346;Штормград, ремесленный квартал;\n"
                         "bad;1;x;;;\n", encoding="utf-8")
            items, errors = vendors.import_file(p)
        v = items[2320]
        self.assertEqual((v.price, v.vendor, v.npc_id, v.stock), (8, "Stephanie Turner", 1346, None))
        self.assertEqual(v.location, "Штормград, ремесленный квартал")
        self.assertEqual(len(errors), 1)

    def test_roundtrip_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "v.json"
            vendors.save(p, {5: vendors.VendorItem(5, 100, "A", "Loc", 3, 77)})
            self.assertEqual(vendors.load(p)[5], vendors.VendorItem(5, 100, "A", "Loc", 3, 77))

    def test_links(self):
        self.assertEqual(links.item_url(2320), "https://www.wowhead.com/forever/item=2320")
        self.assertEqual(links.npc_url(1346), "https://www.wowhead.com/forever/npc=1346")


if __name__ == "__main__":
    unittest.main()
