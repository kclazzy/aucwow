"""Разовая сверка с Wowhead: продаётся ли предмет у вендора. Результат кэшируется в базе: по каждому предмету один запрос.

Разметка страниц Forever мне подтвердить не удалось. Разбор рассчитан на вкладку «Продаётся» (Listview с id 'sold-by'),
как на других версиях Wowhead. Если страница не распознана, статус «unknown»: это НЕ значит «вендора нет», и он не кэшируется."""
from __future__ import annotations

import json
import re
import time
import urllib.request

UA = "ForeverDeals/1.0 (личное приложение, один запрос на предмет)"


def _array_after(text: str, start: int):
    """JSON-массив, начинающийся с ближайшей '[' после start (учитывает строки и вложенность). None при ошибке."""
    i = text.find("[", start)
    if i < 0:
        return None
    depth, j, in_str, esc = 0, i, False, False
    while j < len(text):
        c = text[j]
        if in_str:
            esc = (c == "\\" and not esc)
            if c == '"' and not esc:
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[i:j + 1])
                except ValueError:
                    return None
        j += 1
    return None


def _vendor(row: dict) -> dict:
    cost = row.get("cost") or []
    price = cost[0] if len(cost) == 1 and isinstance(cost[0], int) else None   # валюта/предметы: в меди не выразить
    stock = row.get("stock")
    return {"npc_id": row.get("id"), "name": row.get("name", ""), "price": price,
            "stock": stock if isinstance(stock, int) and stock >= 0 else None}


def parse(html: str) -> dict:
    """-> {'status': 'vendor'|'none'|'unknown', 'vendors': [{npc_id, name, price (медь|None), stock (шт|None)}]}"""
    unknown = {"status": "unknown", "vendors": []}
    if not html or ("Listview" not in html and "g_pageInfo" not in html):
        return unknown
    m = re.search(r"""id:\s*['"]sold-by['"]""", html)
    if not m:
        return {"status": "none", "vendors": []}
    rows = _array_after(html, m.end())
    if not isinstance(rows, list):
        return unknown
    vendors = [_vendor(r) for r in rows if isinstance(r, dict) and r.get("id")]
    return {"status": "vendor", "vendors": vendors} if vendors else unknown


class Checker:
    """Проверяет предметы по одному разу. budget — максимум сетевых запросов за запуск."""

    def __init__(self, store, base: str, opener=urllib.request.urlopen, sleep=time.sleep, budget: int = 40, pause: float = 1.0):
        self.store, self.base, self.opener, self.sleep = store, base.rstrip("/"), opener, sleep
        self.budget, self.pause, self.used = budget, pause, 0

    def check(self, item_id: int, now: int | None = None) -> dict:
        cached = self.store.wh_get(item_id)
        if cached:
            return cached
        if self.used >= self.budget:
            return {"status": "unknown", "vendors": [], "skipped": True}
        if self.used:
            self.sleep(self.pause)         # вежливая пауза между запросами
        self.used += 1
        try:
            req = urllib.request.Request(f"{self.base}/item={item_id}", headers={"User-Agent": UA})
            with self.opener(req, timeout=20) as r:
                result = parse(r.read().decode("utf-8", "replace"))
        except (OSError, ValueError):
            result = {"status": "unknown", "vendors": []}
        if result["status"] != "unknown":
            self.store.wh_put(item_id, result, int(now or time.time()))
        return result
