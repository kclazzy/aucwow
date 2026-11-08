import unittest

from forever_deals import viewmodel as vm
from forever_deals.core import DAY, aggregate_listings
from forever_deals.store import Store


class PriceHistoryTest(unittest.TestCase):
    def test_daily_min_and_market_ordered(self):
        st = Store(":memory:")
        d0 = 1_800_000_000 // DAY * DAY
        st.add_snapshot(d0 + 100, {1: aggregate_listings([(100, 10)])})
        st.add_snapshot(d0 + 200, {1: aggregate_listings([(80, 10)])})
        st.add_snapshot(d0 + DAY + 50, {1: aggregate_listings([(120, 10)])})
        rows = st.price_history(1, d0)
        self.assertEqual([(r[0], r[1]) for r in rows], [(d0, 80), (d0 + DAY, 120)])
        self.assertEqual(len(rows[0]), 3)

    def test_unknown_item_is_empty(self):
        self.assertEqual(Store(":memory:").price_history(99, 0), [])


class LinePointsTest(unittest.TestCase):
    def test_scales_to_box_with_padding(self):
        pts = vm.line_points([10, 20, 15], 200, 100, pad=10)
        self.assertEqual(len(pts), 3)
        self.assertEqual(pts[0], (10, 90))          # минимум внизу
        self.assertEqual(pts[1], (100, 10))         # максимум вверху
        self.assertEqual(pts[2][0], 190)

    def test_constant_series_is_centered(self):
        pts = vm.line_points([5, 5, 5], 200, 100, pad=10)
        self.assertTrue(all(y == 50 for _, y in pts))

    def test_single_point_and_empty(self):
        self.assertEqual(vm.line_points([], 200, 100), [])
        self.assertEqual(len(vm.line_points([7], 200, 100, pad=10)), 1)

    def test_none_values_are_skipped_but_keep_x_positions(self):
        pts = vm.line_points([10, None, 30], 200, 100, pad=10)
        self.assertEqual([p[0] for p in pts], [10, 190])


if __name__ == "__main__":
    unittest.main()
