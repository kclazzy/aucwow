"""Один прогон: аукцион -> снимок -> кандидаты -> ранжирование."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .core import (DAY, Candidate, Settings, aggregate_listings, estimate_sales_per_day, rank, usual_price)

CLASS_TRADE, CLASS_RECIPE = 7, 9
TRADE_SUB = {5: "Ткань", 6: "Кожа", 7: "Руда и камень", 9: "Трава"}


@dataclass
class Result:
    top: list = field(default_factory=list)
    ranked: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    vendor_rows: list = field(default_factory=list)     # все вендорные позиции, прошедшие и нет
    by_category: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    sources: list = field(default_factory=list)


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


def _classify(info):
    if info is None:
        return None
    if info.get("class_id") == CLASS_RECIPE:
        return "recipe", "Рецепт"
    if info.get("class_id") == CLASS_TRADE and info.get("subclass_id") in TRADE_SUB:
        return "material", TRADE_SUB[info["subclass_id"]]
    return None


def run(client, store, vendor_items: dict, s: Settings, cfg: dict, now: int | None = None, progress=lambda m: None) -> Result:
    now = int(now or time.time())
    res = Result()
    progress("Загружаю список аукциона…")
    listings = client.auction_listings()
    aggs = {i: aggregate_listings(l) for i, l in listings.items()}
    aggs = {i: a for i, a in aggs.items() if a.min_price}
    store.add_snapshot(now, aggs)
    progress(f"Лотов по {len(aggs)} предметам. Загружаю данные предметов…")

    cap = int(cfg.get("max_item_lookups", 1500))
    by_qty = sorted(aggs, key=lambda i: -aggs[i].quantity)
    wanted = list(vendor_items) + [i for i in by_qty if i not in vendor_items]
    failed = _lookup_items(client, store, wanted[:cap])
    if failed:
        res.warnings.append(f"Не удалось получить данные у {failed} предметов (проверьте статический неймспейс).")
    if len(wanted) > cap:
        res.warnings.append(f"Проверено {cap} из {len(wanted)} предметов (лимит max_item_lookups).")

    progress("Считаю выгоду…")
    cands = []
    for item_id in wanted[:cap]:
        info = store.get_item(item_id) or {}
        v = vendor_items.get(item_id)
        kind = _classify(info) if not v else ("vendor", "Перепродажа NPC")
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
    res.sources = client.sources()
    if res.meta["max_history"] < 3:
        res.warnings.append("Истории меньше 3 дней: продажи в день и обычная цена пока оценочные.")
    progress("Готово.")
    return res
