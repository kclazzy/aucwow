"""Список вендорных товаров (вводит игрок: Blizzard API не отдаёт ассортимент NPC)."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class VendorItem:
    item_id: int
    price: int                # меди
    vendor: str = ""
    location: str = ""
    stock: Optional[int] = None
    npc_id: Optional[int] = None   # для ссылки на Wowhead


def _parse(row: dict) -> VendorItem:
    item_id = int(row["item_id"])
    price = int(row.get("price") or row.get("price_copper"))
    if item_id <= 0 or price <= 0:
        raise ValueError("item_id и цена должны быть > 0")
    stock = row.get("stock")
    stock = int(stock) if stock not in (None, "", "null") else None
    npc = row.get("npc_id")
    npc = int(npc) if npc not in (None, "", "null") else None
    return VendorItem(item_id, price, (row.get("vendor") or "").strip(), (row.get("location") or "").strip(), stock, npc)


def load(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {v.item_id: v for v in map(_parse, data.get("items", []))}


def save(path, items: dict):
    rows = [dict(item_id=v.item_id, price=v.price, vendor=v.vendor, npc_id=v.npc_id, location=v.location, stock=v.stock)
            for v in sorted(items.values(), key=lambda v: v.item_id)]
    Path(path).write_text(json.dumps({"items": rows}, ensure_ascii=False, indent=2), encoding="utf-8")


def import_file(path) -> tuple:
    """CSV (заголовок: item_id,price,vendor,npc_id,location,stock; разделитель , или ;) или JSON. -> (items, errors)."""
    p = Path(path)
    items, errors = {}, []
    if p.suffix.lower() == ".json":
        rows = json.loads(p.read_text(encoding="utf-8")).get("items", [])
    else:
        text = p.read_text(encoding="utf-8-sig")
        dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
        rows = list(csv.DictReader(text.splitlines(), dialect=dialect))
    for n, row in enumerate(rows, start=2):
        try:
            v = _parse(row)
            items[v.item_id] = v
        except (KeyError, ValueError, TypeError) as exc:
            errors.append(f"строка {n}: {exc}")
    return items, errors
