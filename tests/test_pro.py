"""Приёмы профессионалов: аномальный минимум, волатильность и риск, срок продажи, снайпер."""
import unittest

from forever_deals import analytics, viewmodel as vm
from forever_deals.core import Settings, evaluate, rank, snipe_opportunity, volatility
from tests.test_core import cand
from tests.test_fixes import run_demo


class VolatilityTest(unittest.TestCase):
    def test_needs_three_days(self):
        self.assertIsNone(volatility([100, 120]))

    def test_flat_prices_zero(self):
        self.assertEqual(volatility([100, 100, 100]), 0.0)

    def test_spread_relative_to_median(self):
        v = volatility([50, 100, 150])
        self.assertAlmostEqual(v, 0.4082, places=3)   # pstdev 40.82 / медиана 100

    def test_ignores_missing(self):
        self.assertIsNone(volatility([None, 100, None]))


class RiskTest(unittest.TestCase):
    def test_levels(self):
        s = Settings()
        self.assertEqual(evaluate(cand(volatility=0.05), s).risk, "низкий")
        self.assertEqual(evaluate(cand(volatility=0.2), s).risk, "средний")
        self.assertEqual(evaluate(cand(volatility=0.5), s).risk, "высокий")

    def test_unknown_without_history(self):
        self.assertEqual(evaluate(cand(volatility=None), Settings()).risk, "")

    def test_high_risk_lowers_profit_per_day_and_flags(self):
        s = Settings()
        calm = evaluate(cand(volatility=0.05), s)
        wild = evaluate(cand(volatility=0.5), s)
        self.assertAlmostEqual(wild.epd, calm.epd * (1 - s.risk_penalty))
        self.assertTrue(any("нестабильн" in f for f in wild.flags))

    def test_rank_prefers_stable_when_close(self):
        s = Settings()
        a = cand(item_id=1, volatility=0.5)
        b = cand(item_id=2, volatility=0.05)
        ok, _ = rank([a, b], s)
        self.assertEqual([e.cand.item_id for e in ok], [2, 1])


class AnomalyTest(unittest.TestCase):
    def test_minimum_far_below_usual_is_flagged(self):
        e = evaluate(cand(min_price=1000, usual_price=1500), Settings(snipe_pct=0.30))
        self.assertAlmostEqual(e.discount, 1 / 3, places=3)
        self.assertTrue(any("ниже обычной" in f for f in e.flags))

    def test_small_dip_not_flagged(self):
        e = evaluate(cand(min_price=1400, usual_price=1500), Settings(snipe_pct=0.30))
        self.assertFalse(any("ниже обычной" in f for f in e.flags))

    def test_no_usual_price_zero_discount(self):
        e = evaluate(cand(usual_price=None), Settings())
        self.assertEqual(e.discount, 0.0)


class SellDaysTest(unittest.TestCase):
    def test_days_to_sell_our_batch(self):
        s = Settings(share=0.5, sales_haircut=0.7, budget_item=10**9)
        e = evaluate(cand(sales_per_day=40.0), s)
        # rate_used 28, наша доля 14/день, берём ceil(14*1)=14 шт. -> 1 день
        self.assertAlmostEqual(e.sell_days, e.qty / (e.rate_used * s.share))

    def test_none_without_rate(self):
        e = evaluate(cand(sales_per_day=0.0), Settings(min_rate=0))
        self.assertIsNone(e.sell_days)


class SnipeTest(unittest.TestCase):
    def test_only_lots_below_threshold(self):
        r = snipe_opportunity([(500, 3), (900, 5), (1400, 4)], usual=1500, cut=0.05, snipe_pct=0.30, min_net=50, budget=10**9)
        self.assertEqual(r.units, 8)                       # 1400 выше порога 1050
        self.assertEqual(r.cost, 500 * 3 + 900 * 5)
        self.assertEqual(r.best, 500)
        self.assertAlmostEqual(r.discount, 1 - 500 / 1500)
        self.assertGreater(r.profit, 0)

    def test_nothing_when_no_discount(self):
        r = snipe_opportunity([(1450, 5)], usual=1500, cut=0.05, snipe_pct=0.30, min_net=50, budget=10**9)
        self.assertEqual(r.units, 0)
        self.assertEqual(r.profit, 0)

    def test_budget_limits_units(self):
        r = snipe_opportunity([(500, 10)], usual=1500, cut=0.05, snipe_pct=0.30, min_net=50, budget=1500)
        self.assertEqual(r.units, 3)

    def test_not_profitable_after_cut(self):
        r = snipe_opportunity([(1040, 5)], usual=1500, cut=0.5, snipe_pct=0.30, min_net=50, budget=10**9)
        self.assertEqual(r.units, 0)


class PipelineProTest(unittest.TestCase):
    def test_pipeline_fills_snipe_rows_sorted_by_profit(self):
        res, s = run_demo()
        rows = analytics.snipe_rows(res, s)
        self.assertEqual(rows, sorted(rows, key=lambda r: (-r["profit"], r["item_id"])))
        for r in rows:
            self.assertGreater(r["units"], 0)
            self.assertGreaterEqual(r["discount"], s.snipe_pct)

    def test_tables_have_matching_widths(self):
        self.assertEqual(len(vm.SNIPE_COLS), len(vm.SNIPE_WIDTHS))
        res, s = run_demo()
        for _, row in vm.snipe_table(res, s):
            self.assertEqual(len(row), len(vm.SNIPE_COLS))

    def test_top_has_risk_and_sell_days_columns(self):
        self.assertIn("Риск", vm.TOP_COLS)
        self.assertIn("Дней на продажу", vm.TOP_COLS)
        self.assertEqual(len(vm.TOP_COLS), len(vm.TOP_WIDTHS))
        res, _ = run_demo()
        for _, row in vm.top_rows(res, {}):
            self.assertEqual(len(row), len(vm.TOP_COLS))


if __name__ == "__main__":
    unittest.main()
