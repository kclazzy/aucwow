"""Простые виджеты дашборда на tkinter: плитки показателей и горизонтальные диаграммы (без внешних библиотек)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import viewmodel as vm

BAR = "#3b82c4"
MUTED = "#6b7280"


def kpi_row(parent, tiles):
    """tiles: [(подпись, значение, пояснение)] -> ряд плиток."""
    row = ttk.Frame(parent)
    for i, (label, value, hint) in enumerate(tiles):
        box = ttk.LabelFrame(row, text=label, padding=(12, 4))
        box.grid(row=0, column=i, sticky="nsew", padx=4, pady=4)
        ttk.Label(box, text=value, font=("Segoe UI", 16, "bold")).pack(anchor="w")
        if hint:
            ttk.Label(box, text=hint, foreground=MUTED, wraplength=190).pack(anchor="w")
        row.columnconfigure(i, weight=1, uniform="kpi")
    return row


class BarChart(ttk.LabelFrame):
    """Горизонтальная диаграмма: подпись слева, столбик, значение справа. Пустые данные показывают подсказку."""
    ROW = 24
    LABEL_W = 230
    VALUE_W = 110

    def __init__(self, parent, title, items, empty="Нет данных"):
        super().__init__(parent, text=title, padding=6)
        self.items, self.empty = list(items), empty        # [(подпись, число, подпись значения)]
        self.canvas = tk.Canvas(self, height=max(40, self.ROW * len(self.items) + 8), highlightthickness=0)
        self.canvas.pack(fill="x", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw())

    def draw(self):
        c = self.canvas
        c.delete("all")
        if not self.items:
            c.create_text(8, 18, anchor="w", text=self.empty, fill=MUTED)
            return
        width = max(60, c.winfo_width() - self.LABEL_W - self.VALUE_W)
        for i, (label, value, text) in enumerate(self.items):
            y = 4 + i * self.ROW
            ln = vm.bar_lengths([v for _, v, _ in self.items], width)[i]
            c.create_text(self.LABEL_W - 8, y + self.ROW / 2, anchor="e", text=label[:34])
            c.create_rectangle(self.LABEL_W, y + 3, self.LABEL_W + max(ln, 1 if value > 0 else 0), y + self.ROW - 4,
                               fill=BAR, outline="")
            c.create_text(self.LABEL_W + ln + 6, y + self.ROW / 2, anchor="w", text=text)
