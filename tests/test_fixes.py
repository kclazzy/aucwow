"""Тесты на исправления по замечаниям. Написаны до правок."""
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

from forever_deals import appdata, demo, pipeline, report, vendors
from forever_deals.blizzard import ApiError, Client
from forever_deals.core import Candidate, Settings, evaluate, aggregate_listings
from forever_deals.store import Store
from tests.test_core import cand

NOW = 1_800_000_000


class OutlierTest(unittest.TestCase):
    def test_isolated_overpriced_lot_is_rejected(self):          # п.1
        e = evaluate(cand(min_price=200000, market_price=200000, usual_price=None, sales_per_day=None,
                          history_days=0, quantity=1, n_auctions=1), Settings())
        self.assertTrue(any("изолирован" in r for r in e.rejects), e.rejects)

    def test_one_big_lot_is_fine(self):
        e = evaluate(cand(quantity=300, n_auctions=1), Settings())
        self.assertEqual(e.rejects, [])

    def test_thin_bottom_flagged_using_market_price(self):       # п.6
        e = evaluate(cand(min_price=1000, market_price=3000, usual_price=None), Settings())
        self.assertTrue(any("рыночн" in f for f in e.flags), e.flags)
        e2 = evaluate(cand(min_price=1000, market_price=1100, usual_price=None), Settings())
        self.assertFalse(any("рыночн" in f for f in e2.flags))


class MaterialTest(unittest.TestCase):
    def mat(self, **kw):
        base = dict(group="material", category="Руда и камень", buy_source="opportunity", buy_price=100,
                    vendor_sell=100, min_price=300, market_price=300, usual_price=300)
        base.update(kw)
        return cand(**base)

    def test_no_vendor_price_rejected(self):                    # п.3
        e = evaluate(self.mat(vendor_sell=0, buy_price=1), Settings())
        self.assertTrue(any("цены вендору" in r for r in e.rejects), e.rejects)

    def test_roi_gate_only_for_real_purchases(self):            # п.7
        s = Settings()
        m = evaluate(self.mat(min_price=200, usual_price=200), s)          # net 90, ROI 0.9
        self.assertEqual(m.rejects, [])
        v = evaluate(cand(buy_price=100, min_price=200, usual_price=200, vendor_sell=1), Settings(min_markup=1))
        self.assertTrue(any("ROI" in r for r in v.rejects))

    def test_sales_haircut_applied_to_estimates(self):          # п.2
        s = Settings(sales_haircut=0.5)
        e = evaluate(cand(sales_per_day=40.0), s)
        self.assertEqual(e.rate_used, 20.0)


class HouseCutTest(unittest.TestCase):
    def test_cut_overridden_per_house(self):                    # п.5
        cfg = {"auction_house_id": "7", "house_cuts": {"7": 0.15}}
        self.assertEqual(appdata.load_settings(cfg).cut, 0.15)
        cfg2 = {"auction_house_id": "8", "house_cuts": {"7": 0.15}}
        self.assertEqual(appdata.load_settings(cfg2).cut, 0.05)

    def test_save_cut_for_house(self):
        cfg = {"auction_house_id": "7"}
        appdata.set_house_cut(cfg, 0.15)
        self.assertEqual(cfg["house_cuts"], {"7": 0.15})


class SnapshotTest(unittest.TestCase):
    def aggs(self, qty):
        return {1: aggregate_listings([(100, qty)])}

    def test_identical_snapshot_not_duplicated(self):           # п.11
        st = Store(":memory:")
        self.assertTrue(st.add_snapshot(1000, self.aggs(10)))
        self.assertFalse(st.add_snapshot(2000, self.aggs(10)))
        self.assertTrue(st.add_snapshot(3000, self.aggs(8)))
        self.assertEqual(len(st.qty_series(1, 0)), 2)


class RetryScheduleTest(unittest.TestCase):
    def test_failed_run_backs_off(self):                        # п.4
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            cfg = {"run_time": "20:00", "retry_minutes": 30}
            t = datetime(2026, 11, 8, 20, 5)
            self.assertTrue(appdata.is_due(cfg, h, t))
            appdata.mark_fail(h, t, "нет связи")
            self.assertFalse(appdata.is_due(cfg, h, t + timedelta(minutes=10)))
            self.assertTrue(appdata.is_due(cfg, h, t + timedelta(minutes=31)))
            self.assertEqual(appdata.last_error(h), "нет связи")
            appdata.mark_run(h, t + timedelta(minutes=32))
            self.assertIsNone(appdata.last_error(h))

    def test_prune_reports(self):                               # п.14
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            (h / "reports").mkdir()
            for i in range(5):
                (h / "reports" / f"2026-11-0{i + 1}.md").write_text("x")
            appdata.prune_reports(h, keep=2)
            self.assertEqual(sorted(p.name for p in (h / "reports").iterdir()), ["2026-11-04.md", "2026-11-05.md"])

    def test_secret_from_env_and_file_mode(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            appdata.save_cfg(h, dict(appdata.DEFAULT_CFG, client_secret="s"))
            if os.name == "posix":
                self.assertEqual((h / "config.json").stat().st_mode & 0o777, 0o600)
            os.environ["FD_CLIENT_SECRET"] = "from-env"
            try:
                self.assertEqual(appdata.load_cfg(h)["client_secret"], "from-env")
            finally:
                del os.environ["FD_CLIENT_SECRET"]


def http_error(code):
    return urllib.error.HTTPError("https://x/y", code, "err", {}, io.BytesIO(b""))


class FakeResp:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class RetryApiTest(unittest.TestCase):
    cfg = {"region": "eu", "client_id": "a", "client_secret": "b", "dynamic_namespace": "d", "static_namespace": "s",
           "connected_realm_id": 1, "auction_house_id": 2,
           "auction_path": "/data/wow/connected-realm/{realm}/auctions/{house}", "item_path": "/data/wow/item/{id}"}

    def client(self, script):
        calls = []

        def opener(req, timeout=0):
            calls.append(req.full_url)
            step = script.pop(0)
            if isinstance(step, Exception):
                raise step
            return FakeResp(step)
        sleeps = []
        c = Client(dict(self.cfg), opener=opener, sleep=sleeps.append)
        c._token, c._token_until = "t", 10**12
        return c, calls, sleeps

    def test_retries_429_then_succeeds(self):                   # п.9
        c, calls, sleeps = self.client([http_error(429), http_error(503), {"ok": 1}])
        self.assertEqual(c.get("/x", "ns"), {"ok": 1})
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(sleeps), 2)

    def test_gives_up_after_limit(self):
        c, calls, _ = self.client([http_error(429)] * 4)
        with self.assertRaises(ApiError):
            c.get("/x", "ns")
        self.assertEqual(len(calls), 4)

    def test_404_not_retried(self):
        c, calls, _ = self.client([http_error(404)])
        with self.assertRaises(ApiError):
            c.get("/x", "ns")
        self.assertEqual(len(calls), 1)

    def test_check_connection_reports_steps(self):              # п.16
        auctions = {"auctions": [{"item": {"id": 5}, "quantity": 2, "unit_price": 10}]}
        item = {"name": "Нить", "item_class": {"id": 7}, "item_subclass": {"id": 5}, "sell_price": 1}
        c, _, _ = self.client([auctions, item])
        steps = c.check()
        self.assertTrue(all(ok for ok, _ in steps), steps)
        c2, _, _ = self.client([http_error(404)])
        steps2 = c2.check()
        self.assertFalse(steps2[0][0])


class LookupPriorityTest(unittest.TestCase):
    class Cl:
        def __init__(self):
            self.asked = []

        def auction_listings(self):
            return {1: [(10, 500)], 2: [(90000, 2)], 3: [(50, 100)]}

        def fetch_item(self, i):
            self.asked.append(i)
            return dict(name=f"i{i}", class_id=9, subclass_id=0, purchase_price=0, sell_price=5)

        def sources(self):
            return []

    def test_expensive_items_looked_up_first(self):             # п.10
        cl = self.Cl()
        res = pipeline.run(cl, Store(":memory:"), {}, Settings(), {"max_item_lookups": 1}, now=NOW)
        self.assertEqual(cl.asked, [2])
        self.assertTrue(any("следующих запусках" in w for w in res.warnings))

    def test_cached_items_do_not_use_cap(self):
        st = Store(":memory:")
        for i in (1, 3):
            st.put_item(i, dict(name=f"i{i}", class_id=9, subclass_id=0, purchase_price=0, sell_price=5))
        cl = self.Cl()
        res = pipeline.run(cl, st, {}, Settings(), {"max_item_lookups": 1}, now=NOW)
        self.assertEqual(cl.asked, [2])
        self.assertEqual(res.meta["candidates"], 3)

    def test_unknown_class_ids_warn(self):                      # п.8
        cl = self.Cl()
        cl.fetch_item = lambda i: dict(name="x", class_id=99, subclass_id=1, purchase_price=0, sell_price=5)
        res = pipeline.run(cl, Store(":memory:"), {}, Settings(), {}, now=NOW)
        self.assertTrue(any("ID классов" in w for w in res.warnings))

    def test_class_ids_configurable(self):
        cl = self.Cl()
        cl.fetch_item = lambda i: dict(name="x", class_id=42, subclass_id=1, purchase_price=0, sell_price=5)
        res = pipeline.run(cl, Store(":memory:"), {}, Settings(), {"class_recipe": 42}, now=NOW)
        self.assertEqual(res.meta["candidates"], 3)


class VendorStockTest(unittest.TestCase):
    def test_purchase_decrements_stock(self):                   # п.13
        items = {1: vendors.VendorItem(1, 10, stock=5), 2: vendors.VendorItem(2, 10)}
        vendors.apply_purchase(items, 1, 3)
        self.assertEqual(items[1].stock, 2)
        vendors.apply_purchase(items, 1, 9)
        self.assertEqual(items[1].stock, 0)
        vendors.apply_purchase(items, 2, 4)
        self.assertIsNone(items[2].stock)

    def test_parse_pasted_lines_with_wowhead_urls(self):        # п.15
        text = ("https://www.wowhead.com/forever/item=2589 ; 8м ; Стефани ; https://www.wowhead.com/forever/npc=777 ; Штормград ; 5\n"
                "4306;1з 20с;Другой;;Дарнас\n"
                "мусор\n")
        items, errors = vendors.parse_text(text)
        self.assertEqual(items[2589].npc_id, 777)
        self.assertEqual(items[2589].price, 8)
        self.assertEqual(items[2589].stock, 5)
        self.assertEqual(items[4306].price, 12000)
        self.assertEqual(len(errors), 1)


class TradeJournalTest(unittest.TestCase):
    def test_summary(self):                                     # п.18
        st = Store(":memory:")
        st.add_trade(1, 7, "buy", 10, 100)
        st.add_trade(2, 7, "sell", 4, 400)
        st.add_trade(3, 8, "buy", 1, 50)
        summ = {r["item_id"]: r for r in st.trade_summary(cut=0.05)}
        self.assertEqual(summ[7]["bought"], 10)
        self.assertEqual(summ[7]["sold"], 4)
        self.assertEqual(summ[7]["realized"], int(4 * 400 * 0.95) - 4 * 100)   # 1520 - 400
        self.assertEqual(summ[7]["left"], 6)
        self.assertEqual(summ[8]["realized"], 0)


def run_demo():
    st = Store(":memory:")
    demo.seed_history(st, NOW - 600)
    s = Settings()
    res = pipeline.run(demo.DemoClient(), st, demo.VENDORS, s, {"connected_realm_id": 1, "auction_house_id": 2}, now=NOW)
    return res, s


class RouteAndHtmlTest(unittest.TestCase):
    def test_shopping_route_groups_by_vendor(self):             # п.17
        res, s = run_demo()
        route = report.shopping_route(res)
        self.assertTrue(route)
        for g in route:
            self.assertTrue(g["rows"])
            self.assertEqual(g["total"], sum(r["cost"] for r in g["rows"]))
            self.assertTrue(all(r["qty"] > 0 for r in g["rows"]))
        names = [g["vendor"] for g in route]
        self.assertEqual(len(names), len(set(names)))

    def test_html_report_has_tables_and_clickable_links(self):  # п.21
        res, s = run_demo()
        md = report.build_markdown(res, s, demo.VENDORS, demo=True)
        html = report.markdown_to_html(md)
        self.assertIn("<table>", html)
        self.assertIn('<a href="https://www.wowhead.com/forever/item=900001"', html)
        self.assertIn("<h2>", html)
        self.assertNotIn("| --- |", html)

    def test_markdown_has_epd_and_route_sections(self):         # п.19
        res, s = run_demo()
        md = report.build_markdown(res, s, demo.VENDORS, demo=True)
        self.assertIn("Прибыль/день", md)
        self.assertIn("## Маршрут закупки", md)
        self.assertIn("## Как читать", md)

    def test_demo_names_are_marked(self):                       # п.24
        res, _ = run_demo()
        self.assertTrue(all(e.cand.name.startswith("[демо]") for e in res.ranked + res.rejected))


if __name__ == "__main__":
    unittest.main()
