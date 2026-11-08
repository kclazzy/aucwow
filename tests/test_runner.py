import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from forever_deals import appdata, runner


class RunnerTest(unittest.TestCase):
    def test_demo_run_writes_md_and_html_without_marking(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            (h / "reports").mkdir()
            cfg = dict(appdata.DEFAULT_CFG, demo=True)
            res, md, path, _ = runner.run_search(h, cfg)
            self.assertTrue(path.exists())
            self.assertTrue(path.with_suffix(".html").exists())
            self.assertIsNone(appdata.last_run(h))

    def test_failure_is_recorded_and_reraised(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            (h / "reports").mkdir()
            cfg = dict(appdata.DEFAULT_CFG)             # ключей нет
            with self.assertRaises(RuntimeError):
                runner.run_search(h, cfg)
            self.assertIn("Blizzard", appdata.last_error(h))
            self.assertFalse(appdata.is_due(dict(cfg, run_time="00:00"), h, datetime.now() + timedelta(seconds=1)))


class ExtrasInRunnerTest(unittest.TestCase):
    def test_demo_has_craft_and_disenchant_examples(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            (h / "reports").mkdir()
            res, *_ = runner.run_search(h, dict(appdata.DEFAULT_CFG, demo=True))
            self.assertTrue(res.craft_rows)
            self.assertTrue(any(r.profit and r.profit > 0 for r in res.craft_rows))
            self.assertTrue(res.de_rows)

    def test_user_files_are_loaded_and_broken_disenchant_file_warns(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            (h / "reports").mkdir()
            (h / "disenchant.json").write_text("{broken", encoding="utf-8")
            from forever_deals import runner as r
            warns = []
            rec, rules = r.load_user_tables(h, warns)
            self.assertEqual((rec, rules), ({}, []))
            self.assertTrue(any("disenchant.json" in w for w in warns))
