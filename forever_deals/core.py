"""Чистое ядро: деньги, расчёт выгоды, ранжирование, оценка продаж. Без сети и GUI."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

DAY = 86400


def fmt_money(copper: int) -> str:
    copper = int(round(copper))
    sign = "-" if copper < 0 else ""
    copper = abs(copper)
    g, rest = divmod(copper, 10000)
    s, c = divmod(rest, 100)
    parts = []
    if g:
        parts.append(f"{g}з")
    if s:
        parts.append(f"{s}с")
    if c or not parts:
        parts.append(f"{c}м")
    return sign + " ".join(parts)


@dataclass(frozen=True)
class Settings:
    cut: float = 0.05            # комиссия аукциона (гипотеза из Classic Era, проверить)
    deposit_pct: float = 0.05    # депозит от цены продажи вендору за 12 ч (гипотеза)
    deposit_hours: int = 12
    p_sell: float = 0.7          # вероятность продать за срок лота
    share: float = 0.5           # ваша доля рыночных продаж
    horizon_days: float = 1.0
    min_net: int = 50            # меди
    min_roi: float = 1.0
    min_rate: float = 3.0        # шт/день
    min_markup: float = 10.0     # для вендорных: наценка не меньше
    budget_item: int = 50000     # меди на позицию
    top_n: int = 10
    min_quantity: int = 3        # меньше штук на аукционе = изолированный лот, цене не верим
    sales_haircut: float = 0.7   # оценка по убыли лотов завышена (отмены, перевыставления): берём долю


@dataclass
class Candidate:
    item_id: int
    name: str
    group: str                   # "vendor" | "recipe" | "material"
    category: str                # подпись: "Перепродажа NPC", "Руда"...
    buy_price: int               # закупка (вендор) или альтернатива (цена вендору)
    buy_source: str              # "vendor" | "opportunity"
    min_price: Optional[int]
    market_price: Optional[int]
    vendor_sell: int = 0
    quantity: int = 0
    n_auctions: int = 0
    sales_per_day: Optional[float] = None
    history_days: int = 0
    usual_price: Optional[int] = None
    stock: Optional[int] = None  # остаток у вендора, None = без ограничения
    vendor_name: str = ""
    location: str = ""
    api_buy_price: int = 0       # цена покупки из API предмета (не подтверждает, что предмет продаёт NPC)


@dataclass
class Evaluation:
    cand: Candidate
    sell_price: int = 0
    net: int = 0
    roi: float = 0.0
    markup: float = 0.0
    rate_used: float = 0.0
    epd: float = 0.0
    qty: int = 0
    deposit_loss: float = 0.0
    flags: list = field(default_factory=list)
    rejects: list = field(default_factory=list)


def evaluate(c: Candidate, s: Settings) -> Evaluation:
    e = Evaluation(cand=c)
    if not c.min_price or c.quantity <= 0:
        e.rejects.append("нет лотов на аукционе")
        return e
    real_purchase = c.buy_source == "vendor"
    if not real_purchase and c.vendor_sell <= 0:
        e.rejects.append("нет цены вендору: не с чем сравнивать")
    e.sell_price = min(c.min_price, c.usual_price) if c.usual_price else c.min_price
    deposit = s.deposit_pct * c.vendor_sell * (s.deposit_hours / 12)
    e.deposit_loss = deposit * (1 - s.p_sell)
    e.net = int(e.sell_price * (1 - s.cut) - c.buy_price - e.deposit_loss)
    e.roi = e.net / c.buy_price if c.buy_price > 0 else float("inf")
    e.markup = e.sell_price / c.buy_price if c.buy_price > 0 else float("inf")
    if c.sales_per_day is None:
        e.rate_used = s.min_rate
        e.flags.append("нет истории продаж")
    else:
        e.rate_used = c.sales_per_day * s.sales_haircut
        if c.history_days < 3:
            e.flags.append("мало истории")
    if c.usual_price is None:
        e.flags.append("нет обычной цены")
    if c.market_price and c.market_price > 2 * c.min_price:
        e.flags.append("дно рынка тоньше рыночной цены")
    if not real_purchase and c.api_buy_price and e.sell_price >= s.min_markup * c.api_buy_price:
        e.flags.append(f"возможно продаётся NPC (API: {fmt_money(c.api_buy_price)}), проверьте")
    e.epd = e.rate_used * s.share * e.net

    if c.quantity < s.min_quantity:
        e.rejects.append(f"изолированный лот ({c.quantity} шт.): цене не верим")
    if e.net < s.min_net:
        e.rejects.append(f"мала прибыль ({fmt_money(e.net)} на шт.)")
    if real_purchase and e.roi < s.min_roi:
        e.rejects.append(f"мала рентабельность (ROI {e.roi:.2f})")
    if c.sales_per_day is not None and e.rate_used < s.min_rate:
        e.rejects.append(f"тонкий рынок ({e.rate_used:.1f} шт/день)")
    if c.group == "vendor" and e.markup < s.min_markup:
        e.rejects.append(f"наценка ×{e.markup:.1f} меньше ×{s.min_markup:g}")

    by_budget = s.budget_item // c.buy_price if c.buy_price > 0 else 10**9
    by_demand = math.ceil(e.rate_used * s.share * s.horizon_days)
    caps = [by_budget, by_demand] + ([c.stock] if c.stock is not None else [])
    e.qty = max(0, int(min(caps)))
    return e


def rank(cands, s: Settings):
    evals = [evaluate(c, s) for c in cands]
    ok = [e for e in evals if not e.rejects]
    bad = [e for e in evals if e.rejects]
    ok.sort(key=lambda e: (-e.epd, -e.roi, e.cand.item_id))
    bad.sort(key=lambda e: e.cand.item_id)
    return ok, bad


@dataclass(frozen=True)
class Aggregate:
    min_price: Optional[int]
    market_price: Optional[int]
    quantity: int
    n_auctions: int


def aggregate_listings(listings) -> Aggregate:
    """listings: (цена за единицу в меди, количество). Рыночная = среднее по дешёвым 15% единиц."""
    rows = sorted((int(p), int(q)) for p, q in listings if p and p > 0 and q and q > 0)
    if not rows:
        return Aggregate(None, None, 0, 0)
    total = sum(q for _, q in rows)
    need = max(1, math.ceil(total * 0.15))
    left, cost = need, 0
    for p, q in rows:
        take = min(left, q)
        cost += take * p
        left -= take
        if left == 0:
            break
    return Aggregate(rows[0][0], cost // need, total, len(rows))


def estimate_sales_per_day(snaps):
    """snaps: [(ts, qty)] по возрастанию. Оценка = сумма падений количества / дни. Отмены считаются продажами."""
    snaps = sorted(snaps)
    if len(snaps) < 2:
        return None, 0.0
    span = (snaps[-1][0] - snaps[0][0]) / DAY
    if span < 0.25:
        return None, span
    drops = sum(max(0, a[1] - b[1]) for a, b in zip(snaps, snaps[1:]))
    return drops / span, span


def usual_price(daily_mins, min_days: int = 3) -> Optional[int]:
    vals = [v for v in daily_mins if v]
    if len(vals) < min_days:
        return None
    return int(statistics.median(vals))


def parse_money(text: str) -> int:
    """'1з 25с 3м', '1g 25s 3c' или просто число меди -> меди."""
    import re
    t = text.strip().lower().replace(",", ".")
    if re.fullmatch(r"\d+", t):
        return int(t)
    total, found = 0, False
    for num, unit in re.findall(r"(\d+)\s*([зgсsмmc])", t):
        found = True
        total += int(num) * {"з": 10000, "g": 10000, "с": 100, "s": 100}.get(unit, 1)
    if not found:
        raise ValueError(f"не понял сумму: {text!r}")
    return total
