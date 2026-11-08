import tempfile
import unittest
from pathlib import Path

from forever_deals import appdata, demo, runner, viewmodel as vm
from tests.test_fixes import run_demo


class TablesTest(unittest.TestCase):
    def setUp(self):
        from forever_deals import crafting, pipeline
        from forever_deals.core import Settings
        from forever_deals.store import Store
        from tests.test_fixes import NOW
        st = Store(":memory:")
        demo.seed_history(st, NOW - 600)
        self.s = Settings()
        cfg = {"auction_house_id": "1", "compare_houses": [{"id": "2", "name": "Blackwater", "cut": 0.15}]}
        self.res = pipeline.run(demo.DemoClient(), st, demo.VENDORS, self.s, cfg, now=NOW,
                                recipes=crafting.parse_text(demo.RECIPES_TEXT)[0], de_rules=demo.DE_RULES)

    def check(self, rows, cols):
        self.assertTrue(rows)
        for ids, vals in rows:
            self.assertEqual(len(vals), len(cols))

    def test_top_has_list_price_and_stock_columns(self):
        rows = vm.top_rows(self.res, demo.VENDORS)
        self.check(rows, vm.TOP_COLS)
        self.assertIn("Выставлять по", vm.TOP_COLS)
        self.assertIn("Запас, дн.", vm.TOP_COLS)

    def test_shortage_table(self):
        self.check(vm.shortage_table(self.res), vm.SHORT_COLS)

    def test_reset_table(self):
        self.check(vm.reset_table(self.res, self.s), vm.RESET_COLS)

    def test_craft_table_shows_reagent_names_and_profit(self):
        rows = vm.craft_table(self.res)
        self.check(rows, vm.CRAFT_COLS)
        self.assertTrue(any("Медная руда" in vals[2] for _, vals in rows))

    def test_craft_unknown_prices_are_explained(self):
        from forever_deals import crafting
        recipes, _ = crafting.parse_text("900012;1;999999:1;Кузнечное дело;X")
        row = crafting.craft_profit(recipes[900012], {}, {}, {}, self.s)
        self.res.craft_rows = [row]
        vals = vm.craft_table(self.res)[0][1]
        self.assertIn("нет цены", vals[-1])
        self.assertEqual(vals[5], "—")

    def test_disenchant_table(self):
        self.check(vm.de_table(self.res), vm.DE_COLS)

    def test_arbitrage_table(self):
        self.res.arb_rows = [dict(item_id=1, name="Нить", buy_house="A", sell_house="B", buy=100, sell=300, net=170,
                                  roi=1.7, qty=10, profit=1700)]
        rows = vm.arb_table(self.res)
        self.check(rows, vm.ARB_COLS)
        self.assertEqual(rows[0][1][1], "A")


class HourlyRunTest(unittest.TestCase):
    def test_unmarked_run_does_not_count_as_todays_run(self):
        # ежечасная проверка не должна лишать вечерний запуск дайджеста
        import forever_deals.runner as r
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            (h / "reports").mkdir()
            cfg = dict(appdata.DEFAULT_CFG, demo=True)
            r.run_search(h, cfg, mark=False)
            self.assertIsNone(appdata.last_run(h))

    def test_failed_unmarked_run_does_not_delay_daily_run(self):
        import forever_deals.runner as r
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            (h / "reports").mkdir()
            with self.assertRaises(RuntimeError):
                r.run_search(h, dict(appdata.DEFAULT_CFG), mark=False)     # ключей нет
            self.assertIsNone(appdata.last_error(h))


if __name__ == "__main__":
    unittest.main()
