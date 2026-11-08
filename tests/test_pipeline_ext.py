import unittest

from forever_deals import crafting, pipeline
from forever_deals.core import Settings
from forever_deals.store import Store

NOW = 1_800_000_000


class Cl:
    def __init__(self):
        self.infos = {
            100: dict(name="Слиток", class_id=15, subclass_id=0, purchase_price=0, sell_price=1),
            200: dict(name="Руда", class_id=15, subclass_id=0, purchase_price=0, sell_price=1),
            300: dict(name="Меч новичка", class_id=2, subclass_id=7, quality="UNCOMMON", level=10, purchase_price=0, sell_price=1),
            500: dict(name="Пыль", class_id=15, subclass_id=0, purchase_price=0, sell_price=1),
        }

    def auction_listings(self):
        return {100: [(1000, 20)], 200: [(100, 50)], 300: [(100, 5)], 500: [(400, 30)]}

    def fetch_item(self, i):
        return self.infos[i]

    def sources(self):
        return []


class ExtTest(unittest.TestCase):
    def test_craft_rows_and_names(self):
        recipes, _ = crafting.parse_text("100;1;200:3;Кузнечное дело;Слиток")
        res = pipeline.run(Cl(), Store(":memory:"), {}, Settings(), {}, now=NOW, recipes=recipes)
        self.assertEqual(len(res.craft_rows), 1)
        row = res.craft_rows[0]
        self.assertEqual(row.cost, 300)
        self.assertEqual(row.profit, int(1000 * 0.95) - 300)
        self.assertEqual(res.names[100], "Слиток")
        self.assertEqual(res.names[200], "Руда")

    def test_craft_ids_are_fetched_even_when_not_candidates(self):
        recipes, _ = crafting.parse_text("100;1;200:3;;")
        st = Store(":memory:")
        pipeline.run(Cl(), st, {}, Settings(), {}, now=NOW, recipes=recipes)
        self.assertIsNotNone(st.get_item(100))
        self.assertIsNotNone(st.get_item(200))

    def test_disenchant_rows(self):
        rules = [dict(classes=[2, 4], quality="UNCOMMON", ilvl_min=1, ilvl_max=15, results=[dict(item=500, qty=1.0)])]
        res = pipeline.run(Cl(), Store(":memory:"), {}, Settings(min_net=10), {}, now=NOW, de_rules=rules)
        self.assertEqual([r["item_id"] for r in res.de_rows], [300])
        self.assertEqual(res.de_rows[0]["profit"], int(400 * 0.95) - 100)

    def test_no_recipes_no_rules_means_empty(self):
        res = pipeline.run(Cl(), Store(":memory:"), {}, Settings(), {}, now=NOW)
        self.assertEqual((res.craft_rows, res.de_rows), ([], []))


if __name__ == "__main__":
    unittest.main()
