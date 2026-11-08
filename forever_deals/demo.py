"""Демо-источник: вымышленные предметы и цены, чтобы проверить интерфейс без ключей."""
from __future__ import annotations

import random

from .core import DAY, aggregate_listings
from .vendors import VendorItem

# id, имя, class, subclass, цена вендору (продажа), цена закупки у NPC, средняя цена на АХ, шт/день
ITEMS = [
    (900001, "Грубая нить", 7, 5, 1, 8, 1500, 40),
    (900002, "Тонкая нить", 7, 5, 4, 80, 6000, 27),
    (900003, "Красная краска", 7, 5, 5, 40, 4500, 9),
    (900004, "Пряность тёмного берега", 7, 8, 2, 8, 900, 6),
    (900005, "Рецепт: Мастер-повар", 9, 5, 50, 1000, 12000, 7),
    (900006, "Медная руда", 7, 7, 40, 0, 220, 55),
    (900007, "Мироцвет", 7, 9, 30, 0, 310, 38),
    (900008, "Лёгкая шкура", 7, 6, 20, 0, 150, 60),
    (900009, "Льняная ткань", 7, 5, 13, 0, 60, 90),
    (900010, "Рецепт: Огненный жезл", 9, 8, 100, 0, 7000, 2),
    (900011, "Серебряный кабан", 15, 0, 100, 0, 5000, 5),
]
VENDORS = {
    900001: VendorItem(900001, 8, "Стефани Тёрнер (демо)", "Штормград, Ремесленный квартал", None, 990001),
    900002: VendorItem(900002, 80, "Стефани Тёрнер (демо)", "Штормград, Ремесленный квартал", None, 990001),
    900003: VendorItem(900003, 40, "Продавец красителей (демо)", "Штормград, Старый город", 20, 990002),
    900004: VendorItem(900004, 8, "Эллис, трактирщица (демо)", "Штормград, таверна «Свин и свисток»", None, 990003),
    900005: VendorItem(900005, 1000, "Мастер кулинарии (демо)", "Штормград, таверна «Свин и свисток», верхний этаж", 3, 990003),
}


class DemoClient:
    cfg = {}

    def auction_listings(self):
        rnd = random.Random(7)
        out = {}
        for item_id, _, _, _, _, _, price, rate in ITEMS:
            n = max(3, rate // 3)
            out[item_id] = [(max(1, int(price * rnd.uniform(0.9, 1.4))), rnd.randint(1, 40)) for _ in range(n)]
        return out

    def fetch_item(self, item_id):
        for i, name, cls, sub, vsell, buy, *_ in ITEMS:
            if i == item_id:
                return dict(name="[демо] " + name, class_id=cls, subclass_id=sub, purchase_price=buy, sell_price=vsell)
        raise KeyError(item_id)

    def sources(self):
        return [("Демо-данные (локальные)", "—")]


def seed_history(store, now):
    """3 дня снимков раз в 6 часов: количество то падает (продажи), то пополняется."""
    rnd = random.Random(3)
    for k in range(12, 0, -1):
        ts = now - k * 6 * 3600
        rows = {}
        for item_id, _, _, _, _, _, price, rate in ITEMS:
            n = max(3, rate // 3)
            qty_total = rate * 3 + (k % 3) * rate // 2
            listings = [(max(1, int(price * rnd.uniform(0.9, 1.4))), max(1, qty_total // n)) for _ in range(n)]
            rows[item_id] = aggregate_listings(listings)
        store.add_snapshot(ts, rows)
