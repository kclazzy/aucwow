"""Оповещения: дайджест топа и падения цены в Discord или Telegram. Только отправка сообщений, игра не затрагивается."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import appdata
from .core import fmt_money


class AlertError(Exception):
    pass


LIMITS = {"discord": 2000, "telegram": 4096}


def digest_text(res, s, n: int = 3) -> str:
    top = list(res.top)[:n]
    if not top:
        return "💰 WoW Forever: сегодня нет выгодных позиций."
    lines = [f"💰 WoW Forever: Топ-{len(top)}"]
    for e in top:
        lines.append(f"\n• {e.cand.name}: чистыми {fmt_money(e.net)}/шт, прибыль в день {fmt_money(round(e.epd))}, брать {e.qty} шт.")
    return "".join(lines)


def price_drops(res, pct: float):
    """Выгодные позиции, у которых минимальная цена опустилась ниже pct от обычной (нужна история)."""
    return [e for e in res.ranked if e.cand.usual_price and e.cand.min_price and e.cand.min_price <= pct * e.cand.usual_price]


def new_drops(drops, state: dict, today: str):
    """Оставляет только те позиции, о которых сегодня ещё не сообщали. state: {день: [item_id]}, чужие дни удаляются."""
    for day in [d for d in state if d != today]:
        del state[day]
    seen = state.setdefault(today, [])
    fresh = [e for e in drops if e.cand.item_id not in seen]
    seen.extend(e.cand.item_id for e in fresh)
    return fresh


def drops_text(drops) -> str:
    lines = ["⚡ Цена ниже обычной"]
    for e in drops:
        c = e.cand
        lines.append(f"\n• {c.name}: {fmt_money(c.min_price)} при обычной {fmt_money(c.usual_price)} "
                     f"({round(100 * c.min_price / c.usual_price)}%), чистыми {fmt_money(e.net)}/шт.")
    return "".join(lines)


def _post(opener, url: str, payload: dict):
    if not url.startswith("https://"):
        raise AlertError("адрес вебхука должен начинаться с https://")
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with opener(req, timeout=20) as resp:
            resp.read()
    except urllib.error.URLError as exc:
        raise AlertError(f"не удалось отправить: {getattr(exc, 'reason', exc)}") from exc


def send(cfg: dict, text: str, opener=urllib.request.urlopen):
    """Отправляет текст во все настроенные каналы. -> список каналов, куда ушло."""
    sent = []
    if cfg.get("discord_webhook"):
        _post(opener, cfg["discord_webhook"], {"content": text[:LIMITS["discord"]]})
        sent.append("discord")
    if cfg.get("telegram_token") and cfg.get("telegram_chat_id"):
        _post(opener, f"https://api.telegram.org/bot{cfg['telegram_token']}/sendMessage",
              {"chat_id": cfg["telegram_chat_id"], "text": text[:LIMITS["telegram"]]})
        sent.append("telegram")
    return sent


def notify(h, cfg: dict, res, s, digest: bool, opener=urllib.request.urlopen, today: str = ""):
    """После прогона: дайджест (если digest) и новые падения цены. Сбой отправки не роняет приложение.
    -> {'sent': [...], 'errors': [...]}"""
    out = {"sent": [], "errors": []}
    if not (cfg.get("discord_webhook") or (cfg.get("telegram_token") and cfg.get("telegram_chat_id"))):
        return out
    messages = []
    if digest and cfg.get("alert_digest", True):
        messages.append(digest_text(res, s))
    state = appdata.load_alert_state(h)
    fresh = new_drops(price_drops(res, float(cfg.get("drop_pct", 0.7))), state, today)
    if fresh:
        messages.append(drops_text(fresh))
    appdata.save_alert_state(h, state)
    for text in messages:
        try:
            out["sent"] += send(cfg, text, opener)
        except AlertError as exc:
            out["errors"].append(str(exc))
    return out
