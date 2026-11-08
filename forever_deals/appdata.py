"""Папка данных, настройки, состояние. Всё лежит в ~/.forever_deals (или $FD_HOME)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, fields
from datetime import date, datetime, timedelta
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
    "retry_minutes": 30, "keep_reports": 30, "realm_limit": 200,
    "house_cuts": {}, "github_token": "",
    "discord_webhook": "", "telegram_token": "", "telegram_chat_id": "",
    "hourly_check": False, "wowhead_check": True, "wowhead_budget": 40, "compare_houses": [], "house_name": "Основной", "drop_pct": 0.7, "alert_digest": True,
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
    if os.environ.get("FD_CLIENT_SECRET"):          # секрет можно не хранить в файле
        cfg["client_secret"] = os.environ["FD_CLIENT_SECRET"]
    return cfg


def save_cfg(h: Path, cfg: dict):
    f = h / "config.json"
    f.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(f, 0o600)                           # на Windows chmod почти не действует
    except OSError:
        pass


def load_settings(cfg: dict) -> Settings:
    names = {f.name for f in fields(Settings)}
    kw = {k: v for k, v in cfg.get("settings", {}).items() if k in names}
    cut = (cfg.get("house_cuts") or {}).get(str(cfg.get("auction_house_id", "")))
    if cut is not None:                              # у каждого аукциона своя комиссия
        kw["cut"] = float(cut)
    return Settings(**kw)


def set_house_cut(cfg: dict, cut: float):
    cfg.setdefault("house_cuts", {})[str(cfg.get("auction_house_id", ""))] = float(cut)


def settings_to_cfg(cfg: dict, s: Settings):
    cfg["settings"] = asdict(s)


def _state(h: Path) -> dict:
    f = h / "state.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _save_state(h: Path, st: dict):
    (h / "state.json").write_text(json.dumps(st), encoding="utf-8")


def last_run(h: Path):
    return _state(h).get("last_run")


def last_error(h: Path):
    return _state(h).get("error")


def mark_run(h: Path, when: datetime):
    st = _state(h)
    st["last_run"] = when.isoformat()
    st.pop("error", None)
    st.pop("failed_at", None)
    _save_state(h, st)


def mark_fail(h: Path, when: datetime, error: str):
    st = _state(h)
    st["failed_at"], st["error"] = when.isoformat(), error
    _save_state(h, st)


def parse_houses(text: str):
    """'2:Horde:5, 3:Blackwater:15' (ID : название : комиссия %) -> ([{id, name, cut}], ошибки)."""
    houses, errors = [], []
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        f = [x.strip() for x in part.split(":")]
        try:
            if len(f) != 3 or not f[0].isdigit() or not f[1]:
                raise ValueError
            cut = float(f[2].replace(",", "."))
            if not 0 <= cut <= 100:
                raise ValueError
            houses.append({"id": f[0], "name": f[1], "cut": cut / 100})
        except ValueError:
            errors.append(f"не понял «{part}» (нужно ID:название:комиссия%)")
    return houses, errors


def is_check_due(cfg: dict, h: Path, now: datetime) -> bool:
    """Ежечасная проверка (Blizzard обновляет аукцион раз в час): включена и прошёл час с прошлой."""
    if not cfg.get("hourly_check"):
        return False
    last = _state(h).get("last_check")
    return not last or now - datetime.fromisoformat(last) >= timedelta(minutes=60)


def mark_check(h: Path, when: datetime):
    st = _state(h)
    st["last_check"] = when.isoformat()
    _save_state(h, st)


def load_alert_state(h: Path) -> dict:
    f = h / "alerts.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def save_alert_state(h: Path, state: dict):
    (h / "alerts.json").write_text(json.dumps(state), encoding="utf-8")


def is_due(cfg: dict, h: Path, now: datetime) -> bool:
    """Пора ли запускать ежедневный поиск: время наступило, сегодня успешного запуска не было,
    а после сбоя прошло retry_minutes."""
    hh, mm = (int(x) for x in cfg["run_time"].split(":"))
    if (now.hour, now.minute) < (hh, mm):
        return False
    st = _state(h)
    lr = st.get("last_run")
    if lr and datetime.fromisoformat(lr).date() >= now.date():
        return False
    fa = st.get("failed_at")
    if fa and now - datetime.fromisoformat(fa) < timedelta(minutes=int(cfg.get("retry_minutes", 30))):
        return False
    return True


def prune_reports(h: Path, keep: int = 30):
    files = sorted(p for p in (h / "reports").iterdir() if p.is_file() and p.suffix in (".md", ".html"))
    stems = sorted({p.stem for p in files})
    for stem in stems[:-keep] if keep > 0 else []:
        for p in files:
            if p.stem == stem:
                p.unlink()


def configured(cfg: dict) -> bool:
    need = ("client_id", "client_secret", "dynamic_namespace", "static_namespace", "connected_realm_id", "auction_house_id")
    return all(str(cfg.get(k, "")).strip() for k in need)
