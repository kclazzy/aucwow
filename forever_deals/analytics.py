"""Аналитика для дашбордов: сводки по всем товарам и по профессиям. Чистые функции, без tkinter."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .core import reset_opportunity

TOP_BEST = 5


@dataclass(frozen=True)
class Summary:
    name: str
    total: int            # всего кандидатов
    profitable: int       # прошли фильтры
    rejected: int
    epd_total: float      # ожидаемая прибыль в день по выгодным, меди
    invest: int           # сколько вложить в закупку у вендоров, меди (материалы не считаются: это не покупка)
    avg_markup: float     # средняя наценка выгодных
    best: tuple           # лучшие выгодные позиции (Evaluation), по прибыли в день


def summarize(name: str, evals) -> Summary:
    evals = list(evals)
    ok = sorted((e for e in evals if not e.rejects), key=lambda e: (-e.epd, -e.roi, e.cand.item_id))
    invest = sum(e.qty * e.cand.buy_price for e in ok if e.cand.buy_source == "vendor")
    marks = [e.markup for e in ok if e.markup != float("inf")]
    return Summary(name=name, total=len(evals), profitable=len(ok), rejected=len(evals) - len(ok),
                   epd_total=sum(e.epd for e in ok), invest=invest,
                   avg_markup=sum(marks) / len(marks) if marks else 0, best=tuple(ok[:TOP_BEST]))


def _all(res):
    return list(res.ranked) + list(res.rejected)


def overall(res) -> Summary:
    return summarize("Общая", _all(res))


def by_profession(res):
    """Сводки по профессиям, лучшие по прибыли в день первыми; профессии без кандидатов не показываем."""
    groups = {}
    for e in _all(res):
        groups.setdefault(e.cand.profession, []).append(e)
    rows = [summarize(name, evs) for name, evs in groups.items()]
    return sorted(rows, key=lambda r: (-r.epd_total, -r.profitable, r.name))


def reason_key(reason: str) -> str:
    """Причина отказа без чисел, чтобы однотипные отказы складывались в одну строку."""
    if reason.startswith("наценка"):
        return "наценка ниже минимума"
    return re.split(r"\s*[\(:]", reason, maxsplit=1)[0].strip()


def reason_histogram(res):
    """[(причина, сколько раз)] по убыванию."""
    c = Counter(reason_key(r) for e in res.rejected for r in e.rejects)
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))


def shortage_rows(res, limit: int = 15):
    """Позиции, которых на аукционе хватит на меньше всего дней (дефицит): по возрастанию запаса."""
    rows = [e for e in list(res.ranked) + list(res.rejected) if e.stock_days is not None]
    return sorted(rows, key=lambda e: (e.stock_days, e.cand.item_id))[:limit]


def reset_rows(res, s, limit: int = 15):
    """Возможности сброса рынка: что выкупить и перевыставить по обычной (или рыночной) цене. Лучшие по прибыли первыми."""
    out = []
    for e in list(res.ranked) + list(res.rejected):
        c = e.cand
        target = c.usual_price or c.market_price
        lots = res.listings.get(c.item_id)
        if not target or not lots:
            continue
        r = reset_opportunity(lots, target, s.cut, s.min_net, s.budget_item)
        if r.units > 0 and r.profit > 0:
            days = r.units / c.sales_per_day if c.sales_per_day else None
            out.append(dict(item_id=c.item_id, name=c.name, units=r.units, cost=r.cost, target=target,
                            profit=r.profit, days_to_sell=days))
    return sorted(out, key=lambda r: (-r["profit"], r["item_id"]))[:limit]


def snipe_rows(res, s, limit: int = 15):
    """Снайпер: лоты заметно дешевле обычной цены (по истории). Лучшие по прибыли первыми."""
    from .core import snipe_opportunity
    out = []
    for item_id, usual in res.usual.items():
        lots = res.listings.get(item_id)
        if not lots:
            continue
        r = snipe_opportunity(lots, usual, s.cut, s.snipe_pct, s.min_net, s.budget_item)
        if r.units > 0 and r.profit > 0:
            out.append(dict(item_id=item_id, name=res.all_names.get(item_id, f"#{item_id}"), units=r.units, cost=r.cost,
                            best=r.best, usual=usual, discount=r.discount, profit=r.profit))
    return sorted(out, key=lambda r: (-r["profit"], r["item_id"]))[:limit]
