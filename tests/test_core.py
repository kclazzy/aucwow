import unittest
from forever_deals.core import (Settings, Candidate, evaluate, rank, fmt_money,
                                aggregate_listings, estimate_sales_per_day, usual_price)

DAY = 86400


def cand(**kw):
    base = dict(item_id=1, name="Грубая нить", group="vendor", category="NPC",
                buy_price=8, buy_source="vendor", min_price=1500, market_price=1500,
                vendor_sell=2, quantity=300, n_auctions=20, sales_per_day=40.0,
                history_days=5, usual_price=1500)
    base.update(kw)
    return Candidate(**base)


class MoneyTest(unittest.TestCase):
    def test_format(self):
        self.assertEqual(fmt_money(12345), "1з 23с 45м")
        self.assertEqual(fmt_money(8), "8м")
        self.assertEqual(fmt_money(150), "1с 50м")


class EvaluateTest(unittest.TestCase):
    def test_video_example_net(self):
        s = Settings(cut=0.05, deposit_pct=0.05, deposit_hours=12, p_sell=0.7, share=0.5)
        e = evaluate(cand(), s)
        # 1500*0.95 - 8 - 0.05*2*0.3 = 1416.97 -> int
        self.assertEqual(e.net, 1416)
        self.assertAlmostEqual(e.markup, 1500 / 8)
        self.assertEqual(e.epd, 40 * 0.5 * 1416)
        self.assertEqual(e.rejects, [])

    def test_sell_price_is_conservative(self):
        e = evaluate(cand(min_price=2000, usual_price=1000), Settings())
        self.assertEqual(e.sell_price, 1000)

    def test_rejects_low_profit_with_reason(self):
        e = evaluate(cand(min_price=10, usual_price=10, market_price=10), Settings())
        self.assertTrue(any("мала прибыль" in r for r in e.rejects))

    def test_rejects_thin_market(self):
        e = evaluate(cand(sales_per_day=1.0), Settings(min_rate=3))
        self.assertTrue(any("тонкий рынок" in r for r in e.rejects))

    def test_unknown_sales_flagged_not_rejected(self):
        e = evaluate(cand(sales_per_day=None, history_days=0, usual_price=None), Settings())
        self.assertEqual(e.rejects, [])
        self.assertIn("нет истории продаж", e.flags)

    def test_no_listings_rejected(self):
        e = evaluate(cand(min_price=None, quantity=0), Settings())
        self.assertTrue(any("нет лотов" in r for r in e.rejects))

    def test_quantity_limited_by_budget_and_stock(self):
        e = evaluate(cand(stock=5), Settings(budget_item=1000))
        self.assertEqual(e.qty, 5)
        e = evaluate(cand(), Settings(budget_item=80, horizon_days=1))
        self.assertEqual(e.qty, 10)


class RankTest(unittest.TestCase):
    def test_order_by_epd_then_roi_then_id(self):
        a = cand(item_id=3, sales_per_day=10, min_price=1000, usual_price=1000)
        b = cand(item_id=2, sales_per_day=40, min_price=1500, usual_price=1500)
        c = cand(item_id=1, sales_per_day=40, min_price=1500, usual_price=1500)
        ranked, rejected = rank([a, b, c], Settings())
        self.assertEqual([r.cand.item_id for r in ranked], [1, 2, 3])
        self.assertEqual(rejected, [])

    def test_input_order_irrelevant(self):
        cs = [cand(item_id=i, sales_per_day=5 + i) for i in range(1, 6)]
        r1, _ = rank(cs, Settings())
        r2, _ = rank(list(reversed(cs)), Settings())
        self.assertEqual([x.cand.item_id for x in r1], [x.cand.item_id for x in r2])

    def test_rejected_listed_with_reasons(self):
        ranked, rejected = rank([cand(item_id=9, min_price=None, quantity=0)], Settings())
        self.assertEqual(ranked, [])
        self.assertEqual(rejected[0].cand.item_id, 9)


class AggregateTest(unittest.TestCase):
    def test_min_qty_market(self):
        listings = [(100, 10), (200, 10), (300, 80)]  # (unit_price, qty)
        a = aggregate_listings(listings)
        self.assertEqual(a.min_price, 100)
        self.assertEqual(a.quantity, 100)
        self.assertEqual(a.n_auctions, 3)
        # cheapest 15% of 100 units = 15 units: 10@100 + 5@200 -> 133
        self.assertEqual(a.market_price, 133)

    def test_ignores_bad_rows(self):
        a = aggregate_listings([(0, 5), (100, 0), (50, 2)])
        self.assertEqual(a.min_price, 50)
        self.assertEqual(a.quantity, 2)


class SalesEstimateTest(unittest.TestCase):
    def test_sum_of_drops(self):
        snaps = [(0, 100), (DAY // 2, 80), (DAY, 90), (2 * DAY, 60)]
        rate, days = estimate_sales_per_day(snaps)
        self.assertEqual(days, 2.0)
        self.assertAlmostEqual(rate, (20 + 30) / 2.0)

    def test_too_short_span(self):
        self.assertEqual(estimate_sales_per_day([(0, 10), (60, 5)])[0], None)

    def test_usual_price_median_needs_days(self):
        self.assertIsNone(usual_price([100, 120], min_days=3))
        self.assertEqual(usual_price([100, 300, 120], min_days=3), 120)


class ParseMoneyTest(unittest.TestCase):
    def test_forms(self):
        from forever_deals.core import parse_money
        self.assertEqual(parse_money("1з 25с 3м"), 12503)
        self.assertEqual(parse_money("1g 2s 3c"), 10203)
        self.assertEqual(parse_money("85"), 85)
        self.assertEqual(parse_money("50с"), 5000)
        with self.assertRaises(ValueError):
            parse_money("много")


if __name__ == "__main__":
    unittest.main()
