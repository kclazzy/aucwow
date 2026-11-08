"""Дизенчант: таблицу выпадения вносит пользователь (disenchant.json), программа считает выгоду."""
from __future__ import annotations

import json
from pathlib import Path

from .core import Settings


def _validate(rule) -> dict:
    if not isinstance(rule, dict) or not rule.get("classes") or not rule.get("results"):
        raise ValueError("правило дизенчанта: нужны classes и results")
    for r in rule["results"]:
        if "item" not in r or "qty" not in r:
            raise ValueError("результат дизенчанта: нужны item и qty")
    return rule


def load(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    return [_validate(r) for r in json.loads(p.read_text(encoding="utf-8")).get("rules", [])]


def _matches(info: dict, rule: dict) -> bool:
    if info.get("class_id") not in rule["classes"]:
        return False
    if rule.get("quality") and str(info.get("quality") or "").upper() != str(rule["quality"]).upper():
        return False
    level = info.get("level") or 0
    return rule.get("ilvl_min", 0) <= level <= rule.get("ilvl_max", 10**6)


def rows(items: dict, prices: dict, rules: list, s: Settings):
    """items: {id: сведения о предмете}; prices: {id: Aggregate}. -> позиции, где дизенчант выгоднее покупки, лучшие первыми."""
    out = []
    for item_id, info in items.items():
        agg = prices.get(item_id)
        if not agg or not agg.min_price:
            continue
        for rule in rules:
            if not _matches(info, rule):
                continue
            parts = [(r["qty"], prices.get(r["item"])) for r in rule["results"]]
            if any(a is None or not a.min_price for _, a in parts):
                continue
            value = int(round(sum(q * a.min_price for q, a in parts)))
            profit = int(value * (1 - s.cut)) - agg.min_price
            if profit >= s.min_net:
                out.append(dict(item_id=item_id, name=info.get("name", f"#{item_id}"), buy=agg.min_price,
                                value=value, profit=profit))
            break
    return sorted(out, key=lambda r: (-r["profit"], r["item_id"]))
