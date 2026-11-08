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
