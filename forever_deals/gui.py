"""Окно приложения (tkinter, входит в стандартный Python для Windows)."""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from . import appdata, runner, vendors
from .blizzard import ApiError, Client
from .core import Settings, fmt_money, parse_money
from .links import item_url, npc_url

TITLE = "💰 Ежедневный поиск выгодных товаров WoW Forever"
CHECKS = [
    "Перепродажа товаров NPC с наценкой 10–100x",
    "Рецепты и материалы профессий",
    "Руды, ткани, травы и кожа",
    "Ликвидность и количество продаж",
    "Чистая прибыль после комиссии аукциона",
    "Топ-10 наиболее перспективных товаров",
]


class App(tk.Tk):
    def __init__(self, home, cfg):
        super().__init__()
        self.h, self.cfg = home, cfg
        self.title("WoW Forever — выгодные товары")
        self.geometry("1320x780")
        self.q = queue.Queue()
        self.running = False
        self.rows = {}          # iid -> (item_id, npc_id)
        self.last_md = ""
        self.base = cfg.get("wowhead_base")
        self._build()
        self.after(300, self._poll)
        self.after(5000, self._tick)

    # ---------- построение окна ----------
    def _build(self):
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text=TITLE, font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        self.sched = ttk.Label(top, text="", foreground="#555")
        self.sched.grid(row=1, column=0, sticky="w", pady=(2, 8))
        btns = ttk.Frame(top)
        btns.grid(row=0, column=1, rowspan=2, sticky="e")
        top.columnconfigure(0, weight=1)
        self.run_btn = ttk.Button(btns, text="Выполнить сейчас", command=self.run_now)
        self.run_btn.pack(side="left", padx=4)
        ttk.Button(btns, text="Вендоры…", command=self.open_vendors).pack(side="left", padx=4)
        ttk.Button(btns, text="Настройки…", command=self.open_settings).pack(side="left", padx=4)
        ttk.Button(btns, text="Папка отчётов", command=lambda: self._open_path(self.h / "reports")).pack(side="left", padx=4)

        box = ttk.LabelFrame(self, text="Будут проверяться", padding=8)
        box.pack(fill="x", padx=12)
        for i, t in enumerate(CHECKS):
            ttk.Label(box, text="• " + t).grid(row=i // 2, column=i % 2, sticky="w", padx=8)
        box.columnconfigure(0, weight=1)
        box.columnconfigure(1, weight=1)

        self.status = ttk.Label(self, text="Готов.", padding=(12, 6))
        self.status.pack(fill="x")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.top_tv = self._table(("n", "name", "cat", "buy", "sell", "net", "roi", "rate", "qty", "flags"),
                                  ("#", "Товар", "Категория", "Закупка", "Продажа", "Чистыми/шт", "ROI", "Продаж/день", "Брать", "Метки"),
                                  (30, 220, 130, 80, 90, 90, 60, 90, 60, 220), "Топ-10")
        self.v_tv = self._table(("name", "npc", "place", "buy", "sell", "mk", "net", "rate", "lots", "status"),
                                ("Товар", "Вендор (NPC)", "Расположение", "Закупка", "Продажа", "Наценка", "Чистыми/шт", "Продаж/день", "Лотов", "Статус"),
                                (190, 160, 250, 70, 90, 70, 90, 90, 55, 150), "Вендор → Аукцион")
        rep = ttk.Frame(self.nb)
        self.nb.add(rep, text="Отчёт")
        self.text = tk.Text(rep, wrap="word", font=("Consolas", 10))
        sb = ttk.Scrollbar(rep, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set, state="disabled")
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        bar = ttk.Frame(self, padding=(12, 0, 12, 10))
        bar.pack(fill="x")
        ttk.Button(bar, text="Предмет на Wowhead", command=lambda: self._open_selected("item")).pack(side="left", padx=4)
        ttk.Button(bar, text="Вендор на Wowhead", command=lambda: self._open_selected("npc")).pack(side="left", padx=4)
        ttk.Button(bar, text="Сохранить отчёт как…", command=self.save_report).pack(side="left", padx=4)
        self._refresh_sched()

    def _table(self, cols, heads, widths, title):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text=title)
        tv = ttk.Treeview(f, columns=cols, show="headings", selectmode="browse")
        for c, hd, w in zip(cols, heads, widths):
            tv.heading(c, text=hd)
            tv.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(f, command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.bind("<Double-1>", lambda e: self._open_selected("item"))
        return tv

    # ---------- действия ----------
    def _refresh_sched(self):
        lr = appdata.last_run(self.h)
        last = datetime.fromisoformat(lr).strftime("%d.%m.%Y %H:%M") if lr else "ещё не запускался"
        mode = "  ·  ДЕМО-РЕЖИМ" if self.cfg.get("demo") else ""
        self.sched.config(text=f"Ежедневно · Вечером ({self.cfg['run_time']})  ·  Последний запуск: {last}{mode}")

    def run_now(self):
        if self.running:
            return
        self.running = True
        self.run_btn.state(["disabled"])
        self.status.config(text="Запуск…")

        def work():
            try:
                self.q.put(("done", runner.run_search(self.h, self.cfg, lambda m: self.q.put(("progress", m)))))
            except Exception as exc:       # показываем причину в окне, а не роняем приложение
                self.q.put(("error", exc))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "progress":
                    self.status.config(text=payload)
                elif kind == "done":
                    self._show(*payload)
                elif kind == "error":
                    self.running = False
                    self.run_btn.state(["!disabled"])
                    self.status.config(text="Ошибка: " + str(payload))
                    messagebox.showerror("Ошибка", str(payload))
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        self.after(300, self._poll)

    def _tick(self):
        if not self.running and not self.cfg.get("demo") and appdata.configured(self.cfg) and appdata.is_due(self.cfg, self.h, datetime.now()):
            self.run_now()
        self.after(30000, self._tick)

    def _show(self, res, md, path, items):
        self.running = False
        self.run_btn.state(["!disabled"])
        self.last_md = md
        self.rows.clear()
        for tv in (self.top_tv, self.v_tv):
            tv.delete(*tv.get_children())
        rate = lambda e: "н/д" if e.cand.sales_per_day is None else f"{e.cand.sales_per_day:.1f}"
        for n, e in enumerate(res.top, 1):
            c = e.cand
            v = items.get(c.item_id)
            iid = self.top_tv.insert("", "end", values=(n, c.name, c.category, fmt_money(c.buy_price), fmt_money(e.sell_price),
                                     fmt_money(e.net), f"{e.roi:.1f}", rate(e), e.qty, "; ".join(e.flags) or "—"))
            self.rows[iid] = (c.item_id, v.npc_id if v else None)
        for e in res.vendor_rows:
            c = e.cand
            v = items.get(c.item_id)
            ok = not e.rejects
            iid = self.v_tv.insert("", "end", values=(
                c.name, (c.vendor_name or (f"NPC {v.npc_id}" if v and v.npc_id else "—")), c.location or "—",
                fmt_money(c.buy_price), fmt_money(e.sell_price) if c.min_price else "—", f"×{e.markup:.1f}" if c.min_price else "—",
                fmt_money(e.net) if c.min_price else "—", rate(e), c.n_auctions, "✅ выгодно" if ok else "❌ " + "; ".join(e.rejects)))
            self.rows[iid] = (c.item_id, v.npc_id if v else None)
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", md)
        self.text.config(state="disabled")
        self._refresh_sched()
        warn = f" Предупреждения: {len(res.warnings)}." if res.warnings else ""
        self.status.config(text=f"Готово: {len(res.top)} позиций в топе, отчёт сохранён: {path}.{warn}")

    def _selected(self):
        tv = self.nb.nametowidget(self.nb.select()).winfo_children()[0]
        sel = tv.selection() if isinstance(tv, ttk.Treeview) else ()
        return self.rows.get(sel[0]) if sel else None

    def _open_selected(self, what):
        row = self._selected()
        if not row:
            messagebox.showinfo("Wowhead", "Выберите строку в таблице.")
            return
        item_id, npc_id = row
        if what == "npc":
            if not npc_id:
                messagebox.showinfo("Wowhead", "Для этой позиции не указан NPC. Добавьте npc_id в окне «Вендоры».")
                return
            webbrowser.open(npc_url(npc_id, self.base))
        else:
            webbrowser.open(item_url(item_id, self.base))

    def save_report(self):
        if not self.last_md:
            messagebox.showinfo("Отчёт", "Сначала выполните поиск.")
            return
        p = filedialog.asksaveasfilename(defaultextension=".md", filetypes=[("Markdown", "*.md")])
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.last_md)

    def _open_path(self, p):
        try:
            os.startfile(p)                 # Windows
        except AttributeError:
            webbrowser.open(p.as_uri())

    # ---------- окна ----------
    def bg(self, fn, done):
        def work():
            try:
                r = fn()
            except Exception as exc:
                r = exc
            self.q.put(("call", lambda: done(r)))
        threading.Thread(target=work, daemon=True).start()

    def open_settings(self):
        SettingsDialog(self)

    def open_vendors(self):
        if self.cfg.get("demo"):
            messagebox.showinfo("Вендоры", "В демо-режиме используется встроенный вымышленный список вендоров. "
                                "Отключите демо-режим в настройках, чтобы вести свой список.")
            return
        VendorsDialog(self)


class SettingsDialog(tk.Toplevel):
    API = [("client_id", "Client ID"), ("client_secret", "Client Secret"), ("region", "Регион (eu/us/kr/tw)"),
           ("locale", "Язык названий (ru_RU, en_US…)"), ("dynamic_namespace", "Неймспейс аукциона (dynamic-…)"),
           ("static_namespace", "Неймспейс предметов (static-…)"), ("connected_realm_id", "ID связанного реалма"),
           ("auction_house_id", "ID аукциона (фракция)"), ("run_time", "Время запуска (ЧЧ:ММ)")]
    ECON = [("cut", "Комиссия аукциона (0.05 = 5%)"), ("deposit_pct", "Депозит от цены вендору за 12 ч"),
            ("p_sell", "Вероятность продажи лота"), ("share", "Ваша доля рынка"), ("min_rate", "Мин. продаж в день"),
            ("min_markup", "Мин. наценка для вендорных (×)"), ("min_net", "Мин. прибыль с шт., меди"),
            ("budget_item", "Бюджет на позицию, меди")]

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Настройки")
        self.geometry("560x720")
        self.vars = {}
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        s = appdata.load_settings(app.cfg)
        r = 0
        for key, label in self.API:
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=2)
            v = tk.StringVar(value=str(app.cfg.get(key, "")))
            ttk.Entry(f, textvariable=v, width=38, show="*" if key == "client_secret" else "").grid(row=r, column=1, sticky="ew")
            self.vars[key] = v
            r += 1
        ttk.Label(f, text="Расчёт", font=("Segoe UI", 10, "bold")).grid(row=r, column=0, sticky="w", pady=(10, 2))
        r += 1
        for key, label in self.ECON:
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=2)
            v = tk.StringVar(value=str(getattr(s, key)))
            ttk.Entry(f, textvariable=v, width=38).grid(row=r, column=1, sticky="ew")
            self.vars["s_" + key] = v
            r += 1
        self.demo = tk.BooleanVar(value=bool(app.cfg.get("demo")))
        ttk.Checkbutton(f, text="Демо-режим (вымышленные данные, без ключей)", variable=self.demo).grid(row=r, column=0, columnspan=2, sticky="w", pady=8)
        r += 1
        helper = ttk.Frame(f)
        helper.grid(row=r, column=0, columnspan=2, sticky="ew")
        ttk.Button(helper, text="Найти неймспейс", command=self.find_ns).pack(side="left", padx=2)
        ttk.Button(helper, text="Реалмы…", command=self.find_realms).pack(side="left", padx=2)
        ttk.Button(helper, text="Аукционы реалма…", command=self.find_houses).pack(side="left", padx=2)
        r += 1
        self.info = tk.Text(f, height=7, wrap="word", state="disabled")
        self.info.grid(row=r, column=0, columnspan=2, sticky="nsew", pady=6)
        f.columnconfigure(1, weight=1)
        ttk.Button(f, text="Сохранить", command=self.save).grid(row=r + 1, column=1, sticky="e")

    def say(self, text):
        self.info.config(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", text)
        self.info.config(state="disabled")

    def _client(self):
        cfg = dict(self.app.cfg)
        for k, _ in self.API:
            cfg[k] = self.vars[k].get().strip()
        return Client(cfg)

    def find_ns(self):
        self.say("Проверяю варианты неймспейса…")
        c = self._client()

        def done(r):
            if isinstance(r, Exception):
                return self.say(f"Ошибка: {r}")
            if not r:
                return self.say("Подходящий неймспейс не найден автоматически. Введите его вручную из документации Blizzard.")
            self.vars["dynamic_namespace"].set(r[0])
            self.vars["static_namespace"].set(r[0].replace("dynamic", "static", 1))
            self.say("Откликнулись: " + ", ".join(r) + ".\nСтатический неймспейс подставлен по шаблону — проверьте его.")
        self.app.bg(c.discover_namespaces, done)

    def find_realms(self):
        self.say("Загружаю реалмы…")
        c = self._client()
        self.app.bg(c.connected_realms, lambda r: self.say(f"Ошибка: {r}") if isinstance(r, Exception)
                    else self.say("ID — реалмы:\n" + "\n".join(f"{i} — {n}" for i, n in r)))

    def find_houses(self):
        self.say("Загружаю аукционы реалма…")
        c = self._client()
        self.app.bg(c.auction_houses, lambda r: self.say(f"Ошибка: {r}") if isinstance(r, Exception)
                    else self.say("ID — аукцион:\n" + "\n".join(f"{i} — {n}" for i, n in r)))

    def save(self):
        cfg = self.app.cfg
        try:
            for k, _ in self.API:
                cfg[k] = self.vars[k].get().strip()
            hh, mm = cfg["run_time"].split(":")
            assert 0 <= int(hh) < 24 and 0 <= int(mm) < 60
            base = appdata.load_settings(cfg)
            kw = {}
            for k, _ in self.ECON:
                kw[k] = type(getattr(base, k))(self.vars["s_" + k].get().replace(",", "."))
            appdata.settings_to_cfg(cfg, Settings(**{**base.__dict__, **kw}))
        except (ValueError, AssertionError):
            messagebox.showerror("Настройки", "Проверьте числа и время запуска (ЧЧ:ММ).", parent=self)
            return
        cfg["demo"] = self.demo.get()
        appdata.save_cfg(self.app.h, cfg)
        self.app._refresh_sched()
        self.destroy()


class VendorsDialog(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Вендоры: что покупается у NPC")
        self.geometry("980x560")
        self.path = app.h / "vendors.json"
        self.items = vendors.load(self.path)
        ttk.Label(self, wraplength=940, padding=8, text=(
            "Ассортимент NPC нет в API Blizzard, поэтому список ведёте вы: обойдите вендоров и добавьте товары. "
            "Укажите ID предмета и ID NPC (видны в адресе на Wowhead: …/item=ID, …/npc=ID) — по ним строятся ссылки.")).pack(fill="x")
        cols = ("item", "price", "vendor", "npc", "loc", "stock")
        self.tv = ttk.Treeview(self, columns=cols, show="headings", height=10)
        for c, hd, w in zip(cols, ("ID предмета", "Цена", "Вендор", "ID NPC", "Расположение", "Остаток"), (90, 90, 200, 80, 380, 70)):
            self.tv.heading(c, text=hd)
            self.tv.column(c, width=w)
        self.tv.pack(fill="both", expand=True, padx=8)
        form = ttk.Frame(self, padding=8)
        form.pack(fill="x")
        self.f = {}
        for i, (k, lab, w) in enumerate((("item_id", "ID предмета", 10), ("price", "Цена (напр. 8м или 1з 20с)", 14), ("vendor", "Вендор", 20),
                                         ("npc_id", "ID NPC", 8), ("location", "Расположение", 34), ("stock", "Остаток", 6))):
            ttk.Label(form, text=lab).grid(row=0, column=i, sticky="w")
            self.f[k] = tk.StringVar()
            ttk.Entry(form, textvariable=self.f[k], width=w).grid(row=1, column=i, padx=2)
        btn = ttk.Frame(self, padding=(8, 0, 8, 8))
        btn.pack(fill="x")
        ttk.Button(btn, text="Добавить / обновить", command=self.add).pack(side="left", padx=3)
        ttk.Button(btn, text="Удалить выбранный", command=self.remove).pack(side="left", padx=3)
        ttk.Button(btn, text="Импорт CSV/JSON…", command=self.do_import).pack(side="left", padx=3)
        ttk.Button(btn, text="Wowhead: вендор", command=self.open_npc).pack(side="right", padx=3)
        ttk.Button(btn, text="Wowhead: предмет", command=self.open_item).pack(side="right", padx=3)
        self.refresh()

    def refresh(self):
        self.tv.delete(*self.tv.get_children())
        for v in sorted(self.items.values(), key=lambda v: v.item_id):
            self.tv.insert("", "end", iid=str(v.item_id), values=(v.item_id, fmt_money(v.price), v.vendor, v.npc_id or "", v.location, v.stock if v.stock is not None else ""))

    def add(self):
        g = {k: v.get().strip() for k, v in self.f.items()}
        try:
            price = parse_money(g["price"])
            row = dict(item_id=g["item_id"], price=price, vendor=g["vendor"], npc_id=g["npc_id"], location=g["location"], stock=g["stock"])
            v = vendors._parse(row)
        except (ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Вендоры", f"Проверьте поля: {exc}", parent=self)
            return
        self.items[v.item_id] = v
        vendors.save(self.path, self.items)
        self.refresh()

    def remove(self):
        for iid in self.tv.selection():
            self.items.pop(int(iid), None)
        vendors.save(self.path, self.items)
        self.refresh()

    def do_import(self):
        p = filedialog.askopenfilename(parent=self, filetypes=[("CSV или JSON", "*.csv *.json"), ("Все файлы", "*.*")])
        if not p:
            return
        try:
            new, errors = vendors.import_file(p)
        except Exception as exc:
            messagebox.showerror("Импорт", str(exc), parent=self)
            return
        self.items.update(new)
        vendors.save(self.path, self.items)
        self.refresh()
        msg = f"Импортировано: {len(new)}."
        if errors:
            msg += "\nПропущено:\n" + "\n".join(errors[:10])
        messagebox.showinfo("Импорт", msg, parent=self)

    def _sel(self):
        s = self.tv.selection()
        return self.items.get(int(s[0])) if s else None

    def open_item(self):
        v = self._sel()
        if v:
            webbrowser.open(item_url(v.item_id, self.app.base))

    def open_npc(self):
        v = self._sel()
        if v and v.npc_id:
            webbrowser.open(npc_url(v.npc_id, self.app.base))
        else:
            messagebox.showinfo("Wowhead", "У выбранного товара не указан ID NPC.", parent=self)
