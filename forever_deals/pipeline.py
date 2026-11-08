"""Один прогон: аукцион -> снимок -> кандидаты -> ранжирование."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import crafting, disenchant
from .core import (DAY, Candidate, Settings, aggregate_listings, estimate_sales_per_day, rank, usual_price)

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
    names: dict = field(default_factory=dict)         # id -> название для крафта
    prices: dict = field(default_factory=dict)        # id -> Aggregate по всему аукциону
    notified: dict = field(default_factory=dict)      # итог отправки оповещений


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


def run(client, store, vendor_items: dict, s: Settings, cfg: dict, now: int | None = None, progress=lambda m: None,
        recipes: dict | None = None, de_rules: list | None = None) -> Result:
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
    cands = []
    classes = class_map(cfg)
    looked = 0
    for item_id in wanted:
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
    _extras(res, store, aggs, vendor_items, recipes, craft_ids, de_rules, s, now)
    res.sources = client.sources()
    if looked and not any(c.group != "vendor" for c in cands):
        res.warnings.append("Ни один предмет не распознан как рецепт или материал: проверьте ID классов "
                            "(class_trade, class_recipe, trade_sub в config.json) для Forever.")
    if res.meta["max_history"] < 3:
        res.warnings.append("Истории меньше 3 дней: продажи в день и обычная цена пока оценочные.")
    progress("Готово.")
    return res
