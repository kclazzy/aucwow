import unittest

from forever_deals import lua, trades_import
from forever_deals.store import Store

SAMPLE = r'''
MyAddonDB = {
	["version"] = 3,
	["ledger"] = {
		{
			["itemID"] = 2589,
			["count"] = 20,
			["price"] = 1500, -- за штуку
			["type"] = "sale",
			["time"] = 1800000100,
		}, -- [1]
		{
			["itemID"] = 2589,
			["count"] = 40,
			["price"] = 8,
			["type"] = "purchase",
			["time"] = 1800000000,
		}, -- [2]
		{
			["note"] = "не сделка",
		}, -- [3]
	},
	["name"] = "a \"quoted\" \\ string\n",
	["flag"] = true,
	["neg"] = -2.5e1,
	[7] = "seven",
}
OtherDB = { 1, 2, 3 }
'''


class LuaParseTest(unittest.TestCase):
    def test_parses_assignments_and_tables(self):
        t = lua.parse(SAMPLE)
        self.assertEqual(set(t), {"MyAddonDB", "OtherDB"})
        db = t["MyAddonDB"]
        self.assertEqual(db["version"], 3)
        self.assertEqual(db["flag"], True)
        self.assertEqual(db["neg"], -25.0)
        self.assertEqual(db[7], "seven")
        self.assertEqual(db["name"], 'a "quoted" \\ string\n')
        self.assertEqual(t["OtherDB"], {1: 1, 2: 2, 3: 3})

    def test_comments_are_ignored(self):
        self.assertEqual(lua.parse("X = { --[[ block\ncomment ]] 1, -- line\n 2 }")["X"], {1: 1, 2: 2})

    def test_nil_and_nested(self):
        t = lua.parse('X = { a = nil, b = { c = { d = "e" } } }')
        self.assertIsNone(t["X"]["a"])
        self.assertEqual(t["X"]["b"]["c"]["d"], "e")

    def test_garbage_raises_value_error(self):
        for bad in ("X = {", "X = ", "= 5", 'X = "unterminated'):
            with self.assertRaises(ValueError):
                lua.parse(bad)


class TradeExtractTest(unittest.TestCase):
    def test_extracts_sale_and_purchase(self):
        trades, skipped = trades_import.extract(lua.parse(SAMPLE))
        self.assertEqual(len(trades), 2)
        kinds = {(t["kind"], t["qty"], t["unit_price"]) for t in trades}
        self.assertEqual(kinds, {("sell", 20, 1500), ("buy", 40, 8)})
        self.assertEqual(skipped, 0)               # запись без предмета/цены не считаем кандидатом

    def test_item_link_and_total_price(self):
        tree = {"log": [{"link": "|cff1eff00|Hitem:2589::::::::60:::::|h[Лён]|h|r", "stack": 10, "totalPrice": 500,
                         "action": "bought", "timestamp": 5}]}
        trades, _ = trades_import.extract(tree)
        self.assertEqual(trades, [dict(ts=5, item_id=2589, kind="buy", qty=10, unit_price=50)])

    def test_unknown_kind_is_skipped_and_counted(self):
        tree = {"log": [{"itemID": 1, "count": 1, "price": 5, "type": "mail"}]}
        trades, skipped = trades_import.extract(tree)
        self.assertEqual((trades, skipped), ([], 1))

    def test_custom_mapping(self):
        tree = {"x": [{"it": 9, "n": 2, "p": 7, "t": "sale"}]}
        m = dict(item="it", qty="n", price="p", kind="t")
        trades, _ = trades_import.extract(tree, mapping=m)
        self.assertEqual(trades[0]["item_id"], 9)


class BulkImportTest(unittest.TestCase):
    def test_import_is_idempotent(self):
        st = Store(":memory:")
        trades, _ = trades_import.extract(lua.parse(SAMPLE))
        self.assertEqual(st.add_trades(trades), 2)
        self.assertEqual(st.add_trades(trades), 0)
        self.assertEqual(st.trade_summary()[0]["bought"], 40)


if __name__ == "__main__":
    unittest.main()
