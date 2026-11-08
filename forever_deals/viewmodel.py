"""Данные для таблиц окна без tkinter: сортировка, фильтр, проценты, строки. Тестируется отдельно."""
from __future__ import annotations

import re

from .core import fmt_money, parse_money
from .report import shopping_route

TOP_COLS = ["#", "Товар", "Категория", "Закупка", "Продажа", "Чистыми/шт", "Наценка", "ROI",
            "Продаж/день", "Брать, шт", "Прибыль/день", "Метки"]
TOP_WIDTHS = [30, 230, 140, 75, 85, 100, 70, 50, 105, 80, 115, 150]
VENDOR_COLS = ["Товар", "Вендор (NPC)", "Расположение", "Закупка", "Продажа", "Наценка", "Чистыми/шт",
               "Продаж/день", "Лотов", "Статус"]
ROUTE_COLS = ["Вендор / товар", "Кол-во", "Цена", "Сумма", "Прибыль"]
ROUTE_WIDTHS = [520, 70, 90, 100, 100]
VENDOR_WIDTHS = [190, 160, 240, 75, 90, 70, 90, 85, 55, 230]


def sort_key(text: str):
    """Ключ сортировки ячейки: числа (деньги, ×наценка, просто числа) < текст; «н/д» и «—» самые малые."""
    t = str(text).strip()
    if t in ("", "—", "н/д"):
        return (0, float("-inf"))
    if t.startswith("×"):
        try:
            return (0, float(t[1:]))
        except ValueError:
            pass
    try:
        return (0, float(t.replace(",", ".")))
    except ValueError:
        pass
    if re.fullmatch(r"-?(\d+\s*[зсм]\s*)+", t):
        neg = t.startswith("-")
        return (0, float((-1 if neg else 1) * parse_money(t.lstrip("-"))))
    return (1, t.lower())


def filter_rows(rows, text: str):
    q = text.strip().lower()
    if not q:
        return list(rows)
    return [r for r in rows if any(q in str(c).lower() for c in r)]


def to_percent(frac: float) -> str:
    v = round(frac * 100, 2)
    return str(int(v)) if v == int(v) else str(v)


def from_percent(text: str) -> float:
    v = float(text.replace(",", ".").strip())
    if not 0 <= v <= 100:
        raise ValueError("процент должен быть от 0 до 100")
    return v / 100


def _rate(e):
    return "н/д" if e.cand.sales_per_day is None else f"{e.cand.sales_per_day * 1:.1f}"


def top_rows(res, items):
    out = []
    for n, e in enumerate(res.top, 1):
        c = e.cand
        v = items.get(c.item_id)
        roi = f"{e.roi:.1f}" if c.buy_source == "vendor" else "—"
        out.append(((c.item_id, v.npc_id if v else None),
                    (n, c.name, c.category, fmt_money(c.buy_price), fmt_money(e.sell_price), fmt_money(e.net),
                     f"×{e.markup:.1f}", roi, _rate(e), e.qty, fmt_money(round(e.epd)), "; ".join(e.flags) or "—")))
    return out


def vendor_rows(res, items):
    out = []
    for e in res.vendor_rows:
        c = e.cand
        v = items.get(c.item_id)
        has = bool(c.min_price)
        out.append(((c.item_id, v.npc_id if v else None),
                    (c.name, c.vendor_name or (f"NPC {v.npc_id}" if v and v.npc_id else "—"), c.location or "—",
                     fmt_money(c.buy_price), fmt_money(e.sell_price) if has else "—", f"×{e.markup:.1f}" if has else "—",
                     fmt_money(e.net) if has else "—", _rate(e), c.n_auctions,
                     "✅ выгодно" if not e.rejects else "❌ " + "; ".join(e.rejects))))
    return out


def route_tree(res, items):
    """[(родитель(values), [(ids, values)...])]: вендор -> его товары для покупки."""
    tree = []
    for g in shopping_route(res, items):
        place = f"{g['vendor']}" + (f" — {g['location']}" if g["location"] else "")
        parent = (place, "", "", fmt_money(g["total"]), fmt_money(g["profit"]))
        kids = [((r["item_id"], g["npc_id"]), (r["name"], r["qty"], fmt_money(r["unit"]), fmt_money(r["cost"]), fmt_money(r["profit"])))
                for r in g["rows"]]
        tree.append((parent, kids))
    return tree
