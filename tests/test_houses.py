import unittest

from forever_deals import appdata, arbitrage, pipeline
from forever_deals.core import Aggregate, Settings
from forever_deals.store import Store

NOW = 1_800_000_000


def agg(p, q=50):
    return Aggregate(p, p, q, 5)


class ArbitrageTest(unittest.TestCase):
    s = Settings(cut=0.05, min_net=50, min_roi=0.1, min_quantity=3, budget_item=100000)

    def test_buys_cheap_sells_dear_with_target_house_cut(self):
        books = {"A": {1: agg(1000)}, "B": {1: agg(2000)}}
        cuts = {"A": 0.05, "B": 0.15}
        rows = arbitrage.rows(books, cuts, self.s)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["buy_house"], r["sell_house"]), ("A", "B"))
        self.assertEqual(r["net"], int(2000 * 0.85) - 1000)
        self.assertEqual(r["qty"], 50)                    # бюджет 100000 // 1000 = 100, лотов 50

    def test_higher_cut_can_erase_the_gap(self):
        books = {"A": {1: agg(1000)}, "B": {1: agg(1100)}}
        self.assertEqual(arbitrage.rows(books, {"A": 0.05, "B": 0.15}, self.s), [])

    def test_item_must_exist_in_both_and_not_be_isolated(self):
        books = {"A": {1: agg(1000), 2: agg(100)}, "B": {1: agg(2000, q=1), 3: agg(900)}}
        self.assertEqual(arbitrage.rows(books, {"A": 0.05, "B": 0.05}, self.s), [])

    def test_both_directions_considered_and_sorted_by_profit(self):
        books = {"A": {1: agg(1000), 2: agg(3000)}, "B": {1: agg(2000), 2: agg(1500)}}
        rows = arbitrage.rows(books, {"A": 0.05, "B": 0.05}, self.s)
        self.assertEqual([(r["item_id"], r["buy_house"]) for r in rows], [(2, "B"), (1, "A")])

    def test_single_house_gives_nothing(self):
        self.assertEqual(arbitrage.rows({"A": {1: agg(1)}}, {"A": 0.05}, self.s), [])


class HousesConfigTest(unittest.TestCase):
    def test_parse_houses(self):
        hs, errors = appdata.parse_houses("2:Horde:5, 3:Blackwater:15 , bad, 4::")
        self.assertEqual(hs, [{"id": "2", "name": "Horde", "cut": 0.05}, {"id": "3", "name": "Blackwater", "cut": 0.15}])
        self.assertEqual(len(errors), 2)

    def test_empty(self):
        self.assertEqual(appdata.parse_houses(""), ([], []))

    def test_cut_out_of_range_rejected(self):
        hs, errors = appdata.parse_houses("2:X:150")
        self.assertEqual((hs, len(errors)), ([], 1))


class Cl:
    def auction_listings(self, house=None):
        if house is None:
            return {1: [(1000, 20)], 2: [(500, 20)]}
        return {1: [(2000, 20)], 2: [(500, 20)]}

    def fetch_item(self, i):
        return dict(name=f"i{i}", class_id=15, subclass_id=0, purchase_price=0, sell_price=1)

    def sources(self):
        return []


class PipelineHousesTest(unittest.TestCase):
    def test_pipeline_compares_configured_houses(self):
        cfg = {"auction_house_id": "1", "compare_houses": [{"id": "2", "name": "Blackwater", "cut": 0.15}]}
        res = pipeline.run(Cl(), Store(":memory:"), {}, Settings(min_net=50, min_roi=0.1), cfg, now=NOW)
        self.assertEqual(len(res.arb_rows), 1)
        r = res.arb_rows[0]
        self.assertEqual((r["item_id"], r["sell_house"]), (1, "Blackwater"))
        self.assertEqual(r["name"], "i1")

    def test_no_compare_means_empty(self):
        res = pipeline.run(Cl(), Store(":memory:"), {}, Settings(), {}, now=NOW)
        self.assertEqual(res.arb_rows, [])


if __name__ == "__main__":
    unittest.main()
