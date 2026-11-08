import json
import unittest
from forever_deals import wowhead
from forever_deals.store import Store

SOLD = ('<html><script>g_pageInfo={type:3,typeId:2320};</script><script>new Listview({template: \'npc\', id: \'sold-by\', '
        'name: LANG.tab_soldby, data: ' + json.dumps([
            {"id": 3490, "name": "Стефани Тёрнер", "location": [1519], "stock": -1, "cost": [10]},
            {"id": 3491, "name": "Меновщик", "location": [12], "stock": 5, "cost": [0, [[1, 2]]]},
        ]) + '});</script></html>')
NONE = '<html><script>g_pageInfo={type:3,typeId:2589};</script><script>new Listview({template: \'item\', id: \'reagent-for\', data: [{"id":1}]});</script></html>'


class ParseTest(unittest.TestCase):
    def test_vendor_found(self):
        r = wowhead.parse(SOLD)
        self.assertEqual(r["status"], "vendor")
        self.assertEqual([v["npc_id"] for v in r["vendors"]], [3490, 3491])
        self.assertEqual(r["vendors"][0]["price"], 10)
        self.assertEqual(r["vendors"][0]["stock"], None)       # -1 = без ограничения
        self.assertEqual(r["vendors"][1]["stock"], 5)
        self.assertIsNone(r["vendors"][1]["price"])            # цена не в меди (обмен)

    def test_not_sold(self):
        self.assertEqual(wowhead.parse(NONE)["status"], "none")

    def test_unrecognized_page_is_unknown_not_none(self):
        for html in ("", "<html>Access denied</html>", "{}"):
            self.assertEqual(wowhead.parse(html)["status"], "unknown")

    def test_broken_json_is_unknown(self):
        self.assertEqual(wowhead.parse("g_pageInfo={}; id: 'sold-by', data: [{bad]")["status"], "unknown")


class CheckTest(unittest.TestCase):
    def opener(self, calls, html):
        class R:
            def __init__(s, h): s.h = h
            def read(s): return s.h.encode()
            def __enter__(s): return s
            def __exit__(s, *a): pass
        def op(req, timeout=0):
            calls.append(req.full_url)
            return R(html)
        return op

    def test_cached_once_per_item(self):
        st, calls = Store(":memory:"), []
        ck = wowhead.Checker(st, "https://www.wowhead.com/forever", opener=self.opener(calls, SOLD), sleep=lambda s: None)
        a = ck.check(2320, now=100)
        b = ck.check(2320, now=200)
        self.assertEqual(a, b)
        self.assertEqual(calls, ["https://www.wowhead.com/forever/item=2320"])

    def test_unknown_is_not_cached_so_it_is_retried(self):
        st, calls = Store(":memory:"), []
        ck = wowhead.Checker(st, "https://x", opener=self.opener(calls, "oops"), sleep=lambda s: None)
        ck.check(1, now=1); ck.check(1, now=2)
        self.assertEqual(len(calls), 2)

    def test_network_error_gives_unknown(self):
        def boom(req, timeout=0): raise OSError("net")
        ck = wowhead.Checker(Store(":memory:"), "https://x", opener=boom, sleep=lambda s: None)
        self.assertEqual(ck.check(1, now=1)["status"], "unknown")

    def test_budget_limits_requests(self):
        calls = []
        ck = wowhead.Checker(Store(":memory:"), "https://x", opener=self.opener(calls, SOLD), sleep=lambda s: None, budget=2)
        res = [ck.check(i, now=1)["status"] for i in (1, 2, 3)]
        self.assertEqual(res, ["vendor", "vendor", "unknown"])
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()


class PipelineCheckTest(unittest.TestCase):
    def run_with(self, checker):
        from forever_deals import demo, pipeline
        from forever_deals.core import Settings
        from tests.test_fixes import NOW
        st = Store(":memory:")
        demo.seed_history(st, NOW - 600)
        return pipeline.run(demo.DemoClient(), st, demo.VENDORS, Settings(), {"auction_house_id": "1"}, now=NOW, checker=checker)

    class Fake:
        def __init__(self, answers): self.answers, self.asked = answers, []
        def check(self, item_id, now=None):
            self.asked.append(item_id)
            return self.answers.get(item_id, {"status": "none", "vendors": []})

    def test_marks_each_non_vendor_item_once(self):
        fake = self.Fake({900007: {"status": "vendor", "vendors": [{"npc_id": 5, "name": "Травник", "price": 120, "stock": None}]},
                          900008: {"status": "unknown", "vendors": []}})
        res = self.run_with(fake)
        self.assertEqual(len(fake.asked), len(set(fake.asked)))
        self.assertNotIn(900001, fake.asked)                  # вендорные из списка пользователя не проверяем
        by = {e.cand.item_id: e for e in res.ranked}
        self.assertTrue(any("у вендора: Травник" in f for f in by[900007].flags))
        self.assertIn("вендор: не проверено", by[900008].flags)
        self.assertIn("вендор: нет", by[900006].flags)
        self.assertEqual(res.vendor_check[900007]["status"], "vendor")

    def test_without_checker_nothing_changes(self):
        res = self.run_with(None)
        self.assertEqual(res.vendor_check, {})
        self.assertFalse(any("вендор" in f for e in res.ranked for f in e.flags if f.startswith("вендор")))


if __name__ == "__main__":
    unittest.main()
