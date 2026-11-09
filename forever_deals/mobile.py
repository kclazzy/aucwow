"""Выгрузка последнего запуска для телефона: один JSON-файл (mobile.json), который показывает страница из папки mobile/."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import links, viewmodel as vm
from .core import fmt_money

VERSION = 1


def _tab(tid, title, cols, rows, base, cat=None, hint=""):
    return {"id": tid, "title": title, "cols": list(cols), "cat": cat, "hint": hint,
            "rows": [{"v": [str(x) for x in vals], "id": ids[0], "url": links.item_url(ids[0], base)} for ids, vals in rows]}


def build_export(res, items, cfg) -> dict:
    base = cfg.get("wowhead_base") or links.WOWHEAD
    ts = res.meta.get("ts") or datetime.now().timestamp()
    source = "демо" if cfg.get("demo") else ("веб-страница" if cfg.get("source") == "web" else "API Blizzard")
    tabs = [
        _tab("top", "Топ-10", vm.TOP_COLS, vm.top_rows(res, items), base, cat=2),
        _tab("vendor", "Покупка у вендора", vm.VENDOR_COLS, vm.vendor_rows(res, items), base,
             hint="Подтверждённые позиции: список вендоров, данные сайта или Wowhead."),
        _tab("possible", "Возможно у вендора", vm.POSSIBLE_COLS, vm.possible_table(res), base, cat=1,
             hint="Есть признак вендора, но цены в монетах нет."),
        _tab("catalog", "Все позиции", vm.CATALOG_COLS, vm.catalog_table(res, None), base, cat=1),
        _tab("short", "Дефицит", vm.SHORT_COLS, vm.shortage_table(res), base, cat=1),
        *([_tab("factions", "Фракции", vm.faction_cols(res), vm.faction_table(res), base, cat=1,
                hint="Цены по фракциям без порогов выгоды; чистыми — с учётом комиссии.")] if res.faction_rows else []),
        _tab("arb", "Аукционы", vm.ARB_COLS, vm.arb_table(res), base, hint="Купить на одном аукционе, продать на другом."),
    ]
    return {"version": VERSION, "demo": bool(cfg.get("demo")), "source": source,
            "generated": datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M"),
            "meta": {"items_on_ah": res.meta.get("items_on_ah"), "candidates": res.meta.get("candidates")},
            "warnings": list(res.warnings), "tabs": tabs}


def write(home, res, items, cfg) -> Path:
    path = Path(home) / "mobile.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(build_export(res, items, cfg), ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)                      # подмена целиком: телефон не увидит наполовину записанный файл
    return path
