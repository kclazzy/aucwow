import json
import tempfile
import unittest
from pathlib import Path

from forever_deals import appdata, runner, viewmodel as vm, websource
from forever_deals.websource import WebSourceError

PAGE1 = """<table><tr><th>Item</th><th>Lowest price</th><th>Market price</th><th>For sale</th><th>Vendor</th></tr>
<tr><td><a href="/en/items/2320-thread">Coarse Thread</a> (Cloth, level 5)</td><td>1200</td><td>1500</td><td>2310</td><td>8</td></tr>
<tr><td><a href="/en/items/2589-linen">Linen Cloth</a> (Cloth)</td><td>50</td><td>60</td><td>900</td><td>—</td></tr></table>"""
PAGE2 = """<table><tr><th>Item</th><th>Lowest price</th><th>Market price</th><th>For sale</th><th>Vendor</th></tr>
<tr><td><a href="/en/items/2589-linen">Linen Cloth</a> (Cloth)</td><td>55</td><td>65</td><td>950</td><td>—</td></tr>
<tr><td><a href="/en/items/1000-shot">Crafted Shot</a> (Projectile, level 5)</td><td>1</td><td>1</td><td>228301</td><td>—</td></tr></table>"""


class MultiSourceTest(unittest.TestCase):
    def test_several_files_are_merged_without_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d, "a.html"), Path(d, "b.html")
            a.write_text(PAGE1, encoding="utf-8")
            b.write_text(PAGE2, encoding="utf-8")
            c = websource.WebClient({"web_source_file": f"{a};\n{b}"}).load()
            ids = sorted(r["item_id"] for r in c.rows)
            self.assertEqual(ids, [1000, 2320, 2589])
            self.assertEqual(next(r for r in c.rows if r["item_id"] == 2589)["min"], 55)      # позже загруженная победила

    def test_one_bad_source_is_error_naming_it(self):
        with tempfile.TemporaryDirectory() as d:
            a = Path(d, "a.html")
            a.write_text(PAGE1, encoding="utf-8")
            with self.assertRaises(WebSourceError) as cm:
                websource.WebClient({"web_source_file": f"{a};{d}/missing.html"}).load()
            self.assertIn("missing.html", str(cm.exception))

    def test_site_category_is_kept_for_catalog(self):
        c = websource.WebClient({"web_source_file": "x"})
        c.rows = websource.parse_html(PAGE2)
        self.assertEqual(c.fetch_item(1000)["site_category"], "Projectile")


class JsonFallbackTest(unittest.TestCase):
    def page(self, data, wrap="__NEXT_DATA__"):
        return f'<html><script id="{wrap}" type="application/json">{json.dumps(data)}</script></html>'

    def test_items_found_in_embedded_json(self):
        data = {"props": {"pageProps": {"rows": [
            {"itemId": 2320, "name": "Coarse Thread", "category": "Cloth", "minBuyout": 1200, "marketValue": 1500, "quantity": 2310, "vendorPrice": 8},
            {"itemId": 2589, "name": "Linen Cloth", "category": "Cloth", "minBuyout": 50, "marketValue": 60, "quantity": 900},
        ]}}}
        rows = websource.parse_html(self.page(data))
        self.assertEqual([(r["item_id"], r["min"], r["market"], r["qty"], r["vendor"], r["category"]) for r in rows],
                         [(2320, 1200, 1500, 2310, 8, "Cloth"), (2589, 50, 60, 900, None, "Cloth")])

    def test_gold_unit_applies_to_json_numbers(self):
        data = {"rows": [{"id": 1, "name": "A", "price": 1.5, "quantity": 3}, {"id": 2, "name": "B", "price": 2, "quantity": 4}]}
        self.assertEqual(websource.parse_html(self.page(data), unit="gold")[0]["min"], 15000)

    def test_unrelated_json_is_ignored(self):
        with self.assertRaises(WebSourceError):
            websource.parse_html(self.page({"menu": [{"id": 1, "title": "Home"}]}))


class PipelineCatalogTest(unittest.TestCase):
    def run_web(self, pages, **cfg_extra):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        h = Path(d.name)
        files = []
        for i, p in enumerate(pages):
            f = h / f"p{i}.html"
            f.write_text(p, encoding="utf-8")
            files.append(str(f))
        cfg = {**appdata.DEFAULT_CFG, "source": "web", "web_source_file": ";".join(files), "wowhead_check": False, **cfg_extra}
        return runner.run_search(h, cfg)

    def test_catalog_has_all_scanned_items_with_site_categories(self):
        res, _, _, items = self.run_web([PAGE1, PAGE2])
        by = {r["item_id"]: r for r in res.catalog}
        self.assertEqual(set(by), {1000, 2320, 2589})
        self.assertEqual(by[1000]["category"], "Projectile")          # не торговый класс, но в общем списке есть
        self.assertEqual(by[2320]["vendor"], "да")
        self.assertEqual(by[2320]["vendor_price"], 8)

    def test_category_tabs_sorted_by_size_with_all_first(self):
        res, *_ = self.run_web([PAGE1, PAGE2])
        cats = vm.catalog_categories(res)
        self.assertEqual(cats[0], ("Все", 3))
        self.assertEqual(dict(cats[1:]), {"Cloth": 2, "Projectile": 1})
        self.assertEqual(len(vm.catalog_table(res, "Cloth")), 2)
        self.assertEqual(len(vm.catalog_table(res, None)), 3)
        for ids, vals in vm.catalog_table(res, None):
            self.assertEqual(len(vals), len(vm.CATALOG_COLS))

    def test_possible_vendor_tab_lists_unconfirmed_hints(self):
        from forever_deals import pipeline
        r = pipeline.Result()
        r.catalog = [
            dict(item_id=1, name="Да", category="A", min=10, market=10, qty=1, rate=None, vendor="да", vendor_price=5, note=""),
            dict(item_id=2, name="Обмен", category="A", min=10, market=10, qty=1, rate=None, vendor="возможно", vendor_price=None, note="за обмен на валюту"),
            dict(item_id=3, name="API", category="B", min=10, market=10, qty=1, rate=None, vendor="возможно", vendor_price=None, note="API: цена у NPC 4м"),
            dict(item_id=4, name="Нет", category="B", min=10, market=10, qty=1, rate=None, vendor="нет", vendor_price=None, note=""),
        ]
        self.assertEqual([ids[0] for ids, _ in vm.possible_table(r)], [2, 3])
        for ids, vals in vm.possible_table(r):
            self.assertEqual(len(vals), len(vm.POSSIBLE_COLS))


if __name__ == "__main__":
    unittest.main()
