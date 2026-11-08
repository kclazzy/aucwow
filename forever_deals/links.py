"""Ссылки на Wowhead (раздел Forever). Страницы подтягиваются в браузере: приложение их не скачивает."""
WOWHEAD = "https://www.wowhead.com/forever"


def item_url(item_id: int, base: str = WOWHEAD) -> str:
    return f"{base}/item={int(item_id)}"


def npc_url(npc_id: int, base: str = WOWHEAD) -> str:
    return f"{base}/npc={int(npc_id)}"


def md_link(text: str, url: str) -> str:
    return f"[{text}]({url})"
