"""Папка данных, настройки, состояние. Всё лежит в ~/.forever_deals (или $FD_HOME)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, fields
from datetime import date, datetime
from pathlib import Path

from .core import Settings

DEFAULT_CFG = {
    "client_id": "", "client_secret": "", "region": "eu", "locale": "ru_RU",
    "dynamic_namespace": "", "static_namespace": "",
    "connected_realm_id": "", "auction_house_id": "",
    "auction_path": "/data/wow/connected-realm/{realm}/auctions/{house}",
    "item_path": "/data/wow/item/{id}",
    "max_item_lookups": 1500, "run_time": "20:00", "demo": False,
    "wowhead_base": "https://www.wowhead.com/forever",
}


def home() -> Path:
    p = Path(os.environ.get("FD_HOME") or Path.home() / ".forever_deals")
    (p / "reports").mkdir(parents=True, exist_ok=True)
    return p


def load_cfg(h: Path) -> dict:
    cfg = dict(DEFAULT_CFG)
    f = h / "config.json"
    if f.exists():
        cfg.update(json.loads(f.read_text(encoding="utf-8")))
    return cfg


def save_cfg(h: Path, cfg: dict):
    (h / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def load_settings(cfg: dict) -> Settings:
    names = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in cfg.get("settings", {}).items() if k in names})


def settings_to_cfg(cfg: dict, s: Settings):
    cfg["settings"] = asdict(s)


def last_run(h: Path):
    f = h / "state.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8")).get("last_run")
    return None


def mark_run(h: Path, when: datetime):
    (h / "state.json").write_text(json.dumps({"last_run": when.isoformat()}), encoding="utf-8")


def is_due(cfg: dict, h: Path, now: datetime) -> bool:
    """Пора ли запускать ежедневный поиск: время наступило и сегодня ещё не запускали."""
    hh, mm = (int(x) for x in cfg["run_time"].split(":"))
    if (now.hour, now.minute) < (hh, mm):
        return False
    lr = last_run(h)
    return not lr or datetime.fromisoformat(lr).date() < now.date()


def configured(cfg: dict) -> bool:
    need = ("client_id", "client_secret", "dynamic_namespace", "static_namespace", "connected_realm_id", "auction_house_id")
    return all(str(cfg.get(k, "")).strip() for k in need)
