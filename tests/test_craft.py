import json
import tempfile
import unittest
from pathlib import Path

from forever_deals import crafting, disenchant
from forever_deals.core import Aggregate, Settings


def agg(min_price, market=None, qty=100):
    return Aggregate(min_price, market or min_price, qty, 5)


class RecipeParseTest(unittest.TestCase):
    def test_parse_lines_with_ids_and_links(self):
        text = ("900001 ; 1 ; 900002:2, https://www.wowhead.com/forever/item=900003:1 ; Кузнечное дело ; Медный слиток\n"
                "bad line\n"
                "900010;2;900011:1;;\n")
        recipes, errors = crafting.parse_text(text)
        self.assertEqual(len(recipes), 2)
        r = recipes[900001]
        self.assertEqual(r.reagents, ((900002, 2), (900003, 1)))
        self.assertEqual((r.qty, r.profession, r.name), (1, "Кузнечное дело", "Медный слиток"))
        self.assertEqual(recipes[900010].profession, "Прочее")
        self.assertEqual(len(errors), 1)

    def test_save_load_roundtrip(self):
        recipes, _ = crafting.parse_text("1;1;2:3;Алхимия;Зелье")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "recipes.json"
            crafting.save(p, recipes)
            self.assertEqual(crafting.load(p), recipes)
            self.assertEqual(crafting.load(Path(d) / "none.json"), {})


class CraftProfitTest(unittest.TestCase):
    def recipe(self):
        recipes, _ = crafting.parse_text("100;1;200:2,201:1;Кузнечное дело;Слиток")
        return recipes[100]

    def test_profit_uses_cheaper_of_auction_and_vendor(self):
        s = Settings(cut=0.05)
        prices = {100: agg(600), 200: agg(100), 201: agg(50)}
        row = crafting.craft_profit(self.recipe(), prices, {201: 30}, {}, s)
        self.assertEqual(row.cost, 2 * 100 + 30)
        self.assertEqual(row.revenue, int(600 * 0.95))
        self.assertEqual(row.profit, int(600 * 0.95) - 230)
        self.assertAlmostEqual(row.roi, row.profit / 230)
        self.assertEqual(row.unknown, ())

    def test_usual_price_caps_sell_price(self):
        s = Settings(cut=0.0)
        prices = {100: agg(600), 200: agg(10), 201: agg(10)}
        row = crafting.craft_profit(self.recipe(), prices, {}, {100: 400}, s)
        self.assertEqual(row.revenue, 400)

    def test_missing_reagent_price_makes_profit_unknown(self):
        row = crafting.craft_profit(self.recipe(), {100: agg(600), 200: agg(100)}, {}, {}, Settings())
        self.assertIsNone(row.profit)
        self.assertEqual(row.unknown, (201,))

    def test_missing_product_price_makes_profit_unknown(self):
        row = crafting.craft_profit(self.recipe(), {200: agg(1), 201: agg(1)}, {}, {}, Settings())
        self.assertIsNone(row.profit)

    def test_rank_known_first_by_profit(self):
        recipes, _ = crafting.parse_text("100;1;200:1;A;a\n101;1;200:1;A;b\n102;1;999:1;A;c")
        prices = {100: agg(500), 101: agg(900), 102: agg(900), 200: agg(100)}
        rows = [crafting.craft_profit(r, prices, {}, {}, Settings()) for r in recipes.values()]
        ranked = crafting.rank(rows)
        self.assertEqual([r.recipe.product for r in ranked], [101, 100, 102])


class DisenchantTest(unittest.TestCase):
    rules = [dict(classes=[2, 4], quality="UNCOMMON", ilvl_min=1, ilvl_max=15, results=[dict(item=500, qty=1.5)])]

    def test_loads_and_validates(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "disenchant.json"
            p.write_text(json.dumps({"rules": self.rules}), encoding="utf-8")
            self.assertEqual(len(disenchant.load(p)), 1)
            p.write_text("{bad", encoding="utf-8")
            with self.assertRaises(ValueError):
                disenchant.load(p)
            p.write_text(json.dumps({"rules": [{"classes": [2]}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                disenchant.load(p)
            self.assertEqual(disenchant.load(Path(d) / "none.json"), [])

    def info(self, **kw):
        return dict(dict(name="Меч", class_id=2, quality="UNCOMMON", level=10), **kw)

    def test_rows_profit_after_cut(self):
        s = Settings(cut=0.05, min_net=10)
        items = {1: self.info()}
        prices = {1: agg(100), 500: agg(200)}
        rows = disenchant.rows(items, prices, self.rules, s)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["value"], 300)                       # 1.5 * 200
        self.assertEqual(r["profit"], int(300 * 0.95) - 100)

    def test_no_match_by_class_quality_or_level(self):
        s = Settings(min_net=0)
        prices = {1: agg(100), 500: agg(200)}
        for bad in (self.info(class_id=7), self.info(quality="RARE"), self.info(level=40)):
            self.assertEqual(disenchant.rows({1: bad}, prices, self.rules, s), [])

    def test_unknown_result_price_skips(self):
        self.assertEqual(disenchant.rows({1: self.info()}, {1: agg(100)}, self.rules, Settings(min_net=0)), [])

    def test_unprofitable_filtered_and_sorted(self):
        s = Settings(cut=0.05, min_net=10)
        items = {1: self.info(), 2: self.info(name="Топор")}
        prices = {1: agg(100), 2: agg(50), 500: agg(200)}
        rows = disenchant.rows(items, prices, self.rules, s)
        self.assertEqual([r["item_id"] for r in rows], [2, 1])
        prices[1] = agg(900)
        self.assertEqual([r["item_id"] for r in disenchant.rows(items, prices, self.rules, s)], [2])


if __name__ == "__main__":
    unittest.main()
