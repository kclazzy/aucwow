"""Запуск поиска: общая точка для окна и командной строки."""
from __future__ import annotations

import time
from datetime import datetime

from . import appdata, demo, pipeline, report, vendors
from .blizzard import Client
from .store import Store


def run_search(h, cfg, progress=lambda m: None):
    """-> (result, markdown, report_path, vendor_items). При сбое записывает его в состояние (повтор через retry_minutes)."""
    try:
        return _run(h, cfg, progress)
    except Exception as exc:
        if not cfg.get("demo"):
            appdata.mark_fail(h, datetime.now(), str(exc))
        raise


def _run(h, cfg, progress):
    s = appdata.load_settings(cfg)
    items = demo.VENDORS if cfg.get("demo") else vendors.load(h / "vendors.json")
    now = int(time.time())
    if cfg.get("demo"):
        store = Store(":memory:")
        demo.seed_history(store, now - 600)
        client = demo.DemoClient()
    else:
        if not appdata.configured(cfg):
            raise RuntimeError("Не заполнены настройки Blizzard API (кнопка «Настройки»).")
        store = Store(h / "history.sqlite")
        client = Client(cfg)
    res = pipeline.run(client, store, items, s, cfg, now=now, progress=progress)
    md = report.build_markdown(res, s, items, demo=bool(cfg.get("demo")), wowhead_base=cfg.get("wowhead_base"))
    path = h / "reports" / f"{datetime.fromtimestamp(now):%Y-%m-%d_%H%M}{'_demo' if cfg.get('demo') else ''}.md"
    path.write_text(md, encoding="utf-8")
    path.with_suffix(".html").write_text(report.markdown_to_html(md), encoding="utf-8")
    appdata.prune_reports(h, int(cfg.get("keep_reports", 30)))
    if not cfg.get("demo"):
        appdata.mark_run(h, datetime.fromtimestamp(now))
    return res, md, path, items
