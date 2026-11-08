"""Данные для таблиц окна без tkinter: сортировка, фильтр, проценты, строки. Тестируется отдельно."""
from __future__ import annotations

import re

from .core import fmt_money, parse_money
from .report import shopping_route

TOP_COLS = ["#", "Товар", "Категория", "Закупка", "Продажа", "Чистыми/шт", "Наценка", "ROI",
            "Продаж/день", "Запас, дн.", "Брать, шт", "Выставлять по", "Прибыль/день", "Метки"]
TOP_WIDTHS = [30, 200, 120, 75, 90, 100, 75, 50, 95, 80, 80, 120, 110, 110]
SHORT_COLS = ["Товар", "Профессия", "Лотов, шт.", "Продаж/день", "Запас, дн.", "Цена сейчас", "Выставлять по"]
SHORT_WIDTHS = [260, 140, 90, 100, 90, 110, 120]
RESET_COLS = ["Товар", "Выкупить, шт.", "Затраты", "Перевыставить по", "Прибыль", "Дней на продажу"]
RESET_WIDTHS = [260, 110, 110, 140, 120, 130]
CRAFT_COLS = ["Изделие", "Профессия", "Реагенты", "Себестоимость", "Выручка", "Прибыль", "ROI", "Примечание"]
CRAFT_WIDTHS = [190, 120, 260, 100, 90, 100, 60, 210]
DE_COLS = ["Предмет", "Цена покупки", "Ценность дизенчанта", "Прибыль"]
DE_WIDTHS = [300, 130, 170, 130]
ARB_COLS = ["Товар", "Купить на", "Цена", "Продать на", "Цена", "Чистыми/шт", "Брать, шт.", "Прибыль"]
ARB_WIDTHS = [220, 130, 90, 130, 90, 100, 90, 110]
VENDOR_COLS = ["Товар", "Вендор (NPC)", "Расположение", "Закупка", "Продажа", "Наценка", "Чистыми/шт",
               "Продаж/день", "Лотов", "Статус"]
PROF_COLS = ["Товар", "Тип", "Закупка", "Продажа", "Чистыми/шт", "Продаж/день", "Прибыль/день", "Статус"]
PROF_WIDTHS = [230, 130, 80, 90, 100, 90, 110, 300]
ROUTE_COLS = ["Вендор / товар", "Кол-во", "Цена", "Сумма", "Прибыль"]
ROUTE_WIDTHS = [520, 70, 90, 100, 100]
VENDOR_WIDTHS = [190, 150, 230, 80, 95, 85, 110, 110, 65, 200]


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


def _days(e):
    return "н/д" if e.stock_days is None else f"{e.stock_days:.1f}"


def top_rows(res, items):
    out = []
    for n, e in enumerate(res.top, 1):
        c = e.cand
        v = items.get(c.item_id)
        roi = f"{e.roi:.1f}" if c.buy_source == "vendor" else "—"
        out.append(((c.item_id, v.npc_id if v else None),
                    (n, c.name, c.category, fmt_money(c.buy_price), fmt_money(e.sell_price), fmt_money(e.net),
                     f"×{e.markup:.1f}", roi, _rate(e), _days(e), e.qty, fmt_money(e.list_price), fmt_money(round(e.epd)),
                     "; ".join(e.flags) or "—")))
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


def bar_lengths(values, width: int):
    """Длины столбиков диаграммы в пикселях: самый большой = width, отрицательные не рисуются."""
    top = max((v for v in values if v > 0), default=0)
    return [int(round(width * v / top)) if top and v > 0 else 0 for v in values]


def profession_rows(res, items, name):
    """Все позиции профессии: выгодные по прибыли в день, затем отклонённые с причиной."""
    evs = [e for e in list(res.ranked) + list(res.rejected) if e.cand.profession == name]
    evs.sort(key=lambda e: (bool(e.rejects), -e.epd if not e.rejects else 0, e.cand.item_id))
    out = []
    for e in evs:
        c = e.cand
        v = items.get(c.item_id)
        has = bool(c.min_price)
        out.append(((c.item_id, v.npc_id if v else None),
                    (c.name, c.category, fmt_money(c.buy_price), fmt_money(e.sell_price) if has else "—",
                     fmt_money(e.net) if has else "—", _rate(e), fmt_money(round(e.epd)) if not e.rejects else "—",
                     "✅ выгодно" if not e.rejects else "❌ " + "; ".join(e.rejects))))
    return out


def row_tag(status: str, index: int) -> str:
    """Тег раскраски строки: статус (✅/❌) важнее полос."""
    if status.startswith("✅"):
        return "ok"
    if status.startswith("❌"):
        return "bad"
    return "odd" if index % 2 else "even"


def line_points(values, width: int, height: int, pad: int = 12):
    """Координаты точек линейного графика. None пропускается, но место по оси X сохраняется.
    Минимум внизу, максимум вверху; постоянный ряд рисуется по центру."""
    n = len(values)
    known = [v for v in values if v is not None]
    if not known:
        return []
    lo, hi = min(known), max(known)
    out = []
    for i, v in enumerate(values):
        if v is None:
            continue
        x = pad if n == 1 else pad + (width - 2 * pad) * i / (n - 1)
        y = height / 2 if hi == lo else height - pad - (height - 2 * pad) * (v - lo) / (hi - lo)
        out.append((int(round(x)), int(round(y))))
    return out


def shortage_table(res):
    from . import analytics
    return [((e.cand.item_id, None), (e.cand.name, e.cand.profession, e.cand.quantity, _rate(e), _days(e),
                                      fmt_money(e.cand.min_price), fmt_money(e.list_price)))
            for e in analytics.shortage_rows(res)]


def reset_table(res, s):
    from . import analytics
    return [((r["item_id"], None), (r["name"], r["units"], fmt_money(r["cost"]), fmt_money(r["target"]), fmt_money(r["profit"]),
                                    "н/д" if r["days_to_sell"] is None else f"{r['days_to_sell']:.1f}"))
            for r in analytics.reset_rows(res, s)]


def craft_table(res):
    out = []
    for row in res.craft_rows:
        r = row.recipe
        name = res.names.get(r.product) or r.name or f"#{r.product}"
        reagents = ", ".join(f"{res.names.get(i, f'#{i}')} ×{q}" for i, q in r.reagents)
        note = "нет цены: " + ", ".join(res.names.get(i, f"#{i}") for i in row.unknown) if row.unknown else "—"
        out.append(((r.product, None), (name, r.profession, reagents, fmt_money(row.cost),
                                        fmt_money(row.revenue) if row.profit is not None else "—",
                                        fmt_money(row.profit) if row.profit is not None else "—",
                                        f"{row.roi:.1f}" if row.roi is not None else "—", note)))
    return out


def de_table(res):
    return [((r["item_id"], None), (r["name"], fmt_money(r["buy"]), fmt_money(r["value"]), fmt_money(r["profit"])))
            for r in res.de_rows]


def arb_table(res):
    return [((r["item_id"], None), (r["name"], r["buy_house"], fmt_money(r["buy"]), r["sell_house"], fmt_money(r["sell"]),
                                    fmt_money(r["net"]), r["qty"], fmt_money(r["profit"])))
            for r in res.arb_rows]
