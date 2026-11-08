"""SQLite: снимки аукциона (для оценки продаж и обычной цены) и кэш предметов."""
from __future__ import annotations

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
        """)

    def add_snapshot(self, ts: int, aggs: dict):
        self.db.executemany(
            "INSERT INTO snap VALUES(?,?,?,?,?,?)",
            [(ts, i, a.min_price, a.market_price, a.quantity, a.n_auctions) for i, a in aggs.items()])
        self.db.commit()

    def qty_series(self, item_id: int, since: int):
        cur = self.db.execute("SELECT ts, qty FROM snap WHERE item_id=? AND ts>=? ORDER BY ts", (item_id, since))
        return cur.fetchall()

    def daily_mins(self, item_id: int, since: int):
        """Минимум цены по календарным суткам (UTC): [(day, min)]."""
        cur = self.db.execute(
            "SELECT ts/?, MIN(min_price) FROM snap WHERE item_id=? AND ts>=? AND min_price IS NOT NULL "
            "GROUP BY ts/? ORDER BY 1", (DAY, item_id, since, DAY))
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
