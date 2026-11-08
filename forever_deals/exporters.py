"""Экспорт списка закупки в виде, который можно вставить в игру или аддон."""
from __future__ import annotations


def _clean(names):
    seen, out = set(), []
    for n in names:
        n = n.replace(";", "").strip()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def tsm_search_string(names) -> str:
    """Строка поиска в стиле TSM: «Имя/exact;Имя2/exact». Поддерживается поиском Hammerprice и TSM."""
    return ";".join(f"{n}/exact" for n in _clean(names))


def plain_lines(names) -> str:
    return "\n".join(names)


def route_names(route):
    """Названия товаров маршрута закупки в порядке маршрута (без пометки демо)."""
    return _clean(r["name"].removeprefix("[демо] ") for g in route for r in g["rows"])
