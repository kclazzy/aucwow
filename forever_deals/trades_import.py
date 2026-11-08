"""Импорт сделок из сохранённых данных аддонов. Формат у каждого аддона свой и не подтверждён,
поэтому это эвристика: ищем записи с предметом, количеством, ценой и видом сделки. Результат нужно проверить."""
from __future__ import annotations

import re

KEYS = dict(
    item=("itemid", "item_id", "item", "itemlink", "link"),
    qty=("count", "quantity", "qty", "stack", "stacksize", "amount"),
    price=("price", "unitprice", "copper", "money", "buyout", "totalprice", "total"),
    kind=("type", "kind", "action", "event", "transaction"),
    ts=("time", "timestamp", "ts", "date"),
)


def _find(row: dict, names, exact=None):
    if exact:
        return exact if exact in row else None
    lower = {str(k).lower(): k for k in row}
    for n in names:
        if n in lower:
            return lower[n]
    return None


def _item_id(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        m = re.search(r"item:(\d+)", v) or re.fullmatch(r"\s*(\d+)\s*", v)
        return int(m.group(1)) if m else None
    return None


def _kind(v):
    t = str(v).lower()
    if any(w in t for w in ("sale", "sold", "sell")):
        return "sell"
    if any(w in t for w in ("purchase", "buy", "bought")):
        return "buy"
    return None


def _row(row: dict, mapping):
    m = mapping or {}
    keys = {name: _find(row, KEYS[name], m.get(name)) for name in KEYS}
    if not (keys["item"] and keys["qty"] and keys["price"] and keys["kind"]):
        return None, False                       # не похоже на сделку
    item = _item_id(row[keys["item"]])
    qty, price = row[keys["qty"]], row[keys["price"]]
    if item is None or isinstance(qty, bool) or not isinstance(qty, (int, float)) or qty <= 0 \
            or isinstance(price, bool) or not isinstance(price, (int, float)) or price < 0:
        return None, False
    kind = _kind(row[keys["kind"]])
    if kind is None:
        return None, True                        # похоже на сделку, но вид неизвестен
    unit = int(price) // int(qty) if "total" in str(keys["price"]).lower() else int(price)
    ts = row.get(keys["ts"]) if keys["ts"] else 0
    return dict(ts=int(ts) if isinstance(ts, (int, float)) else 0, item_id=item, kind=kind, qty=int(qty), unit_price=unit), False


def extract(tree, mapping=None):
    """-> (сделки, пропущено записей с неизвестным видом). mapping: {'item','qty','price','kind','ts'} — свои имена полей."""
    trades, skipped = [], 0
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, (list, tuple)):
            stack.extend(node)
            continue
        if not isinstance(node, dict):
            continue
        trade, unknown = _row(node, mapping)
        if trade:
            trades.append(trade)
            continue
        skipped += unknown
        stack.extend(node.values())
    return sorted(trades, key=lambda t: (t["ts"], t["item_id"], t["kind"])), skipped
