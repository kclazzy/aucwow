"""Отчёт на русском в Markdown: цены, расчёты, ссылки."""
from __future__ import annotations

from datetime import datetime

from .core import Settings, fmt_money
from .links import item_url, md_link, npc_url


def _rate(e):
    return "н/д" if e.cand.sales_per_day is None else f"{e.cand.sales_per_day:.1f}"


def _buy_text(e):
    return "вендор" if e.cand.buy_source == "vendor" else "цена вендору (альтернатива)"


def vendor_place(e, base):
    c = e.cand
    parts = []
    if c.vendor_name:
        parts.append(c.vendor_name)
    if c.location:
        parts.append(c.location)
    return ", ".join(parts) or "место не указано"


def vendor_cell(c, v, base) -> str:
    """Ячейка «Где купить»: имя NPC (ссылка на Wowhead, если известен npc_id) и место."""
    name = c.vendor_name or (f"NPC {v.npc_id}" if v and v.npc_id else "")
    if v and v.npc_id and name:
        name = md_link(name, npc_url(v.npc_id, base))
    return ", ".join(x for x in (name, c.location) if x) or "место не указано"


def calc_line(e, s: Settings) -> str:
    c = e.cand
    after = int(e.sell_price * (1 - s.cut))
    return (f"{fmt_money(e.sell_price)} × (1 − {s.cut:.0%}) = {fmt_money(after)}; "
            f"− закупка {fmt_money(c.buy_price)} − ожидаемая потеря депозита {fmt_money(round(e.deposit_loss))} "
            f"= **{fmt_money(e.net)}** чистыми с шт.; ROI {e.roi:.1f}; наценка ×{e.markup:.1f}")


def build_markdown(res, s: Settings, vendor_items: dict, now=None, demo=False, wowhead_base=None) -> str:
    from .links import WOWHEAD
    base = wowhead_base or WOWHEAD
    ts = datetime.fromtimestamp(res.meta.get("ts", 0))
    L = [f"# 💰 Выгодные товары WoW Forever — {ts:%d.%m.%Y %H:%M}", ""]
    if demo:
        L += ["> ⚠️ **ДЕМО-ДАННЫЕ.** Предметы, цены и ссылки вымышлены, только для проверки интерфейса.", ""]
    m = res.meta
    L += [f"Аукцион: реалм {m.get('realm')}, аукцион {m.get('house')}. Предметов на аукционе: {m.get('items_on_ah')}, "
          f"проверено кандидатов: {m.get('candidates')}, максимум истории: {m.get('max_history')} дн.", ""]
    for w in res.warnings:
        L.append(f"- ⚠️ {w}")
    if res.warnings:
        L.append("")

    L += [f"## Топ-{s.top_n}", "",
          "| # | Товар | Категория | Закупка | Продажа | Чистыми/шт | ROI | Продаж/день | Брать | Метки |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for n, e in enumerate(res.top, 1):
        c = e.cand
        L.append(f"| {n} | {md_link(c.name, item_url(c.item_id, base))} | {c.category} | {fmt_money(c.buy_price)} | "
                 f"{fmt_money(e.sell_price)} | {fmt_money(e.net)} | {e.roi:.1f} | {_rate(e)} | {e.qty} | {'; '.join(e.flags) or '—'} |")
    if not res.top:
        L.append("| — | Нет позиций, прошедших фильтры | | | | | | | | |")
    L.append("")

    L += ["## Вендор → аукцион", "",
          "Товары, которые покупаются у NPC и продаются на аукционе. Список вендоров вносите сами (в API Blizzard его нет).", "",
          "| Товар | Где купить | Закупка | Продажа | Наценка | Чистыми/шт | Продаж/день | Лотов | Статус |",
          "|---|---|---|---|---|---|---|---|---|"]
    for e in res.vendor_rows:
        c = e.cand
        v = vendor_items.get(c.item_id)
        where = vendor_cell(c, v, base)
        status = "✅ в топе" if not e.rejects and e in res.top else ("✅ выгодно" if not e.rejects else "❌ " + "; ".join(e.rejects))
        mark = f"×{e.markup:.1f}" if c.min_price else "—"
        L.append(f"| {md_link(c.name, item_url(c.item_id, base))} | {where} | {fmt_money(c.buy_price)} | "
                 f"{fmt_money(e.sell_price) if c.min_price else '—'} | {mark} | {fmt_money(e.net) if c.min_price else '—'} | "
                 f"{_rate(e)} | {c.n_auctions} | {status} |")
    if not res.vendor_rows:
        L.append("| Вендорных позиций нет — импортируйте список (кнопка «Вендоры») | | | | | | | | |")
    L.append("")

    for title in ("Рецепт", "Ткань", "Кожа", "Руда и камень", "Трава"):
        rows = res.by_category.get(title, [])[:5]
        if rows:
            L += [f"## {title}: лучшие позиции", "",
                  "| Товар | Цена вендору | Продажа | Чистыми/шт | Продаж/день | Метки |", "|---|---|---|---|---|---|"]
            for e in rows:
                c = e.cand
                L.append(f"| {md_link(c.name, item_url(c.item_id, base))} | {fmt_money(c.buy_price)} | {fmt_money(e.sell_price)} | "
                         f"{fmt_money(e.net)} | {_rate(e)} | {'; '.join(e.flags) or '—'} |")
            L.append("")

    L += ["## Расчёты по топу", ""]
    for n, e in enumerate(res.top, 1):
        c = e.cand
        L += [f"**{n}. {c.name}** ({c.category}, закупка: {_buy_text(e)})", "",
              f"- Расчёт: {calc_line(e, s)}",
              f"- Рынок: {c.n_auctions} лотов, {c.quantity} шт.; продаж в день: {_rate(e)} (оценка); рекомендовано брать: {e.qty} шт., ожидаемая прибыль {fmt_money(round(e.epd))} в день",
              f"- Место закупки: {vendor_place(e, base) if c.buy_source == 'vendor' else 'не требуется (материал/рецепт: сравнение с продажей вендору)'}",
              f"- Источник: {md_link('Wowhead', item_url(c.item_id, base))}", ""]

    L += ["## Допущения", "",
          f"- Комиссия аукциона {s.cut:.0%} и депозит {s.deposit_pct:.0%} от цены вендору за {s.deposit_hours} ч — гипотезы из Classic Era, сверьте с первым чеком.",
          f"- Вероятность продажи {s.p_sell:.0%}, ваша доля рынка {s.share:.0%}. Продажи в день — оценка по убыли лотов, отмены считаются продажами.",
          "- Пока нет истории, скорость продаж не известна и ранжирование идёт по прибыли с единицы при минимальном спросе из настроек.",
          "", "## Источники", ""]
    for name, url in res.sources:
        L.append(f"- {name}: {url}")
    L += [f"- Wowhead (предметы и NPC): {base}",
          "- Сверка цен вручную: https://forevermastery.com/en/prices", ""]
    return "\n".join(L)
