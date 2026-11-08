import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from forever_deals import alerts, appdata, demo, exporters, report
from forever_deals.core import Settings, evaluate
from tests.test_core import cand
from tests.test_fixes import run_demo


class ExportTest(unittest.TestCase):
    def test_tsm_string(self):
        self.assertEqual(exporters.tsm_search_string(["Грубая нить", "Краска"]), "Грубая нить/exact;Краска/exact")

    def test_tsm_string_strips_separators_and_duplicates(self):
        self.assertEqual(exporters.tsm_search_string(["A;B", "A;B", "  "]), "AB/exact")

    def test_plain_lines(self):
        self.assertEqual(exporters.plain_lines(["a", "b"]), "a\nb")

    def test_route_names_in_route_order_without_demo_prefix(self):
        res, _ = run_demo()
        names = exporters.route_names(report.shopping_route(res, demo.VENDORS))
        self.assertTrue(names)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(not n.startswith("[демо]") for n in names))


class DigestTest(unittest.TestCase):
    def test_digest_lists_top_items_with_profit(self):
        res, s = run_demo()
        txt = alerts.digest_text(res, s, n=3)
        self.assertIn("Топ-3", txt)
        self.assertIn(res.top[0].cand.name, txt)
        self.assertEqual(txt.count("\n•"), 3)

    def test_digest_when_nothing(self):
        class R:
            top = []
            meta = {}
        self.assertIn("нет выгодных", alerts.digest_text(R(), Settings(), n=3))


class PriceDropTest(unittest.TestCase):
    def evs(self):
        s = Settings(sales_haircut=1.0)
        cheap = evaluate(cand(item_id=1, min_price=900, usual_price=1500), s)       # 60% от обычной
        normal = evaluate(cand(item_id=2, min_price=1450, usual_price=1500), s)
        no_hist = evaluate(cand(item_id=3, min_price=900, usual_price=None), s)
        return [cheap, normal, no_hist]

    def test_only_real_drops_below_threshold(self):
        class R:
            ranked = self.evs()
        drops = alerts.price_drops(R(), 0.7)
        self.assertEqual([e.cand.item_id for e in drops], [1])

    def test_dedup_within_day(self):
        class R:
            ranked = self.evs()
        state = {}
        first = alerts.new_drops(alerts.price_drops(R(), 0.7), state, "2026-11-08")
        again = alerts.new_drops(alerts.price_drops(R(), 0.7), state, "2026-11-08")
        nextday = alerts.new_drops(alerts.price_drops(R(), 0.7), state, "2026-11-09")
        self.assertEqual((len(first), len(again), len(nextday)), (1, 0, 1))

    def test_drop_text(self):
        e = self.evs()[0]
        txt = alerts.drops_text([e])
        self.assertIn("ниже обычной", txt)
        self.assertIn("60%", txt)


class Fake:
    def __init__(self):
        self.reqs = []

    def __call__(self, req, timeout=0):
        self.reqs.append((req.full_url, req.data, req.get_header("Content-type")))
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"{}"


class SendTest(unittest.TestCase):
    def test_discord_payload_and_truncation(self):
        f = Fake()
        sent = alerts.send({"discord_webhook": "https://discord.com/api/webhooks/1/x"}, "я" * 5000, opener=f)
        self.assertEqual(sent, ["discord"])
        url, data, ctype = f.reqs[0]
        self.assertEqual(url, "https://discord.com/api/webhooks/1/x")
        self.assertLessEqual(len(json.loads(data)["content"]), 2000)
        self.assertEqual(ctype, "application/json")

    def test_telegram_payload(self):
        f = Fake()
        sent = alerts.send({"telegram_token": "T0K", "telegram_chat_id": "42"}, "привет", opener=f)
        self.assertEqual(sent, ["telegram"])
        url, data, _ = f.reqs[0]
        self.assertEqual(url, "https://api.telegram.org/botT0K/sendMessage")
        self.assertEqual(json.loads(data), {"chat_id": "42", "text": "привет"})

    def test_nothing_configured_sends_nothing(self):
        f = Fake()
        self.assertEqual(alerts.send({}, "x", opener=f), [])
        self.assertEqual(f.reqs, [])

    def test_only_https_urls_accepted(self):
        with self.assertRaises(alerts.AlertError):
            alerts.send({"discord_webhook": "http://example.com/x"}, "x", opener=Fake())
        with self.assertRaises(alerts.AlertError):
            alerts.send({"discord_webhook": "file:///etc/passwd"}, "x", opener=Fake())

    def test_network_error_becomes_alert_error(self):
        import urllib.error

        def boom(req, timeout=0):
            raise urllib.error.URLError("down")
        with self.assertRaises(alerts.AlertError):
            alerts.send({"discord_webhook": "https://discord.com/api/webhooks/1/x"}, "x", opener=boom)


class HourlyCheckTest(unittest.TestCase):
    def test_due_only_when_enabled_and_hour_passed(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            now = datetime(2026, 11, 8, 12, 0)
            self.assertFalse(appdata.is_check_due({"hourly_check": False}, h, now))
            cfg = {"hourly_check": True}
            self.assertTrue(appdata.is_check_due(cfg, h, now))
            appdata.mark_check(h, now)
            self.assertFalse(appdata.is_check_due(cfg, h, now + timedelta(minutes=30)))
            self.assertTrue(appdata.is_check_due(cfg, h, now + timedelta(minutes=61)))

    def test_alert_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            appdata.save_alert_state(h, {"2026-11-08": [1, 2]})
            self.assertEqual(appdata.load_alert_state(h), {"2026-11-08": [1, 2]})


if __name__ == "__main__":
    unittest.main()


class NotifyTest(unittest.TestCase):
    def cfg(self, **kw):
        return dict({"discord_webhook": "https://discord.com/api/webhooks/1/x", "drop_pct": 5.0, "alert_digest": True}, **kw)

    def test_digest_and_drops_sent_once_then_deduplicated(self):
        res, s = run_demo()
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            f = Fake()
            out = alerts.notify(h, self.cfg(), res, s, digest=True, opener=f, today="2026-11-08")
            self.assertEqual(out["errors"], [])
            self.assertEqual(len(f.reqs), 2)                       # дайджест + падения цены
            f2 = Fake()
            alerts.notify(h, self.cfg(), res, s, digest=False, opener=f2, today="2026-11-08")
            self.assertEqual(f2.reqs, [])                           # те же падения сегодня не повторяются

    def test_no_channels_means_no_work(self):
        res, s = run_demo()
        with tempfile.TemporaryDirectory() as d:
            out = alerts.notify(Path(d), {}, res, s, digest=True, opener=Fake(), today="2026-11-08")
            self.assertEqual(out, {"sent": [], "errors": []})

    def test_send_failure_is_reported_not_raised(self):
        import urllib.error
        res, s = run_demo()

        def boom(req, timeout=0):
            raise urllib.error.URLError("down")
        with tempfile.TemporaryDirectory() as d:
            out = alerts.notify(Path(d), self.cfg(), res, s, digest=True, opener=boom, today="2026-11-08")
            self.assertTrue(out["errors"])
            self.assertEqual(out["sent"], [])
