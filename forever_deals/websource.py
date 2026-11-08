"""Источник цен без API Blizzard: таблица цен с веб-страницы (по ссылке) или из сохранённого файла страницы.

Столбцы определяются по заголовкам (English/русский): предмет, минимальная цена, рыночная цена, количество, цена у вендора.
ID предмета берётся из ссылки в строке (…/items/2320-… или …/item=2320). Страницы конкретных сайтов мне подтвердить не удалось,
поэтому разбор общий: если таблица не найдена, приложение скажет об этом, а не подставит выдуманные цифры."""
from __future__ import annotations

import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from .core import parse_money
from .vendors import VendorItem

UA = "ForeverDeals/1.0 (личное приложение, одна загрузка страницы за запуск)"
VENDOR_NAME = "по данным сайта"


class WebSourceError(Exception):
    pass


class _Tables(HTMLParser):
    """Собирает таблицы: [[ячейка]], ячейка = {'text', 'href', 'link'}."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._row, self._cell, self._depth = [], None, None, 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self.tables.append([])
        elif tag == "tr" and self._depth:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {"text": "", "href": None, "link": ""}
        elif tag == "a" and self._cell is not None and self._cell["href"] is None:
            self._cell["href"] = dict(attrs).get("href") or ""
            self._cell["_in_a"] = True

    def handle_endtag(self, tag):
        if tag == "table":
            self._depth = max(0, self._depth - 1)
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._cell.pop("_in_a", None)
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row and self.tables:
                self.tables[-1].append(self._row)
            self._row = None
        elif tag == "a" and self._cell is not None:
            self._cell.pop("_in_a", None)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data
            if self._cell.get("_in_a"):
                self._cell["link"] += data


COLUMNS = [  # (поле, подстроки заголовка); порядок важен
    ("item", ("item", "name", "предмет", "назван", "товар")),
    ("market", ("market", "рын")),
    ("avg", ("average", "avg", "сред")),
    ("min", ("lowest", "min", "мин", "buyout", "выкуп", "дешев")),
    ("qty", ("for sale", "quantity", "qty", "stock", "кол", "на продаже", "лот")),
    ("vendor", ("vendor", "вендор", "npc")),
]
CATEGORY = [  # подстрока категории -> (class_id, subclass_id); ID как в Retail, для Forever не подтверждены
    (("cloth", "ткан"), (7, 5)), (("leather", "кож"), (7, 6)), (("metal", "stone", "руд", "металл"), (7, 7)),
    (("cooking", "кулин"), (7, 8)), (("herb", "трав"), (7, 9)), (("elemental", "стихи"), (7, 10)),
    (("enchant", "чар"), (7, 12)), (("recipe", "рецепт"), (9, 0)),
]


def _header_field(text: str):
    t = re.sub(r"[▲▼↑↓]", "", text).strip().lower()
    for field, keys in COLUMNS:
        if any(k in t for k in keys):
            return field
    return None


def _money(text: str, unit: str):
    t = text.strip().lower()
    if not t or t in {"—", "-", "–", "n/a", "н/д"}:
        return None
    if re.search(r"[зgсsмmc]", t) and re.search(r"\d", t):
        try:
            return parse_money(t)
        except ValueError:
            return None
    t = t.replace(",", "").replace(" ", "").replace("\xa0", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return int(round(v * 10000)) if unit == "gold" else int(round(v))


def _count(text: str):
    t = re.sub(r"[,\s\xa0]", "", text)
    return int(t) if t.isdigit() else None


def _item(cell: dict):
    m = re.search(r"item[s]?[/=](\d+)", cell.get("href") or "")
    if not m:
        return None
    name = (cell["link"] or cell["text"]).strip()
    category, level = "", None
    for grp in re.findall(r"\(([^)]*)\)", cell["text"]):
        for part in (p.strip() for p in grp.split(",")):
            lv = re.fullmatch(r"(?:level|ур\.?|уровень)\s*(\d+)", part, re.I)
            if lv:
                level = int(lv.group(1))
            elif part and not category:
                category = part
    return int(m.group(1)), name, category, level


def parse_html(html: str, unit: str = "copper") -> list:
    p = _Tables()
    try:
        p.feed(html or "")
    except Exception as exc:                      # битая разметка не должна ронять приложение
        raise WebSourceError(f"не удалось разобрать страницу: {exc}") from exc
    for table in p.tables:
        if not table:
            continue
        cols = {}
        for i, cell in enumerate(table[0]):
            f = _header_field(cell["text"])
            if f and f not in cols.values():
                cols[i] = f
        fields = set(cols.values())
        if "item" not in fields or "qty" not in fields or not ({"min", "market"} & fields):
            continue
        rows = []
        for tr in table[1:]:
            vals = {cols[i]: c for i, c in enumerate(tr) if i in cols}
            it = _item(vals["item"]) if "item" in vals else None
            qty = _count(vals["qty"]["text"]) if "qty" in vals else None
            if not it or qty is None:
                continue
            g = lambda k: _money(vals[k]["text"], unit) if k in vals else None
            mn, mk = g("min"), g("market")
            if mn is None and mk is None:
                continue
            rows.append(dict(item_id=it[0], name=it[1], category=it[2], level=it[3], min=mn if mn is not None else mk,
                             market=mk if mk is not None else mn, avg=g("avg"), qty=qty, vendor=g("vendor")))
        if rows:
            return rows
    raise WebSourceError("таблица цен не найдена: страница, возможно, подгружает данные скриптом. Откройте её в браузере, "
                         "раскройте весь список, сохраните страницу (Ctrl+S) и укажите файл.")


def _class_of(category: str):
    c = category.lower()
    for keys, cls in CATEGORY:
        if any(k in c for k in keys):
            return cls
    return None, None


class WebClient:
    """Тот же интерфейс, что у blizzard.Client, но данные берутся из таблицы на странице."""

    def __init__(self, cfg: dict, opener=urllib.request.urlopen):
        self.cfg, self.opener, self.rows = cfg, opener, []

    def load(self):
        url, path = self.cfg.get("web_source_url", ""), self.cfg.get("web_source_file", "")
        if not url and not path:
            raise WebSourceError("не указана ссылка на страницу с ценами или файл страницы (Настройки → Источник без API).")
        try:
            if path:
                html = Path(path).read_text(encoding="utf-8", errors="replace")
            else:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with self.opener(req, timeout=60) as r:
                    html = r.read().decode("utf-8", "replace")
        except OSError as exc:
            raise WebSourceError(f"не удалось получить страницу: {exc}") from exc
        self.rows = parse_html(html, self.cfg.get("web_price_unit", "copper"))
        return self

    def warnings(self) -> list:
        n = len(self.rows)
        out = []
        if n in (50, 100):
            out.append(f"В таблице ровно {n} строк: возможно, показана только часть списка. Раскройте её целиком "
                       "(кнопка «Show more») и сохраните страницу заново.")
        return out

    def auction_listings(self, house=None) -> dict:
        if house is not None:
            return {}
        return {r["item_id"]: [(r["market"] or r["min"], r["qty"])] for r in self.rows}

    def fetch_item(self, item_id: int) -> dict:
        r = next((x for x in self.rows if x["item_id"] == item_id), None)
        if r is None:
            raise KeyError(item_id)
        cls, sub = _class_of(r["category"])
        info = dict(name=r["name"], class_id=cls, subclass_id=sub, purchase_price=r["vendor"] or 0, sell_price=0)
        if r["level"] is not None:
            info["level"] = r["level"]
        return info

    def vendor_items(self) -> dict:
        return {r["item_id"]: VendorItem(r["item_id"], r["vendor"], VENDOR_NAME) for r in self.rows if r["vendor"]}

    def sources(self):
        return [("Таблица цен на веб-странице", self.cfg.get("web_source_url") or self.cfg.get("web_source_file") or "—")]
