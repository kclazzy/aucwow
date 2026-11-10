import json
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from forever_deals.core import Settings
from forever_deals import appdata, mobile, mobile_server, runner

ROOT = Path(__file__).resolve().parent.parent


def demo_run():
    d = tempfile.TemporaryDirectory()
    h = Path(d.name)
    cfg = {**appdata.DEFAULT_CFG, "demo": True}
    res, md, path, items = runner.run_search(h, cfg)
    return d, h, cfg, res, items


class ExportTest(unittest.TestCase):
    def test_export_has_tabs_with_matching_columns_and_links(self):
        d, h, cfg, res, items = demo_run()
        self.addCleanup(d.cleanup)
        data = mobile.build_export(res, items, cfg, Settings())
        self.assertEqual(data["version"], 1)
        self.assertTrue(data["demo"])
        tabs = {t["id"]: t for t in data["tabs"]}
        self.assertTrue({"top", "vendor", "possible", "catalog", "arb", "short", "snipe"} <= set(tabs))
        for t in tabs.values():
            for row in t["rows"]:
                self.assertEqual(len(row["v"]), len(t["cols"]), t["id"])
        top = tabs["top"]["rows"][0]
        self.assertTrue(top["url"].endswith(f"/item={top['id']}"))
        json.dumps(data, ensure_ascii=False)                    # сериализуется целиком

    def test_runner_writes_mobile_json_next_to_reports(self):
        d, h, cfg, res, items = demo_run()
        self.addCleanup(d.cleanup)
        data = json.loads((h / "mobile.json").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        self.assertGreater(len(data["tabs"][0]["rows"]), 0)

    def test_token_created_once_and_kept(self):
        cfg = {}
        t1 = mobile_server.ensure_token(cfg)
        self.assertEqual(len(t1), 16)
        self.assertEqual(mobile_server.ensure_token(cfg), t1)


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.h = Path(self.d.name)
        (self.h / "mobile.json").write_text('{"version": 1, "tabs": []}', encoding="utf-8")
        self.srv = mobile_server.MobileServer(self.h, "secret123", port=0, host="127.0.0.1")
        self.srv.start()
        self.addCleanup(self.srv.stop)
        self.base = f"http://127.0.0.1:{self.srv.port}"

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()

    def test_serves_page_data_and_scripts_under_token(self):
        st, ct, body = self.get("/secret123/")
        self.assertEqual(st, 200)
        self.assertIn("text/html", ct)
        self.assertIn(b"logic.js", body)
        self.assertEqual(json.loads(self.get("/secret123/data.json")[2])["version"], 1)
        self.assertEqual(self.get("/secret123/logic.js")[0], 200)

    def test_wrong_token_and_path_traversal_are_404(self):
        for path in ("/", "/wrong/", "/wrong/data.json", "/secret123/../app.py", "/secret123/%2e%2e/config.json"):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.get(path)
            self.assertEqual(cm.exception.code, 404, path)

    def test_data_is_reread_on_every_request(self):
        (self.h / "mobile.json").write_text('{"version": 1, "marker": "new", "tabs": []}', encoding="utf-8")
        self.assertEqual(json.loads(self.get("/secret123/data.json")[2])["marker"], "new")

    def test_missing_data_is_404_with_hint(self):
        (self.h / "mobile.json").unlink()
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/secret123/data.json")
        self.assertEqual(cm.exception.code, 404)

    def test_stop_releases_port(self):
        self.srv.stop()
        with self.assertRaises(OSError):
            self.get("/secret123/")

    def test_urls_use_lan_address_and_token(self):
        urls = self.srv.urls(["192.168.0.5"])
        self.assertEqual(urls, [f"http://192.168.0.5:{self.srv.port}/secret123/"])


@unittest.skipUnless(shutil.which("node"), "нет node")
class PageLogicTest(unittest.TestCase):
    def test_js_logic(self):
        r = subprocess.run(["node", "--test", str(ROOT / "tests" / "mobile_logic.test.mjs")], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(shutil.which("google-chrome"), "нет Chrome")
class PageRenderTest(unittest.TestCase):
    """Страница в настоящем браузере: данные грузятся, карточки рисуются, названия из данных не исполняются как HTML."""

    def dom(self, home):
        srv = mobile_server.MobileServer(home, "tok", port=0, host="127.0.0.1").start()
        self.addCleanup(srv.stop)
        r = subprocess.run(["google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu", "--virtual-time-budget=4000",
                            "--dump-dom", f"http://127.0.0.1:{srv.port}/tok/"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        return r.stdout

    def test_demo_data_renders_cards_and_tabs(self):
        d, h, cfg, res, items = demo_run()
        self.addCleanup(d.cleanup)
        dom = self.dom(h)
        self.assertGreaterEqual(dom.count('class="card"'), 5)
        self.assertIn("Покупка у вендора", dom)
        self.assertIn("ДЕМО", dom)

    def test_item_names_are_not_interpreted_as_html(self):
        d, h, cfg, res, items = demo_run()
        self.addCleanup(d.cleanup)
        data = json.loads((h / "mobile.json").read_text(encoding="utf-8"))
        data["tabs"][0]["rows"][0]["v"][1] = "<img src=x onerror=document.title='pwned'>"
        (h / "mobile.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        dom = self.dom(h)
        self.assertNotIn("<img src=x", dom)
        self.assertNotIn("<title>pwned", dom)
        self.assertIn("&lt;img src=x", dom)

    def test_missing_data_shows_file_fallback(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.assertIn("mobile.json", self.dom(Path(d.name)))
