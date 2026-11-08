import unittest

from forever_deals import analytics, demo, pipeline, report
from forever_deals.core import Settings
from forever_deals.store import Store
from tests.test_core import cand
from tests.test_fixes import run_demo, NOW


class ProfessionTest(unittest.TestCase):
    def test_recipe_subclass_gives_profession(self):
        info = dict(class_id=9, subclass_id=4)
        self.assertEqual(pipeline.profession(info, {}), "Кузнечное дело")

    def test_material_subclass_gives_profession(self):
        self.assertEqual(pipeline.profession(dict(class_id=7, subclass_id=5), {}), "Портняжное дело")
        self.assertEqual(pipeline.profession(dict(class_id=7, subclass_id=9), {}), "Травничество")

    def test_unknown_goes_to_other(self):
        self.assertEqual(pipeline.profession(dict(class_id=15, subclass_id=0), {}), "Прочее")
        self.assertEqual(pipeline.profession({}, {}), "Прочее")

    def test_mapping_configurable(self):
        cfg = {"recipe_prof": {"4": "Кузница"}}
        self.assertEqual(pipeline.profession(dict(class_id=9, subclass_id=4), cfg), "Кузница")


class SummaryTest(unittest.TestCase):
    def evals(self):
        from forever_deals.core import evaluate
        s = Settings(sales_haircut=1.0)
        a = evaluate(cand(item_id=1, profession="Портняжное дело"), s)
        b = evaluate(cand(item_id=2, profession="Портняжное дело", min_price=10, usual_price=10), s)   # отклонён
        c = evaluate(cand(item_id=3, profession="Кулинария", group="material", buy_source="opportunity",
                          buy_price=100, vendor_sell=100, min_price=900, usual_price=900), s)
        return [a, b, c]

    def test_summary_numbers(self):
        a, b, c = self.evals()
        sm = analytics.summarize("Портняжное дело", [a, b])
        self.assertEqual((sm.total, sm.profitable, sm.rejected), (2, 1, 1))
        self.assertEqual(sm.epd_total, a.epd)
        self.assertEqual(sm.invest, a.qty * a.cand.buy_price)
        self.assertEqual([e.cand.item_id for e in sm.best], [1])

    def test_invest_counts_only_real_purchases(self):
        c = self.evals()[2]
        sm = analytics.summarize("Кулинария", [c])
        self.assertEqual(sm.invest, 0)
        self.assertGreater(sm.epd_total, 0)

    def test_empty_summary_is_safe(self):
        sm = analytics.summarize("Пусто", [])
        self.assertEqual((sm.total, sm.profitable, sm.epd_total, sm.avg_markup), (0, 0, 0, 0))

    def test_reason_key_strips_numbers(self):
        self.assertEqual(analytics.reason_key("мала прибыль (12м на шт.)"), "мала прибыль")
        self.assertEqual(analytics.reason_key("наценка ×4.0 меньше ×10"), "наценка ниже минимума")
        self.assertEqual(analytics.reason_key("тонкий рынок (1.0 шт/день)"), "тонкий рынок")
        self.assertEqual(analytics.reason_key("изолированный лот (1 шт.): цене не верим"), "изолированный лот")


class DemoAnalyticsTest(unittest.TestCase):
    def test_demo_candidates_have_professions(self):
        res, _ = run_demo()
        profs = {e.cand.profession for e in res.ranked + res.rejected}
        self.assertTrue({"Портняжное дело", "Кулинария", "Горное дело", "Травничество", "Кожевничество"} <= profs, profs)

    def test_by_profession_sorted_by_profit_and_complete(self):
        res, _ = run_demo()
        rows = analytics.by_profession(res)
        epds = [r.epd_total for r in rows]
        self.assertEqual(epds, sorted(epds, reverse=True))
        self.assertEqual(sum(r.total for r in rows), len(res.ranked) + len(res.rejected))
        self.assertEqual(len({r.name for r in rows}), len(rows))

    def test_overall_matches_sum_of_professions(self):
        res, _ = run_demo()
        total = analytics.overall(res)
        self.assertAlmostEqual(total.epd_total, sum(r.epd_total for r in analytics.by_profession(res)))
        self.assertEqual(total.profitable, len(res.ranked))

    def test_reason_histogram_counts_every_rejection(self):
        res, _ = run_demo()
        hist = analytics.reason_histogram(res)
        self.assertEqual(sum(n for _, n in hist), sum(len(e.rejects) for e in res.rejected))
        self.assertEqual([n for _, n in hist], sorted((n for _, n in hist), reverse=True))

    def test_report_has_profession_section(self):
        res, s = run_demo()
        md = report.build_markdown(res, s, demo.VENDORS, demo=True)
        self.assertIn("## Аналитика по профессиям", md)
        self.assertIn("| Портняжное дело |", md)


class BarsTest(unittest.TestCase):
    def test_bar_lengths_scale_to_max(self):
        from forever_deals import viewmodel as vm
        self.assertEqual(vm.bar_lengths([10, 5, 0], 100), [100, 50, 0])
        self.assertEqual(vm.bar_lengths([0, 0], 100), [0, 0])
        self.assertEqual(vm.bar_lengths([], 100), [])
        self.assertEqual(vm.bar_lengths([-5, 10], 100), [0, 100])      # отрицательное не рисуем


if __name__ == "__main__":
    unittest.main()
