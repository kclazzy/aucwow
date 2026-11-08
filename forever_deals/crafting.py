"""Прибыль крафта: рецепты вносит пользователь (в API Forever рецептов с реагентами может не быть)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .core import Settings


@dataclass(frozen=True)
class Recipe:
    product: int
    qty: int = 1                      # сколько штук даёт один крафт
    reagents: tuple = ()              # ((item_id, количество), ...)
    profession: str = "Прочее"
    name: str = ""


@dataclass(frozen=True)
class CraftRow:
    recipe: Recipe
    cost: int
    revenue: int
    profit: Optional[int]             # None: не хватает цен
    roi: Optional[float]
    unknown: tuple                    # предметы без цены
    sell: int = 0


def _item_id(text: str) -> int:
    m = re.search(r"item=(\d+)", text) or re.fullmatch(r"\s*(\d+)\s*", text)
    if not m:
        raise ValueError(f"не нашёл ID предмета в {text!r}")
    return int(m.group(1))


def _reagent(token: str):
    m = re.search(r"(\d+)\s*:\s*(\d+)\s*$", token)
    if m:
        return int(m.group(1)), int(m.group(2))
    return _item_id(token), 1


def parse_text(text: str):
    """Строки: товар ; кол-во ; реагент:кол-во, реагент:кол-во ; профессия ; название. -> ({product: Recipe}, ошибки)"""
    recipes, errors = {}, []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        f = [x.strip() for x in line.split(";")] + [""] * 5
        try:
            reagents = tuple(_reagent(t) for t in f[2].split(",") if t.strip())
            if not reagents:
                raise ValueError("нет реагентов")
            r = Recipe(_item_id(f[0]), int(f[1] or 1), reagents, f[3] or "Прочее", f[4])
            if r.qty <= 0:
                raise ValueError("количество должно быть > 0")
            recipes[r.product] = r
        except (ValueError, TypeError) as exc:
            errors.append(f"строка {n}: {exc}")
    return recipes, errors


def load(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    rows = json.loads(p.read_text(encoding="utf-8")).get("recipes", [])
    return {r["product"]: Recipe(r["product"], r["qty"], tuple(tuple(x) for x in r["reagents"]), r["profession"], r["name"])
            for r in rows}


def save(path, recipes: dict):
    rows = [dict(product=r.product, qty=r.qty, reagents=[list(x) for x in r.reagents], profession=r.profession, name=r.name)
            for r in sorted(recipes.values(), key=lambda r: r.product)]
    Path(path).write_text(json.dumps({"recipes": rows}, ensure_ascii=False, indent=2), encoding="utf-8")


def craft_profit(recipe: Recipe, prices: dict, vendor_buy: dict, usual: dict, s: Settings) -> CraftRow:
    """Себестоимость: каждый реагент по меньшей из цены аукциона и цены у вендора. Продажа — как в основной модели."""
    cost, unknown = 0, []
    for item, qty in recipe.reagents:
        options = [p for p in (prices[item].min_price if item in prices else None, vendor_buy.get(item)) if p]
        if options:
            cost += qty * min(options)
        else:
            unknown.append(item)
    agg = prices.get(recipe.product)
    if not agg or not agg.min_price:
        unknown.append(recipe.product)
    if unknown:
        return CraftRow(recipe, cost, 0, None, None, tuple(unknown))
    sell = min(agg.min_price, usual[recipe.product]) if usual.get(recipe.product) else agg.min_price
    revenue = int(sell * recipe.qty * (1 - s.cut))
    profit = revenue - cost
    return CraftRow(recipe, cost, revenue, profit, profit / cost if cost else None, (), sell)


def rank(rows):
    return sorted(rows, key=lambda r: (r.profit is None, -(r.profit or 0), r.recipe.product))
