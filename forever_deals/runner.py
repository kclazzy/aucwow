"""Запуск поиска: общая точка для окна и командной строки."""
from __future__ import annotations

import time
from datetime import datetime

from . import alerts, appdata, crafting, demo, disenchant, pipeline, report, vendors, websource, wowhead
from .blizzard import Client
from .store import Store


def run_search(h, cfg, progress=lambda m: None, digest=False, mark=True):
    """-> (result, markdown, report_path, vendor_items). При сбое записывает его в состояние (повтор через retry_minutes)."""
    try:
        result = _run(h, cfg, progress, mark)
        if not cfg.get("demo"):
            res = result[0]
            res.notified = alerts.notify(h, cfg, res, appdata.load_settings(cfg), digest, today=datetime.now().date().isoformat())
        return result
    except Exception as exc:
        if mark and not cfg.get("demo"):
            appdata.mark_fail(h, datetime.now(), str(exc))
        raise


def load_user_tables(h, warnings: list):
    """Рецепты и таблица дизенчанта пользователя. Битый файл не роняет запуск, а даёт предупреждение."""
    out = []
    for name, loader in (("recipes.json", crafting.load), ("disenchant.json", disenchant.load)):
        try:
            out.append(loader(h / name))
        except (ValueError, KeyError, TypeError) as exc:
            warnings.append(f"{name}: не удалось прочитать ({exc}); файл пропущен.")
            out.append({} if name == "recipes.json" else [])
    return out[0], out[1]


def _run(h, cfg, progress, mark=True):
    s = appdata.load_settings(cfg)
    items = demo.VENDORS if cfg.get("demo") else vendors.load(h / "vendors.json")
    now = int(time.time())
    if cfg.get("demo"):
        store = Store(":memory:")
        demo.seed_history(store, now - 600)
        client = demo.DemoClient()
    elif cfg.get("source") == "web":
        store = Store(h / "history.sqlite")
        client = websource.WebClient(cfg).load()                 # без API: таблица цен со страницы или из файла
        progress(f"Таблица цен загружена: {len(client.rows)} предметов.")
        items = {**client.vendor_items(), **items}                # свой список вендоров важнее данных сайта
    else:
        if not appdata.configured(cfg):
            raise RuntimeError("Не заполнены настройки Blizzard API (кнопка «Настройки»).")
        store = Store(h / "history.sqlite")
        client = Client(cfg)
    warns = []
    if cfg.get("demo"):
        recipes, de_rules = crafting.parse_text(demo.RECIPES_TEXT)[0], demo.DE_RULES
    else:
        recipes, de_rules = load_user_tables(h, warns)
    if cfg.get("demo"):
        cfg = {**cfg, "compare_houses": [{"id": "2", "name": "Blackwater (демо)", "cut": 0.15}]}
    checker = None
    if cfg.get("demo"):
        checker = demo.DemoChecker()
    elif cfg.get("wowhead_check", True):
        checker = wowhead.Checker(store, cfg.get("wowhead_base") or "https://www.wowhead.com/forever",
                                  budget=int(cfg.get("wowhead_budget", 40)))
    res = pipeline.run(client, store, items, s, cfg, now=now, progress=progress, recipes=recipes, de_rules=de_rules,
                       checker=checker)
    res.warnings += warns
    if cfg.get("source") == "web" and not cfg.get("demo"):
        res.warnings += client.warnings()
        res.warnings.append("Источник без API: цены берутся из таблицы сайта (рыночная цена), продаж в день пока нет — они "
                            "оценятся после нескольких ежедневных запусков.")
    md = report.build_markdown(res, s, items, demo=bool(cfg.get("demo")), wowhead_base=cfg.get("wowhead_base"))
    path = h / "reports" / f"{datetime.fromtimestamp(now):%Y-%m-%d_%H%M}{'_demo' if cfg.get('demo') else ''}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    path.with_suffix(".html").write_text(report.markdown_to_html(md), encoding="utf-8")
    appdata.prune_reports(h, int(cfg.get("keep_reports", 30)))
    if mark and not cfg.get("demo"):
        appdata.mark_run(h, datetime.fromtimestamp(now))
    return res, md, path, items
