"""Запас в днях, цена выставления, сброс рынка, дефицит."""
import unittest

from forever_deals import analytics
from forever_deals.core import Settings, evaluate, reset_opportunity
from tests.test_core import cand
from tests.test_fixes import run_demo


class StockAndListPriceTest(unittest.TestCase):
    def test_stock_days(self):
        e = evaluate(cand(quantity=300, sales_per_day=40.0), Settings())
        self.assertAlmostEqual(e.stock_days, 7.5)

    def test_stock_days_unknown_without_sales(self):
        e = evaluate(cand(sales_per_day=None), Settings())
        self.assertIsNone(e.stock_days)
        e = evaluate(cand(sales_per_day=0.0), Settings())
        self.assertIsNone(e.stock_days)

    def test_list_price_undercuts_minimum(self):
        e = evaluate(cand(min_price=1500, usual_price=1500, buy_price=8), Settings(undercut=1))
        self.assertEqual(e.list_price, 1499)

    def test_list_price_never_below_floor(self):
        s = Settings(undercut=1, min_net=50, cut=0.05)
        c = cand(min_price=100, usual_price=100, buy_price=60, vendor_sell=0)
        e = evaluate(c, s)
        # пол: (60 + 0 + 50) / 0.95 = 115.8 -> 116, это выше минимальной цены 100
        self.assertEqual(e.list_price, 116)
        self.assertTrue(any("цена выставления" in f for f in e.flags))

    def test_list_price_zero_when_no_listings(self):
        e = evaluate(cand(min_price=None, quantity=0), Settings())
        self.assertEqual(e.list_price, 0)


class ResetTest(unittest.TestCase):
    def test_buys_cheap_tiers_until_unprofitable(self):
        r = reset_opportunity([(100, 5), (110, 5), (500, 3)], target=400, cut=0.05, min_net=50)
        self.assertEqual((r.units, r.cost), (10, 1050))
        self.assertEqual(r.revenue, 10 * 380)
        self.assertEqual(r.profit, 3800 - 1050)

    def test_budget_limits_units(self):
        r = reset_opportunity([(100, 5), (110, 5)], target=400, cut=0.05, min_net=50, budget=520)
        self.assertEqual(r.units, 5)           # 5*100=500, следующая единица 110 не влезает в остаток 20
        self.assertEqual(r.cost, 500)

    def test_nothing_when_all_tiers_unprofitable(self):
        r = reset_opportunity([(390, 5)], target=400, cut=0.05, min_net=50)
        self.assertEqual((r.units, r.profit), (0, 0))

    def test_unsorted_input_is_sorted(self):
        r = reset_opportunity([(110, 5), (100, 5)], target=400, cut=0.05, min_net=50, budget=500)
        self.assertEqual(r.cost, 500)


class ShortageAndResetRowsTest(unittest.TestCase):
    def test_shortage_sorted_by_days_of_stock(self):
        res, s = run_demo()
        rows = analytics.shortage_rows(res)
        days = [e.stock_days for e in rows]
        self.assertTrue(days)
        self.assertEqual(days, sorted(days))
        self.assertTrue(all(d is not None for d in days))

    def test_reset_rows_have_listings_and_positive_profit(self):
        res, s = run_demo()
        rows = analytics.reset_rows(res, s)
        for r in rows:
            self.assertGreater(r["units"], 0)
            self.assertGreater(r["profit"], 0)
        profits = [r["profit"] for r in rows]
        self.assertEqual(profits, sorted(profits, reverse=True))


if __name__ == "__main__":
    unittest.main()
