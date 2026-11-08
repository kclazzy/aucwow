import unittest

from forever_deals import demo, viewmodel as vm
from tests.test_fixes import run_demo


class ViewModelTest(unittest.TestCase):
    def test_sort_key_orders_money_markup_and_text(self):
        vals = ["1з", "50с", "×12.5", "н/д", "3м", "12"]
        money = sorted(["1з", "50с", "3м"], key=vm.sort_key)
        self.assertEqual(money, ["3м", "50с", "1з"])
        self.assertLess(vm.sort_key("×2.0"), vm.sort_key("×12.5"))
        self.assertLess(vm.sort_key("н/д"), vm.sort_key("3м"))
        self.assertLess(vm.sort_key("9"), vm.sort_key("10"))
        self.assertLess(vm.sort_key("Ткань"), vm.sort_key("Трава"))

    def test_percent_roundtrip_and_validation(self):
        self.assertEqual(vm.to_percent(0.05), "5")
        self.assertAlmostEqual(vm.from_percent("15"), 0.15)
        self.assertAlmostEqual(vm.from_percent("7,5"), 0.075)
        for bad in ("-1", "101", "abc"):
            with self.assertRaises(ValueError):
                vm.from_percent(bad)

    def test_filter(self):
        rows = [("Грубая нить", "Ткань"), ("Мироцвет", "Трава")]
        self.assertEqual(vm.filter_rows(rows, "нить"), [rows[0]])
        self.assertEqual(vm.filter_rows(rows, ""), rows)

    def test_top_rows_include_epd_and_dash_roi_for_materials(self):
        res, _ = run_demo()
        rows = vm.top_rows(res, demo.VENDORS)
        self.assertEqual(len(rows), len(res.top))
        for (ids, vals), e in zip(rows, res.top):
            self.assertEqual(ids[0], e.cand.item_id)
            self.assertEqual(len(vals), len(vm.TOP_COLS))
            if e.cand.buy_source != "vendor":
                self.assertEqual(vals[vm.TOP_COLS.index("ROI")], "—")

    def test_route_rows_nested(self):
        res, _ = run_demo()
        tree = vm.route_tree(res, demo.VENDORS)
        self.assertTrue(tree)
        parent, children = tree[0]
        self.assertTrue(children)
        self.assertTrue(parent[3])
        self.assertEqual(len(children[0][1]), len(vm.ROUTE_COLS))


if __name__ == "__main__":
    unittest.main()


class ProfessionRowsTest(unittest.TestCase):
    def test_rows_for_profession_best_first_then_rejected(self):
        from forever_deals import analytics
        res, _ = run_demo()
        name = analytics.by_profession(res)[0].name
        rows = vm.profession_rows(res, demo.VENDORS, name)
        evs = [e for e in res.ranked + res.rejected if e.cand.profession == name]
        self.assertEqual(len(rows), len(evs))
        status = [vals[-1] for _, vals in rows]
        first_bad = next((i for i, st in enumerate(status) if st.startswith("❌")), len(status))
        self.assertTrue(all(st.startswith("✅") for st in status[:first_bad]))
        self.assertTrue(all(st.startswith("❌") for st in status[first_bad:]))
        self.assertTrue(all(len(vals) == len(vm.PROF_COLS) for _, vals in rows))
