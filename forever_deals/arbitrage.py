"""Сравнение аукционов (Alliance, Horde, Blackwater): купить дешевле на одном, продать дороже на другом с учётом комиссии."""
from __future__ import annotations

from itertools import permutations

from .core import Settings


def rows(books: dict, cuts: dict, s: Settings):
    """books: {аукцион: {item_id: Aggregate}}, cuts: {аукцион: комиссия}. Лучшие по общей прибыли первыми.
    Учитываются только предметы, которые есть на обоих аукционах и не являются изолированными лотами."""
    out = []
    for a, b in permutations(books, 2):
        for item_id, buy_agg in books[a].items():
            sell_agg = books[b].get(item_id)
            if not sell_agg or not buy_agg.min_price or not sell_agg.min_price:
                continue
            if buy_agg.quantity < s.min_quantity or sell_agg.quantity < s.min_quantity:
                continue
            buy, sell = buy_agg.min_price, sell_agg.min_price
            net = int(sell * (1 - cuts.get(b, s.cut)) - buy)
            roi = net / buy
            qty = min(buy_agg.quantity, s.budget_item // buy)
            if net >= s.min_net and roi >= s.min_roi and qty > 0:
                out.append(dict(item_id=item_id, buy_house=a, sell_house=b, buy=buy, sell=sell, net=net, roi=roi,
                                qty=qty, profit=net * qty))
    return sorted(out, key=lambda r: (-r["profit"], r["item_id"], r["buy_house"]))
