"""Отчёт на русском в Markdown: цены, расчёты, ссылки."""
from __future__ import annotations

from datetime import datetime

from . import analytics, theme
from .core import Settings, fmt_money
from .links import item_url, md_link, npc_url


def _rate(e):
    return "н/д" if e.cand.sales_per_day is None else f"{e.cand.sales_per_day:.1f}"


def _buy_text(e):
    return "вендор" if e.cand.buy_source == "vendor" else "цена вендору (альтернатива)"


def _roi(e):
    return f"{e.roi:.1f}" if e.cand.buy_source == "vendor" else "—"


def shopping_route(res, vendor_items=None):
    """Список закупки по вендорам: [{vendor, location, npc_id, rows:[...], total, profit}], лучшие вендоры первыми."""
    vendor_items = vendor_items or {}
    groups = {}
    for e in res.ranked:
        c = e.cand
        if c.group != "vendor" or e.qty <= 0:
            continue
        v = vendor_items.get(c.item_id)
        key = (c.vendor_name or "Вендор не указан", c.location)
        g = groups.setdefault(key, dict(vendor=key[0], location=key[1], npc_id=v.npc_id if v else None, rows=[], total=0, profit=0))
        cost = e.qty * c.buy_price
        g["rows"].append(dict(item_id=c.item_id, name=c.name, qty=e.qty, unit=c.buy_price, cost=cost, profit=e.qty * e.net))
        g["total"] += cost
        g["profit"] += e.qty * e.net
    out = sorted(groups.values(), key=lambda g: -g["profit"])
    for g in out:
        g["rows"].sort(key=lambda r: -r["profit"])
    return out


def route_text(route) -> str:
    L = []
    for g in route:
        L.append(f"{g['vendor']}" + (f" — {g['location']}" if g["location"] else "") + f" (на {fmt_money(g['total'])})")
        for r in g["rows"]:
            L.append(f"  • {r['name']} × {r['qty']} по {fmt_money(r['unit'])} = {fmt_money(r['cost'])}")
    return "\n".join(L)


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
          "| # | Товар | Категория | Закупка | Продажа | Чистыми/шт | Наценка | ROI | Продаж/день | Запас, дн. | Брать, шт | Выставлять по | Прибыль/день | Метки |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, e in enumerate(res.top, 1):
        c = e.cand
        L.append(f"| {n} | {md_link(c.name, item_url(c.item_id, base))} | {c.category} | {fmt_money(c.buy_price)} | "
                 f"{fmt_money(e.sell_price)} | {fmt_money(e.net)} | ×{e.markup:.1f} | {_roi(e)} | {_rate(e)} | "
                 f"{'н/д' if e.stock_days is None else '%.1f' % e.stock_days} | {e.qty} | {fmt_money(e.list_price)} | {fmt_money(round(e.epd))} | {'; '.join(e.flags) or '—'} |")
    if not res.top:
        L.append("| — | Нет позиций, прошедших фильтры | | | | | | | | | | | | |")
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

    L += ["## Аналитика по профессиям", "",
          "Профессия: у рецептов — чей это рецепт, у материалов — откуда сырьё (подклассы предметов как в Retail, для Forever не подтверждены).", "",
          "| Профессия | Позиций | Выгодных | Прибыль/день | Вложить | Средняя наценка | Лучший товар |", "|---|---|---|---|---|---|---|"]
    for r in analytics.by_profession(res):
        best = r.best[0].cand.name if r.best else "—"
        L.append(f"| {r.name} | {r.total} | {r.profitable} | {fmt_money(round(r.epd_total))} | {fmt_money(r.invest)} | "
                 f"{'×%.1f' % r.avg_markup if r.profitable else '—'} | {best} |")
    L.append("")

    route = shopping_route(res, vendor_items)
    L += ["## Маршрут закупки", "", "Что купить и у кого, сгруппировано по вендорам (только позиции, прошедшие фильтры).", ""]
    if route:
        for g in route:
            who = g["vendor"]
            if g["npc_id"]:
                who = md_link(who, npc_url(g["npc_id"], base))
            L += [f"**{who}**" + (f" — {g['location']}" if g["location"] else "") + f" · на {fmt_money(g['total'])}, ожидаемая прибыль {fmt_money(g['profit'])}", ""]
            for r in g["rows"]:
                L.append(f"- {md_link(r['name'], item_url(r['item_id'], base))} × {r['qty']} по {fmt_money(r['unit'])} = {fmt_money(r['cost'])}")
            L.append("")
    else:
        L += ["Пока нечего закупать: нет вендорных позиций, прошедших фильтры.", ""]

    maybe = [e for e in res.ranked if any(f.startswith("возможно продаётся NPC") for f in e.flags)][:10]
    if maybe:
        L += ["## Возможные вендорные товары (не подтверждено)", "",
              "У этих предметов в API указана цена покупки, а на аукционе они дороже минимум в несколько раз. "
              "Проверьте на Wowhead, продаёт ли их NPC, и внесите в «Вендоры».", "",
              "| Товар | Цена в API | Продажа | Наценка |", "|---|---|---|---|"]
        for e in maybe:
            c = e.cand
            L.append(f"| {md_link(c.name, item_url(c.item_id, base))} | {fmt_money(c.api_buy_price)} | {fmt_money(e.sell_price)} | ×{e.sell_price / c.api_buy_price:.1f} |")
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

    L += ["## Как читать", "",
          "- **Наценка** — во сколько раз цена продажи выше закупки. **ROI** — чистая прибыль, делённая на закупку (у материалов не считается: «закупка» там цена продажи вендору).",
          "- **Чистыми/шт** — после комиссии аукциона и ожидаемой потери депозита. **Брать** — сколько штук купить: меньшее из бюджета, остатка у вендора и спроса за сутки.",
          "- **Прибыль/день** — продаж в день × ваша доля × чистыми с шт. По этому столбцу отсортирован топ.",
          "- Метка «мало истории» и «нет истории продаж» значит, что скорость продаж оценочная: первые дни опирайтесь на цены, а не на порядок в топе.", "",
          "## Допущения", "",
          f"- Комиссия аукциона {s.cut:.0%} (для выбранного аукциона; задаётся в настройках), депозит {s.deposit_pct:.0%} от цены вендору за {s.deposit_hours} ч — гипотезы из Classic Era, сверьте с первым чеком.",
          f"- Продажи в день умножены на {s.sales_haircut:.0%}: убыль лотов включает отмены и перевыставления. Изолированные лоты (меньше {s.min_quantity} шт.) отклоняются.",
          f"- Вероятность продажи {s.p_sell:.0%}, ваша доля рынка {s.share:.0%}. Продажи в день — оценка по убыли лотов, отмены считаются продажами.",
          "- Пока нет истории, скорость продаж не известна и ранжирование идёт по прибыли с единицы при минимальном спросе из настроек.",
          "", "## Источники", ""]
    for name, url in res.sources:
        L.append(f"- {name}: {url}")
    L += [f"- Wowhead (предметы и NPC): {base} (формат ссылок /item=ID и /npc=ID не подтверждён; при ошибке поменяйте адрес в настройках)",
          "- Сверка цен вручную: https://forevermastery.com/en/prices", ""]
    return "\n".join(L)


def markdown_to_html(md: str, title: str = "Отчёт WoW Forever") -> str:
    """Минимальный конвертер для нашего Markdown: заголовки, таблицы, списки, цитаты, **жирный**, ссылки."""
    import html as _h
    import re

    def inline(t):
        t = _h.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank">\1</a>', t)

    out, lines, i = [], md.split("\n"), 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|"):
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append(lines[i])
                i += 1
            rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in block]
            rows = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]
            out.append("<table>")
            for n, r in enumerate(rows):
                tag = "th" if n == 0 else "td"
                out.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in r) + "</tr>")
            out.append("</table>")
            continue
        m = re.match(r"(#{1,3}) (.*)", ln)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
        elif ln.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif ln.startswith("> "):
            out.append(f"<blockquote>{inline(ln[2:])}</blockquote>")
        elif ln.strip():
            out.append(f"<p>{inline(ln)}</p>")
        i += 1
    P = theme.P
    css = (f"body{{font-family:Segoe UI,Arial,sans-serif;max-width:1250px;margin:0 auto;padding:0 20px 40px;background:{P['bg']};color:{P['text']}}}"
           f"h1{{background:{P['header_bg']};color:{P['header_fg']};margin:0 -20px 16px;padding:22px 20px;font-size:24px}}"
           f"h2{{margin:28px 0 8px;padding-bottom:4px;border-bottom:2px solid {P['accent']};font-size:19px}}"
           f"table{{border-collapse:collapse;margin:8px 0;font-size:14px;background:{P['card']};width:100%}}"
           f"th,td{{border:1px solid {P['border']};padding:6px 10px;text-align:left}}"
           f"th{{background:{P['header_bg']};color:{P['header_fg']}}}tr:nth-child(even) td{{background:{P['zebra']}}}"
           f"blockquote{{background:#fff3cd;margin:8px 0;padding:10px 14px;border-left:4px solid #f59e0b}}"
           f"a{{color:{P['accent']}}}li{{margin:3px 0}}")
    return (f"<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"utf-8\"><title>{_h.escape(title)}</title>"
            f"<style>{css}</style></head><body>" + "\n".join(out) + "</body></html>")
