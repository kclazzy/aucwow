"""Источник цен без API Blizzard: таблица цен с веб-страницы (по ссылке) или из сохранённого файла страницы.

Столбцы определяются по заголовкам (English/русский): предмет, минимальная цена, рыночная цена, количество, цена у вендора.
ID предмета берётся из ссылки в строке (…/items/2320-… или …/item=2320). Страницы конкретных сайтов мне подтвердить не удалось,
поэтому разбор общий: если таблица не найдена, приложение скажет об этом, а не подставит выдуманные цифры."""
from __future__ import annotations

import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from .core import parse_money
from .vendors import VendorItem

UA = "ForeverDeals/1.0 (personal desktop app; one page load per run)"
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


ITEM_LINK = re.compile(r"item[s]?[/=]\d+")
COLUMNS = [  # (поле, подстроки заголовка); порядок важен
    ("item", ("item", "name", "предмет", "назван", "товар")),
    ("market", ("market", "рын")),
    ("avg", ("average", "avg", "сред")),
    ("vendor", ("vendor", "вендор", "npc")),
    ("min", ("lowest", "min", "мин", "buyout", "выкуп", "дешев", "price", "cost", "floor", "цена", "стоим")),
    ("qty", ("for sale", "quantity", "qty", "stock", "кол", "на продаже", "лот", "avail", "listed", "supply", "volume",
             "units", "amount", "предлож", "остат", "налич")),
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


def _header(table):
    """Ищет строку заголовков среди первых трёх строк таблицы. -> (индекс строки, {колонка: поле}) или (None, {})."""
    for idx, row in enumerate(table[:3]):
        cols = {}
        for i, cell in enumerate(row):
            f = _header_field(cell["text"])
            if f and f not in cols.values():
                cols[i] = f
        if len(cols) >= 2:
            return idx, cols
    return None, {}


def _complete(cols) -> bool:
    fields = set(cols.values())
    return "item" in fields and "qty" in fields and bool({"min", "market"} & fields)


def _table_rows(table, cols, unit, start):
    rows = []
    for tr in table[start:]:
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
    return rows


def _diagnostics(html: str, tables) -> str:
    heads = []
    for n, t in enumerate(tables[:4], 1):
        first = next((r for r in t[:3] if r), [])
        heads.append(f"таблица {n}: строк {len(t)}, заголовки [{' | '.join(c['text'].strip()[:20] for c in first[:10])}]")
    link = ITEM_LINK.search(html)
    around = ""
    if link:
        a = html.rfind("<a", 0, link.start())
        around = " Первая ссылка на предмет: " + re.sub(r"\s+", " ", html[max(0, a):a + 160])
    return (f"получено {len(html)} символов, таблиц: {len(tables)}, скриптов: {len(re.findall(r'<script', html, re.I))}, "
            f"ссылок на предметы: {len(ITEM_LINK.findall(html))}; " + "; ".join(heads) + "." + around)


def parse_html(html: str, unit: str = "copper") -> list:
    p = _Tables()
    try:
        p.feed(html or "")
    except Exception as exc:                      # битая разметка не должна ронять приложение
        raise WebSourceError(f"не удалось разобрать страницу: {exc}") from exc
    carried = {}                                  # заголовки могут лежать в отдельной таблице перед данными
    for table in p.tables:
        if not table:
            continue
        idx, cols = _header(table)
        if idx is not None and _complete(cols):
            rows = _table_rows(table, cols, unit, idx + 1)
        elif carried and any(_item(c) for r in table[:3] for c in r):
            rows = _table_rows(table, carried, unit, 0)
        else:
            rows = []
        if rows:
            return rows
        if idx is not None and len(cols) >= 2:
            carried = cols
    html = html or ""
    rows = _parse_json(html, unit)               # страница могла отдать данные JSON-блоком, а таблицу нарисовать скриптом
    if rows:
        return rows
    raise WebSourceError("таблица цен не найдена: страница, возможно, подгружает данные скриптом или заголовки не распознаны. "
                         "Откройте её в браузере, раскройте весь список, сохраните страницу (Ctrl+S) и укажите файл. "
                         f"({_diagnostics(html, p.tables)})")


JSON_KEYS = {  # поле -> варианты ключей (в нижнем регистре, без _ и -)
    "item_id": ("itemid", "id", "itemnumber"),
    "name": ("name", "itemname", "title"),
    "category": ("category", "itemclass", "type", "group", "class", "subclass"),
    "min": ("minbuyout", "minprice", "lowestprice", "lowest", "minbuy", "min", "buyout", "price"),
    "market": ("marketvalue", "marketprice", "market"),
    "avg": ("average", "avg", "avgprice"),
    "qty": ("quantity", "qty", "forsale", "stock", "available", "count", "total"),
    "vendor": ("vendorprice", "vendorbuy", "vendorbuyprice", "npcprice", "vendor"),
}


def _walk(node):
    """Все списки словарей внутри JSON-структуры."""
    if isinstance(node, list):
        if node and all(isinstance(x, dict) for x in node):
            yield node
        for x in node:
            yield from _walk(x)
    elif isinstance(node, dict):
        for x in node.values():
            yield from _walk(x)


def _num(v, unit):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(round(v * 10000)) if unit == "gold" else int(round(v))
    return _money(str(v), unit) if isinstance(v, str) else None


def _json_rows(data, unit):
    for lst in _walk(data):
        rows = []
        for d in lst:
            low = {re.sub(r"[_\-\s]", "", k.lower()): v for k, v in d.items()}
            pick = lambda f: next((low[k] for k in JSON_KEYS[f] if k in low and low[k] not in (None, "")), None)
            item_id, qty = pick("item_id"), pick("qty")
            mn, mk = _num(pick("min"), unit), _num(pick("market"), unit)
            if isinstance(item_id, str) and item_id.isdigit():
                item_id = int(item_id)
            if isinstance(qty, str):
                qty = _count(qty)
            if not isinstance(item_id, int) or isinstance(item_id, bool) or not isinstance(qty, (int, float)) or (mn is None and mk is None):
                continue
            cat = pick("category")
            rows.append(dict(item_id=item_id, name=str(pick("name") or f"#{item_id}"), category=cat if isinstance(cat, str) else "",
                             level=None, min=mn if mn is not None else mk, market=mk if mk is not None else mn,
                             avg=_num(pick("avg"), unit), qty=int(qty), vendor=_num(pick("vendor"), unit) or None))
        if len(rows) >= 2:                      # одиночные совпадения — случайность, не таблица цен
            return rows
    return []


def _parse_json(html: str, unit: str) -> list:
    for m in re.finditer(r"<script[^>]*>(.*?)</script>", html, re.S | re.I):
        body = m.group(1).strip()
        if not body:
            continue
        candidates = [body]
        if "=" in body:
            candidates.append(body.split("=", 1)[1].strip().rstrip(";"))
        for text in candidates:
            try:
                data = json.loads(text)
            except ValueError:
                continue
            rows = _json_rows(data, unit)
            if rows:
                return rows
    return []


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

    def _read(self, source: str, is_file: bool) -> str:
        try:
            if is_file:
                return Path(source).read_text(encoding="utf-8", errors="replace")
            req = urllib.request.Request(source, headers={"User-Agent": UA})
            with self.opener(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except (OSError, ValueError) as exc:
            raise WebSourceError(f"{source}: не удалось получить страницу: {exc}") from exc

    def _save_debug(self, html: str):
        """Нераспознанную страницу кладёт в папку данных (last_page.html): по ней можно доработать разбор."""
        d = self.cfg.get("debug_dir")
        if not d:
            return None
        try:
            path = Path(d) / "last_page.html"
            path.write_text(html, encoding="utf-8")
            return str(path)
        except OSError:
            return None

    def load(self):
        """Файлы (если указаны) важнее ссылок. Несколько источников через «;» или с новой строки: списки объединяются
        (повторы предметов берутся из последнего), так можно собрать все категории или все страницы списка."""
        split = lambda t: [x.strip() for x in re.split(r"[;\n]+", t or "") if x.strip()]
        files, urls = split(self.cfg.get("web_source_file", "")), split(self.cfg.get("web_source_url", ""))
        if not files and not urls:
            raise WebSourceError("не указана ссылка на страницу с ценами или файл страницы (Настройки → Источник без API).")
        merged = {}
        for source in (files or urls):
            html = self._read(source, bool(files))
            try:
                rows = parse_html(html, self.cfg.get("web_price_unit", "copper"))
            except WebSourceError as exc:
                saved = self._save_debug(html)
                extra = f" Страница сохранена для анализа: {saved}" if saved else ""
                raise WebSourceError(f"{exc if source in str(exc) else f'{source}: {exc}'}{extra}") from exc
            for r in rows:
                merged[r["item_id"]] = r
        self.rows = list(merged.values())
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
        info = dict(name=r["name"], class_id=cls, subclass_id=sub, purchase_price=r["vendor"] or 0, sell_price=0,
                    site_category=r["category"])
        if r["level"] is not None:
            info["level"] = r["level"]
        return info

    def vendor_items(self) -> dict:
        return {r["item_id"]: VendorItem(r["item_id"], r["vendor"], VENDOR_NAME) for r in self.rows if r["vendor"]}

    def sources(self):
        return [("Таблица цен на веб-странице", self.cfg.get("web_source_url") or self.cfg.get("web_source_file") or "—")]
