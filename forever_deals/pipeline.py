"""Один прогон: аукцион -> снимок -> кандидаты -> ранжирование."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import arbitrage, crafting, disenchant
from .vendors import VendorItem
from .core import (DAY, Candidate, Settings, aggregate_listings, estimate_sales_per_day, fmt_money, rank, usual_price)

# ID классов предметов как в Retail; для Forever не подтверждены — меняются в config.json
CLASS_TRADE, CLASS_RECIPE = 7, 9
TRADE_SUB = {5: "Ткань", 6: "Кожа", 7: "Руда и камень", 9: "Трава"}


# Профессия по подклассу (ID как в Retail; для Forever не подтверждены, меняются в config.json: recipe_prof, trade_prof)
RECIPE_PROF = {1: "Кожевничество", 2: "Портняжное дело", 3: "Инженерное дело", 4: "Кузнечное дело", 5: "Кулинария",
               6: "Алхимия", 7: "Первая помощь", 8: "Наложение чар", 9: "Рыбалка", 10: "Ювелирное дело"}
TRADE_PROF = {1: "Инженерное дело", 2: "Инженерное дело", 3: "Инженерное дело", 4: "Ювелирное дело", 5: "Портняжное дело",
              6: "Кожевничество", 7: "Горное дело", 8: "Кулинария", 9: "Травничество", 12: "Наложение чар"}
OTHER = "Прочее"


def profession(info, cfg: dict) -> str:
    """Рецепт -> чья профессия; торговый товар -> из какой профессии сырьё; иначе «Прочее»."""
    if not info:
        return OTHER
    recipe = {int(k): v for k, v in (cfg.get("recipe_prof") or RECIPE_PROF).items()}
    trade = {int(k): v for k, v in (cfg.get("trade_prof") or TRADE_PROF).items()}
    _, class_recipe, _ = class_map(cfg)
    class_trade = class_map(cfg)[0]
    if info.get("class_id") == class_recipe:
        return recipe.get(info.get("subclass_id"), OTHER)
    if info.get("class_id") == class_trade:
        return trade.get(info.get("subclass_id"), OTHER)
    return OTHER


def class_map(cfg: dict):
    sub = {int(k): v for k, v in (cfg.get("trade_sub") or TRADE_SUB).items()}
    return int(cfg.get("class_trade", CLASS_TRADE)), int(cfg.get("class_recipe", CLASS_RECIPE)), sub


@dataclass
class Result:
    top: list = field(default_factory=list)
    ranked: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    vendor_rows: list = field(default_factory=list)     # все вендорные позиции, прошедшие и нет
    by_category: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    listings: dict = field(default_factory=dict)     # item_id -> [(цена, шт.)] для сброса рынка
    sources: list = field(default_factory=list)
    craft_rows: list = field(default_factory=list)
    de_rows: list = field(default_factory=list)
    arb_rows: list = field(default_factory=list)      # сравнение аукционов
    names: dict = field(default_factory=dict)         # id -> название для крафта
    prices: dict = field(default_factory=dict)        # id -> Aggregate по всему аукциону
    notified: dict = field(default_factory=dict)      # итог отправки оповещений
    vendor_extra: dict = field(default_factory=dict)  # id -> VendorItem, найденные через Wowhead
    faction_rows: list = field(default_factory=list)  # сравнение цен фракций без порогов (источник-страница сравнения)
    catalog: list = field(default_factory=list)       # все просканированные предметы с категориями и признаком вендора
    vendor_check: dict = field(default_factory=dict)  # id -> итог сверки с Wowhead (продаётся ли у вендора)


def _lookup_items(client, store, ids, workers=8):
    missing = [i for i in ids if store.get_item(i) is None]
    failed = 0

    def one(i):
        try:
            return i, client.fetch_item(i)
        except Exception:
            return i, None
    with ThreadPoolExecutor(workers) as ex:
        for i, data in ex.map(one, missing):
            if data is None:
                failed += 1
            else:
                store.put_item(i, data)
    return failed


def _classify(info, classes):
    if not info:
        return None
    trade, recipe, sub = classes
    if info.get("class_id") == recipe:
        return "recipe", "Рецепт"
    if info.get("class_id") == trade and info.get("subclass_id") in sub:
        return "material", sub[info["subclass_id"]]
    return None


def _compare_houses(res, client, store, aggs, s, cfg):
    houses = cfg.get("compare_houses") or []
    if not houses:
        return
    primary = cfg.get("house_name") or "Основной"
    books, cuts = {primary: aggs}, {primary: s.cut}
    for h in houses:
        try:
            lots = client.auction_listings(house=h["id"])
        except Exception as exc:          # один недоступный аукцион не должен ломать прогон
            res.warnings.append(f"Не удалось загрузить аукцион «{h['name']}»: {exc}")
            continue
        books[h["name"]] = {i: a for i, l in lots.items() if (a := aggregate_listings(l)).min_price}
        cuts[h["name"]] = h.get("cut", s.cut)
    rows = arbitrage.rows(books, cuts, s)[:30]
    _lookup_items(client, store, [r["item_id"] for r in rows])
    for r in rows:
        r["name"] = (store.get_item(r["item_id"]) or {}).get("name", f"#{r['item_id']}")
    res.arb_rows = rows


def _extras(res, store, aggs, vendor_items, recipes, craft_ids, de_rules, s, now):
    """Крафт (рецепты пользователя) и дизенчант (таблица пользователя)."""
    if recipes:
        usual = {i: usual_price([m for _, m in store.daily_mins(i, now - 14 * DAY)]) for i in craft_ids}
        vendor_buy = {i: v.price for i, v in vendor_items.items()}
        res.craft_rows = crafting.rank([crafting.craft_profit(r, aggs, vendor_buy, usual, s) for r in recipes.values()])
        res.names = {i: (store.get_item(i) or {}).get("name", f"#{i}") for i in craft_ids}
    if de_rules:
        items = {i: info for i in aggs if (info := store.get_item(i))}
        res.de_rows = disenchant.rows(items, aggs, de_rules, s)


def _probe_vendors(res, evs, vendor_items, checker, now, progress):
    """Сверка с Wowhead: можно ли купить позицию у вендора. Проверяются позиции, которых нет в вендорном списке, выгодные
    первыми; каждый предмет по одному разу (кэш в базе). -> {item_id: VendorItem} для подтверждённых вендорных позиций
    с ценой в меди (обмен на валюту или предметы в расчёт перепродажи не берём)."""
    todo = [e for e in evs if e.cand.item_id not in vendor_items and e.cand.group != "vendor"]
    progress(f"Сверяю с Wowhead: продаются ли у вендоров ({len(todo)} позиций)…")
    extra = {}
    for e in todo:
        r = checker.check(e.cand.item_id, now)
        res.vendor_check[e.cand.item_id] = r
        if r["status"] != "vendor":
            continue
        priced = [v for v in r["vendors"] if v.get("price")]
        if priced:
            v = min(priced, key=lambda v: v["price"])
            extra[e.cand.item_id] = VendorItem(e.cand.item_id, v["price"], v["name"], "", v.get("stock"), v.get("npc_id"))
    return extra


def _vendor_flags(res):
    """Метки по итогам сверки для выгодных позиций, которые не стали вендорными."""
    unchecked = 0
    for e in res.ranked:
        r = res.vendor_check.get(e.cand.item_id)
        if r is None or e.cand.group == "vendor":
            continue
        if r["status"] == "vendor":
            e.flags.append(f"у вендора: {r['vendors'][0]['name']} (обмен/валюта)")
        elif r["status"] == "none":
            e.flags.append("вендор: нет")
        else:
            e.flags.append("вендор: не проверено")
            unchecked += 1
    if unchecked:
        res.warnings.append(f"Wowhead: не проверено {unchecked} позиций (нет связи, лимит запросов или страница Forever не распознана). "
                            "Они будут проверены в следующих запусках.")


def _catalog(res, store, aggs, vendor_items, cands):
    """Общий список: все просканированные предметы с известными данными, категория (с сайта, если есть) и признак вендора."""
    by = {c.item_id: c for c in cands}
    out = []
    for item_id, agg in aggs.items():
        info = store.get_item(item_id)
        if not info:
            continue
        c = by.get(item_id)
        v, chk = vendor_items.get(item_id), res.vendor_check.get(item_id)
        state, price, note = "", None, ""
        if v:
            state, price = "да", v.price
        elif chk and chk["status"] == "vendor":
            state, note = "возможно", "у вендора, но за обмен на валюту/предметы (Wowhead)"
        elif chk and chk["status"] == "none":
            state = "нет"
        elif info.get("purchase_price", 0) > 0:
            state, note = "возможно", f"API: цена у NPC {fmt_money(info['purchase_price'])}, на Wowhead ещё не проверено"
        out.append(dict(item_id=item_id, name=info.get("name", f"#{item_id}"),
                        category=info.get("site_category") or (c.category if c else "") or "Прочее",
                        min=agg.min_price, market=agg.market_price, qty=agg.quantity,
                        rate=c.sales_per_day if c else None, vendor=state, vendor_price=price, note=note))
    res.catalog = sorted(out, key=lambda r: r["name"])


def run(client, store, vendor_items: dict, s: Settings, cfg: dict, now: int | None = None, progress=lambda m: None,
        recipes: dict | None = None, de_rules: list | None = None, checker=None) -> Result:
    recipes = recipes or {}
    now = int(now or time.time())
    res = Result()
    progress("Загружаю список аукциона…")
    listings = client.auction_listings()
    res.listings = listings
    aggs = {i: aggregate_listings(l) for i, l in listings.items()}
    aggs = {i: a for i, a in aggs.items() if a.min_price}
    fresh = store.add_snapshot(now, aggs)
    if not fresh:
        res.warnings.append("Аукцион не изменился с прошлого запуска (Blizzard обновляет данные раз в час): новый снимок не записан.")
    progress(f"Лотов по {len(aggs)} предметам. Загружаю данные предметов…")

    # кэшированные предметы берём все; новые запрашиваем в порядке «вендорные, затем дороже»
    cap = int(cfg.get("max_item_lookups", 1500))
    cached = [i for i in aggs if i in vendor_items or store.get_item(i) is not None]
    fresh_ids = sorted((i for i in aggs if i not in cached), key=lambda i: -aggs[i].min_price)
    craft_ids = sorted({i for r in recipes.values() for i in (r.product, *[x for x, _ in r.reagents])})
    priority = list(dict.fromkeys(list(vendor_items) + craft_ids))
    vendor_missing = [i for i in priority if store.get_item(i) is None]
    to_fetch = (vendor_missing + [i for i in fresh_ids if i not in vendor_missing])[:cap]
    failed = _lookup_items(client, store, to_fetch)
    if failed:
        res.warnings.append(f"Не удалось получить данные у {failed} предметов (проверьте статический неймспейс).")
    skipped = len(fresh_ids) + len(vendor_missing) - len(to_fetch)
    if skipped > 0:
        res.warnings.append(f"За один запуск запрошено {len(to_fetch)} новых предметов, ещё {skipped} будут запрошены в следующих запусках (лимит max_item_lookups).")
    wanted = list(vendor_items) + [i for i in cached + to_fetch if i not in vendor_items]
    wanted = list(dict.fromkeys(wanted))

    progress("Считаю выгоду…")
    classes = class_map(cfg)

    def build(vendor_items):
        cands, looked = [], 0
        for item_id in list(dict.fromkeys(list(vendor_items) + wanted)):
            info = store.get_item(item_id) or {}
            v = vendor_items.get(item_id)
            looked += 1 if info else 0
            kind = _classify(info, classes) if not v else ("vendor", "Перепродажа NPC")
            if kind is None:
                continue
            agg = aggs.get(item_id)
            series = store.qty_series(item_id, now - 3 * DAY)
            rate, _ = estimate_sales_per_day(series)
            mins = [m for _, m in store.daily_mins(item_id, now - 14 * DAY)]
            vendor_sell = info.get("sell_price", 0)
            buy = v.price if v else max(vendor_sell, 1)
            cands.append(Candidate(
                item_id=item_id, name=info.get("name", f"#{item_id}"), group=kind[0], category=kind[1],
                buy_price=buy, buy_source="vendor" if v else "opportunity",
                min_price=agg.min_price if agg else None, market_price=agg.market_price if agg else None,
                vendor_sell=vendor_sell, quantity=agg.quantity if agg else 0, n_auctions=agg.n_auctions if agg else 0,
                sales_per_day=rate, history_days=store.history_days(item_id, now - 14 * DAY),
                usual_price=usual_price(mins), stock=v.stock if v else None,
                api_buy_price=info.get("purchase_price", 0), profession=profession(info, cfg),
                vendor_name=v.vendor if v else "", location=v.location if v else ""))
        return cands, looked

    cands, looked = build(vendor_items)
    ranked, rejected = rank(cands, s)
    if checker is not None:
        extra = _probe_vendors(res, ranked + rejected, vendor_items, checker, now, progress)
        if extra:                                     # подтверждённые вендорные позиции считаем как вендорные
            res.vendor_extra = extra
            vendor_items = {**vendor_items, **extra}
            cands, looked = build(vendor_items)
            ranked, rejected = rank(cands, s)
    res.ranked, res.rejected = ranked, rejected
    res.top = ranked[: s.top_n]
    for e in ranked:
        res.by_category.setdefault(e.cand.category, []).append(e)
    vend = [e for e in ranked + rejected if e.cand.group == "vendor"]
    vend.sort(key=lambda e: (bool(e.rejects), -e.epd if not e.rejects else -e.net, e.cand.item_id))
    res.vendor_rows = vend
    res.meta = dict(ts=now, items_on_ah=len(aggs), candidates=len(cands),
                    max_history=max((c.history_days for c in cands), default=0),
                    realm=cfg.get("connected_realm_id"), house=cfg.get("auction_house_id"))
    res.prices = aggs
    _vendor_flags(res)
    _catalog(res, store, aggs, vendor_items, cands)
    _compare_houses(res, client, store, aggs, s, cfg)
    _extras(res, store, aggs, vendor_items, recipes, craft_ids, de_rules, s, now)
    res.sources = client.sources()
    if looked and not any(c.group != "vendor" for c in cands):
        res.warnings.append("Ни один предмет не распознан как рецепт или материал: проверьте ID классов "
                            "(class_trade, class_recipe, trade_sub в config.json) для Forever.")
    if res.meta["max_history"] < 3:
        res.warnings.append("Истории меньше 3 дней: продажи в день и обычная цена пока оценочные.")
    progress("Готово.")
    return res
