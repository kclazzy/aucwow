"""Аналитика для дашбордов: сводки по всем товарам и по профессиям. Чистые функции, без tkinter."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

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
