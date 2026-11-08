"""SQLite: снимки аукциона (для оценки продаж и обычной цены) и кэш предметов."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

DAY = 86400


class Store:
    def __init__(self, path):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS snap(ts INTEGER, item_id INTEGER, min_price INTEGER,
            market INTEGER, qty INTEGER, n INTEGER);
        CREATE INDEX IF NOT EXISTS snap_item ON snap(item_id, ts);
        CREATE TABLE IF NOT EXISTS item(item_id INTEGER PRIMARY KEY, data TEXT);
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS wh(item_id INTEGER PRIMARY KEY, ts INTEGER, data TEXT);
        CREATE TABLE IF NOT EXISTS trade(ts INTEGER, item_id INTEGER, kind TEXT, qty INTEGER, unit_price INTEGER);
        """)

    def close(self):
        self.db.close()

    def wh_get(self, item_id: int):
        """Сохранённый результат сверки с Wowhead или None."""
        row = self.db.execute("SELECT data FROM wh WHERE item_id=?", (item_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def wh_put(self, item_id: int, data: dict, ts: int):
        self.db.execute("INSERT OR REPLACE INTO wh VALUES(?,?,?)", (item_id, ts, json.dumps(data, ensure_ascii=False)))
        self.db.commit()

    def add_snapshot(self, ts: int, aggs: dict) -> bool:
        """Пишет снимок, если данные изменились с прошлого (Blizzard обновляет аукцион раз в час). -> записан ли."""
        rows = sorted((i, a.min_price, a.market_price, a.quantity, a.n_auctions) for i, a in aggs.items())
        digest = hashlib.sha1(json.dumps(rows).encode()).hexdigest()
        row = self.db.execute("SELECT v FROM meta WHERE k='last_digest'").fetchone()
        if row and row[0] == digest:
            return False
        self.db.executemany("INSERT INTO snap VALUES(?,?,?,?,?,?)", [(ts, *r) for r in rows])
        self.db.execute("INSERT OR REPLACE INTO meta VALUES('last_digest', ?)", (digest,))
        self.db.commit()
        return True

    def qty_series(self, item_id: int, since: int):
        cur = self.db.execute("SELECT ts, qty FROM snap WHERE item_id=? AND ts>=? ORDER BY ts", (item_id, since))
        return cur.fetchall()

    def daily_mins(self, item_id: int, since: int):
        """Минимум цены по календарным суткам (UTC): [(day, min)]."""
        cur = self.db.execute(
            "SELECT ts/?, MIN(min_price) FROM snap WHERE item_id=? AND ts>=? AND min_price IS NOT NULL "
            "GROUP BY ts/? ORDER BY 1", (DAY, item_id, since, DAY))
        return cur.fetchall()

    def price_history(self, item_id: int, since: int):
        """[(начало суток UTC, минимальная цена за сутки, средняя рыночная)] по возрастанию."""
        cur = self.db.execute(
            "SELECT (ts/?)*?, MIN(min_price), CAST(AVG(market) AS INTEGER) FROM snap "
            "WHERE item_id=? AND ts>=? AND min_price IS NOT NULL GROUP BY ts/? ORDER BY 1",
            (DAY, DAY, item_id, since, DAY))
        return cur.fetchall()

    def history_days(self, item_id: int, since: int) -> int:
        cur = self.db.execute("SELECT COUNT(DISTINCT ts/?) FROM snap WHERE item_id=? AND ts>=?", (DAY, item_id, since))
        return cur.fetchone()[0]

    def get_item(self, item_id: int):
        row = self.db.execute("SELECT data FROM item WHERE item_id=?", (item_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_item(self, item_id: int, data: dict):
        self.db.execute("INSERT OR REPLACE INTO item VALUES(?,?)", (item_id, json.dumps(data, ensure_ascii=False)))
        self.db.commit()

    # --- журнал сделок ---
    def add_trade(self, ts: int, item_id: int, kind: str, qty: int, unit_price: int):
        if kind not in ("buy", "sell") or qty <= 0 or unit_price < 0:
            raise ValueError("сделка: kind buy/sell, количество > 0, цена >= 0")
        self.db.execute("INSERT INTO trade VALUES(?,?,?,?,?)", (ts, item_id, kind, qty, unit_price))
        self.db.commit()

    def add_trades(self, trades) -> int:
        """Массовый импорт сделок без дублей (повторный импорт того же файла ничего не добавляет). -> сколько добавлено."""
        added = 0
        for t in trades:
            args = (t["ts"], t["item_id"], t["kind"], t["qty"], t["unit_price"])
            if not self.db.execute("SELECT 1 FROM trade WHERE ts=? AND item_id=? AND kind=? AND qty=? AND unit_price=?", args).fetchone():
                self.db.execute("INSERT INTO trade VALUES(?,?,?,?,?)", args)
                added += 1
        self.db.commit()
        return added

    def trade_summary(self, cut: float = 0.05):
        """По предметам: куплено, продано, остаток, реализованная прибыль (продано по средней цене покупки)."""
        out = []
        for (item_id,) in self.db.execute("SELECT DISTINCT item_id FROM trade ORDER BY item_id").fetchall():
            rows = self.db.execute("SELECT kind, qty, unit_price FROM trade WHERE item_id=?", (item_id,)).fetchall()
            bought = sum(q for k, q, _ in rows if k == "buy")
            spent = sum(q * p for k, q, p in rows if k == "buy")
            sold = sum(q for k, q, _ in rows if k == "sell")
            revenue = sum(q * p for k, q, p in rows if k == "sell")
            avg_buy = spent / bought if bought else 0
            realized = int(revenue * (1 - cut) - sold * avg_buy) if sold else 0
            out.append(dict(item_id=item_id, bought=bought, sold=sold, left=bought - sold,
                            spent=spent, revenue=revenue, realized=realized))
        return out
