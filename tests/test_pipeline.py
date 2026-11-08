import unittest
from forever_deals import demo, pipeline, report
from forever_deals.core import Settings
from forever_deals.store import Store

NOW = 1_800_000_000


def run_demo():
    store = Store(":memory:")
    demo.seed_history(store, NOW - 600)
    s = Settings()
    res = pipeline.run(demo.DemoClient(), store, demo.VENDORS, s, {"connected_realm_id": 1, "auction_house_id": 2}, now=NOW)
    return res, s


class PipelineTest(unittest.TestCase):
    def test_vendor_rows_include_every_vendor_item(self):
        res, _ = run_demo()
        self.assertEqual({e.cand.item_id for e in res.vendor_rows}, set(demo.VENDORS))

    def test_top_sorted_and_limited(self):
        res, s = run_demo()
        self.assertLessEqual(len(res.top), s.top_n)
        epds = [e.epd for e in res.top]
        self.assertEqual(epds, sorted(epds, reverse=True))

    def test_non_vendor_items_get_material_categories(self):
        res, _ = run_demo()
        cats = {e.cand.category for e in res.ranked + res.rejected}
        self.assertTrue({"Перепродажа NPC", "Руда и камень", "Трава", "Кожа", "Ткань", "Рецепт"} <= cats)
        names = {e.cand.name for e in res.ranked + res.rejected}
        self.assertNotIn("Серебряный кабан", names)   # оружие не относится ни к одной группе


class ReportTest(unittest.TestCase):
    def test_report_has_sections_locations_and_wowhead_links(self):
        res, s = run_demo()
        md = report.build_markdown(res, s, demo.VENDORS, demo=True)
        for part in ("## Топ-10", "## Вендор → аукцион", "## Расчёты по топу", "## Источники", "ДЕМО-ДАННЫЕ"):
            self.assertIn(part, md)
        self.assertIn("https://www.wowhead.com/forever/item=900001", md)
        self.assertIn("https://www.wowhead.com/forever/npc=990001", md)
        self.assertIn("Штормград, Ремесленный квартал", md)


if __name__ == "__main__":
    unittest.main()


class ScheduleTest(unittest.TestCase):
    def test_due_logic(self):
        import tempfile
        from datetime import datetime
        from pathlib import Path
        from forever_deals import appdata
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            cfg = {"run_time": "20:00"}
            self.assertFalse(appdata.is_due(cfg, h, datetime(2026, 11, 8, 19, 59)))
            self.assertTrue(appdata.is_due(cfg, h, datetime(2026, 11, 8, 20, 0)))
            appdata.mark_run(h, datetime(2026, 11, 8, 20, 1))
            self.assertFalse(appdata.is_due(cfg, h, datetime(2026, 11, 8, 23, 0)))
            self.assertTrue(appdata.is_due(cfg, h, datetime(2026, 11, 9, 20, 5)))
