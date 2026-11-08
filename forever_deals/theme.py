"""Оформление окна: палитра, стили ttk, проверка контраста. Все цвета живут здесь (одно решение — одно место)."""
from __future__ import annotations

PALETTE = {
    "bg": "#f4f6fa", "card": "#ffffff", "text": "#1f2937", "muted": "#5b6472", "border": "#d5dbe6",
    "header_bg": "#1f2d4d", "header_fg": "#ffffff", "header_sub": "#c5d0ea",
    "accent": "#2563eb", "accent_dark": "#1d4ed8", "accent_fg": "#ffffff",
    "ok": "#15803d", "bad": "#b91c1c", "warn": "#92400e",
    "ok_bg": "#e8f6ee", "bad_bg": "#fdecec", "zebra": "#f1f5fb", "select": "#dbe7fb", "bar": "#2563eb",
}
P = PALETTE

# (название, цвет текста, цвет фона) — все пары должны читаться (контраст не ниже 4.5)
TEXT_PAIRS = [
    ("основной текст", P["text"], P["bg"]), ("текст в карточке", P["text"], P["card"]),
    ("приглушённый текст", P["muted"], P["bg"]), ("приглушённый в карточке", P["muted"], P["card"]),
    ("заголовок окна", P["header_fg"], P["header_bg"]), ("подзаголовок окна", P["header_sub"], P["header_bg"]),
    ("главная кнопка", P["accent_fg"], P["accent"]), ("главная кнопка (нажата)", P["accent_fg"], P["accent_dark"]),
    ("текст в выгодной строке", P["text"], P["ok_bg"]), ("текст в отклонённой строке", P["text"], P["bad_bg"]),
    ("статус «выгодно»", P["ok"], P["card"]), ("статус «отклонено»", P["bad"], P["card"]),
    ("сообщение об успехе", P["ok"], P["card"]), ("сообщение об ошибке", P["bad"], P["card"]),
    ("предупреждение", P["warn"], P["bg"]), ("выделенная строка", P["text"], P["select"]),
]


def _lum(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(fg: str, bg: str) -> float:
    """Контраст по WCAG: от 1 (одинаковые) до 21 (чёрное на белом)."""
    a, b = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def apply(root, family="Segoe UI"):
    """Применяет тему ко всем ttk-виджетам окна."""
    from tkinter import ttk
    st = ttk.Style(root)
    st.theme_use("clam")
    root.configure(bg=P["bg"])
    base = (family, 10)
    st.configure(".", background=P["bg"], foreground=P["text"], font=base, bordercolor=P["border"],
                 lightcolor=P["bg"], darkcolor=P["bg"], troughcolor=P["bg"])
    st.configure("TLabel", background=P["bg"], foreground=P["text"])
    st.configure("Muted.TLabel", foreground=P["muted"])
    st.configure("Status.TLabel", background=P["card"], foreground=P["text"], padding=(12, 8), relief="flat")
    st.configure("Header.TFrame", background=P["header_bg"])
    st.configure("Title.TLabel", background=P["header_bg"], foreground=P["header_fg"], font=(family, 18, "bold"))
    st.configure("Sub.TLabel", background=P["header_bg"], foreground=P["header_sub"])
    st.configure("TLabelframe", background=P["card"], bordercolor=P["border"], relief="solid")
    st.configure("TLabelframe.Label", background=P["card"], foreground=P["muted"], font=(family, 9, "bold"))
    st.configure("Card.TFrame", background=P["card"])
    st.configure("Card.TLabel", background=P["card"], foreground=P["text"])
    st.configure("CardMuted.TLabel", background=P["card"], foreground=P["muted"])
    st.configure("Kpi.TLabel", background=P["card"], foreground=P["accent"], font=(family, 18, "bold"))
    st.configure("TButton", padding=(12, 6), background=P["card"], foreground=P["text"], bordercolor=P["border"])
    st.map("TButton", background=[("active", P["select"]), ("disabled", P["bg"])])
    st.configure("Accent.TButton", background=P["accent"], foreground=P["accent_fg"], bordercolor=P["accent"],
                 font=(family, 10, "bold"))
    st.map("Accent.TButton", background=[("active", P["accent_dark"]), ("disabled", P["border"])],
           foreground=[("disabled", P["muted"])])
    st.configure("TNotebook", background=P["bg"], borderwidth=0, tabmargins=(0, 4, 0, 0))
    st.configure("TNotebook.Tab", padding=(14, 7), background=P["border"], foreground=P["muted"])
    st.map("TNotebook.Tab", background=[("selected", P["card"])], foreground=[("selected", P["accent"])])
    st.configure("Treeview", background=P["card"], fieldbackground=P["card"], foreground=P["text"], rowheight=27,
                 borderwidth=0)
    st.map("Treeview", background=[("selected", P["select"])], foreground=[("selected", P["text"])])
    st.configure("Treeview.Heading", background=P["header_bg"], foreground=P["header_fg"], font=(family, 9, "bold"),
                 padding=(6, 6), relief="flat")
    st.map("Treeview.Heading", background=[("active", P["accent_dark"])])
    return st


def tag_tree(tv):
    """Цвета строк таблицы: полосы и статусы."""
    tv.tag_configure("odd", background=P["zebra"])
    tv.tag_configure("even", background=P["card"])
    tv.tag_configure("ok", background=P["ok_bg"])
    tv.tag_configure("bad", background=P["bad_bg"])
    tv.tag_configure("vendor", background=P["select"], font=("Segoe UI", 10, "bold"))
