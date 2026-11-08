import tempfile
import unittest
from pathlib import Path

from forever_deals import websource
from forever_deals.websource import WebSourceError

HTML = """<html><body><table>
<thead><tr><th>Item▼</th><th>Lowest price▼</th><th>Market price▼</th><th>Average▼</th><th>For sale▼</th><th>Vendor▼</th></tr></thead>
<tbody>
<tr><td><a href="/en/items/2320-coarse-thread">Coarse Thread</a> <small>(Cloth, level 5)</small></td><td>1,200</td><td>1,500</td><td>1,450</td><td>2,310</td><td>8</td></tr>
<tr><td><a href="/en/items/8067-crafted-light-shot">Crafted Light Shot</a> (Projectile, level 5)</td><td>1</td><td>1</td><td>1</td><td>228,301</td><td>—</td></tr>
<tr><td><a href="/en/items/4306-silk-cloth">Silk Cloth</a> (Cloth)</td><td>3000</td><td>3200</td><td>3100</td><td>n/a</td><td>—</td></tr>
</tbody></table></body></html>"""


class ParseTest(unittest.TestCase):
    def test_rows_with_ids_prices_and_quantities(self):
        rows = websource.parse_html(HTML)
        self.assertEqual(len(rows), 2)                       # строка без количества пропущена
        r = rows[0]
        self.assertEqual((r["item_id"], r["name"], r["category"], r["level"]), (2320, "Coarse Thread", "Cloth", 5))
        self.assertEqual((r["min"], r["market"], r["qty"], r["vendor"]), (1200, 1500, 2310, 8))
        self.assertIsNone(rows[1]["vendor"])

    def test_russian_headers_and_gold_text(self):
        html = ("<table><tr><th>Предмет</th><th>Мин. цена</th><th>Рыночная цена</th><th>Количество</th></tr>"
                '<tr><td><a href="/item=2589">Льняная ткань</a></td><td>1з 20с</td><td>1з 50с 5м</td><td>40</td></tr></table>')
        r = websource.parse_html(html)[0]
        self.assertEqual((r["item_id"], r["min"], r["market"], r["qty"]), (2589, 12000, 15005, 40))

    def test_plain_numbers_are_copper_unless_gold_unit(self):
        html = ('<table><tr><th>Item</th><th>Lowest</th><th>Qty</th></tr>'
                '<tr><td><a href="/item=1">A</a></td><td>12.5</td><td>3</td></tr></table>')
        self.assertEqual(websource.parse_html(html, unit="gold")[0]["min"], 125000)
        self.assertEqual(websource.parse_html(html.replace("12.5", "125"))[0]["min"], 125)

    def test_no_table_is_clear_error(self):
        for html in ("", "<html><body>loading…</body></html>", "<table><tr><th>X</th></tr></table>"):
            with self.assertRaises(WebSourceError):
                websource.parse_html(html)

    def test_error_reports_what_was_on_the_page(self):
        with self.assertRaises(WebSourceError) as cm:
            websource.parse_html('<html><script src="a.js"></script><a href="/items/5-x">x</a></html>')
        self.assertIn("таблиц: 0", str(cm.exception))
        self.assertIn("скриптов: 1", str(cm.exception))
        self.assertIn("ссылок на предметы: 1", str(cm.exception))

    def test_rows_without_item_id_are_skipped(self):
        html = ("<table><tr><th>Item</th><th>Lowest</th><th>Qty</th></tr>"
                "<tr><td>Нет ссылки</td><td>5</td><td>3</td></tr></table>")
        with self.assertRaises(WebSourceError):
            websource.parse_html(html)


class ClientTest(unittest.TestCase):
    def client(self, **cfg):
        c = websource.WebClient({"web_source_file": "x", **cfg})
        c.rows = websource.parse_html(HTML)
        return c

    def test_listings_use_market_price_as_typical(self):
        self.assertEqual(self.client().auction_listings()[2320], [(1500, 2310)])

    def test_fetch_item_maps_category_to_class(self):
        info = self.client().fetch_item(2320)
        self.assertEqual((info["class_id"], info["subclass_id"], info["purchase_price"], info["sell_price"]), (7, 5, 8, 0))
        self.assertEqual(self.client().fetch_item(8067)["class_id"], None)

    def test_vendor_items_from_vendor_column(self):
        v = self.client().vendor_items()
        self.assertEqual(list(v), [2320])
        self.assertEqual((v[2320].price, v[2320].vendor), (8, "по данным сайта"))

    def test_loads_saved_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "page.html"
            p.write_text(HTML, encoding="utf-8")
            c = websource.WebClient({"web_source_file": str(p)})
            c.load()
            self.assertEqual(len(c.rows), 2)

    def test_load_by_url_uses_user_agent_and_reports_errors(self):
        seen = []

        class R:
            def read(s): return HTML.encode()
            def __enter__(s): return s
            def __exit__(s, *a): return False

        def op(req, timeout=0):
            seen.append(req)
            return R()
        c = websource.WebClient({"web_source_url": "https://example.test/p"}, opener=op)
        c.load()
        self.assertIn("ForeverDeals", seen[0].get_header("User-agent"))

        def boom(req, timeout=0): raise OSError("net")
        with self.assertRaises(WebSourceError):
            websource.WebClient({"web_source_url": "https://example.test/p"}, opener=boom).load()

    def test_requires_url_or_file(self):
        with self.assertRaises(WebSourceError):
            websource.WebClient({}).load()

    def test_exactly_50_rows_warns_about_partial_table(self):
        rows = [dict(item_id=i, name="n", category="Cloth", level=None, min=1, market=1, avg=1, qty=5, vendor=None) for i in range(50)]
        c = websource.WebClient({"web_source_file": "x"})
        c.rows = rows
        self.assertTrue(any("50" in w for w in c.warnings()))


if __name__ == "__main__":
    unittest.main()


class RunnerTest(unittest.TestCase):
    def test_run_without_api_uses_page_and_vendor_column(self):
        from forever_deals import appdata, runner
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            page = h / "page.html"
            page.write_text(HTML, encoding="utf-8")
            cfg = {**appdata.DEFAULT_CFG, "source": "web", "web_source_file": str(page), "wowhead_check": False}
            res, md, path, items = runner.run_search(h, cfg)
            self.assertIn(2320, items)                                    # вендорная позиция создана из столбца Vendor
            self.assertTrue(any(e.cand.item_id == 2320 for e in res.vendor_rows))
            self.assertTrue(path.exists())
            self.assertTrue(any("Таблица цен" in s[0] for s in res.sources))

    def test_blizzard_not_required_but_table_is(self):
        from forever_deals import appdata, runner
        with tempfile.TemporaryDirectory() as d:
            cfg = {**appdata.DEFAULT_CFG, "source": "web", "web_source_file": str(Path(d) / "missing.html")}
            with self.assertRaises(WebSourceError):
                runner.run_search(Path(d), cfg)

    def test_user_vendor_list_wins_over_site_column(self):
        from forever_deals import appdata, runner, vendors
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            (h / "page.html").write_text(HTML, encoding="utf-8")
            vendors.save(h / "vendors.json", {2320: vendors.VendorItem(2320, 5, "Мой вендор")})
            cfg = {**appdata.DEFAULT_CFG, "source": "web", "web_source_file": str(h / "page.html"), "wowhead_check": False}
            _, _, _, items = runner.run_search(h, cfg)
            self.assertEqual((items[2320].price, items[2320].vendor), (5, "Мой вендор"))


class ConfiguredTest(unittest.TestCase):
    def test_web_source_needs_url_or_file_not_keys(self):
        from forever_deals import appdata
        self.assertFalse(appdata.configured({"source": "web"}))
        self.assertTrue(appdata.configured({"source": "web", "web_source_url": "https://x/p"}))
        self.assertTrue(appdata.configured({"source": "web", "web_source_file": "C:/p.html"}))
        self.assertFalse(appdata.configured({"source": "blizzard"}))


class HeaderTest(unittest.TestCase):
    def test_all_user_agents_are_latin1_encodable(self):
        """HTTP-заголовки кодируются в latin-1: кириллица в User-Agent роняла запрос на Windows."""
        from forever_deals import updater, selfupdate, wowhead
        for ua in (websource.UA, wowhead.UA):
            ua.encode("latin-1")
        seen = []

        class R:
            def read(s): return HTML.encode()
            def __enter__(s): return s
            def __exit__(s, *a): return False
        websource.WebClient({"web_source_url": "https://x/p"}, opener=lambda req, timeout=0: (seen.append(req), R())[1]).load()
        for k, v in seen[0].header_items():
            f"{k}: {v}".encode("latin-1")

    def test_wowhead_request_headers_are_latin1(self):
        from forever_deals import wowhead
        from forever_deals.store import Store
        seen = []

        class R:
            def read(s): return b"x"
            def __enter__(s): return s
            def __exit__(s, *a): return False
        wowhead.Checker(Store(":memory:"), "https://x", opener=lambda req, timeout=0: (seen.append(req), R())[1],
                        sleep=lambda s: None).check(1)
        for k, v in seen[0].header_items():
            f"{k}: {v}".encode("latin-1")


class LooseHeaderTest(unittest.TestCase):
    ROW = '<tr><td><a href="/forever/item/2320">Coarse Thread</a></td><td>12</td><td>2310</td></tr>'

    def test_header_in_second_row(self):
        html = ('<table><tr><td colspan="3">Prices — EU Alliance</td></tr>'
                '<tr><th>Item</th><th>Price</th><th>Available</th></tr>' + self.ROW + self.ROW.replace("2320", "2589") + '</table>')
        rows = websource.parse_html(html)
        self.assertEqual([(r["item_id"], r["min"], r["qty"]) for r in rows], [(2320, 12, 2310), (2589, 12, 2310)])

    def test_header_in_separate_table(self):
        html = ('<table><thead><tr><th>Item</th><th>Price</th><th>Listed</th></tr></thead></table>'
                '<table>' + self.ROW + '</table>')
        self.assertEqual(websource.parse_html(html)[0]["qty"], 2310)

    def test_more_header_synonyms(self):
        for price, qty in (("Min Buyout", "Qty"), ("Floor", "Supply"), ("Cost", "Units"), ("Цена", "Предложение")):
            html = f'<table><tr><th>Item</th><th>{price}</th><th>{qty}</th></tr>{self.ROW}</table>'
            self.assertEqual(websource.parse_html(html)[0]["item_id"], 2320, (price, qty))

    def test_error_lists_headers_and_link_context(self):
        html = ('<html><table><tr><th>Foo</th><th>Bar</th></tr><tr><td><a href="/forever/item/7">Thing</a></td><td>1</td></tr></table></html>')
        with self.assertRaises(WebSourceError) as cm:
            websource.parse_html(html)
        msg = str(cm.exception)
        self.assertIn("Foo | Bar", msg)
        self.assertIn("/forever/item/7", msg)

    def test_failed_page_is_saved_for_analysis(self):
        with tempfile.TemporaryDirectory() as d:
            c = websource.WebClient({"web_source_file": str(Path(d, "p.html")), "debug_dir": d})
            Path(d, "p.html").write_text("<html>no table</html>", encoding="utf-8")
            with self.assertRaises(WebSourceError) as cm:
                c.load()
            saved = Path(d, "last_page.html")
            self.assertTrue(saved.exists())
            self.assertIn("no table", saved.read_text(encoding="utf-8"))
            self.assertIn("last_page.html", str(cm.exception))
