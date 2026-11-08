"""Окно приложения (tkinter, входит в стандартный Python для Windows)."""
from __future__ import annotations

import os
import queue
import re
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from . import appdata, report, runner, vendors, viewmodel as vm
from .blizzard import ApiError, Client
from .core import Settings, fmt_money, parse_money
from .links import item_url, npc_url
from .store import Store

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
        self.res, self.items = None, {}
        self.last_md, self.last_path = "", None
        self.auto = False
        self.sort_state = {}
        self.base = cfg.get("wowhead_base")
        self._build()
        self.after(300, self._poll)
        self.after(5000, self._tick)
        if not appdata.configured(cfg) and not cfg.get("demo"):
            self.after(400, lambda: WizardDialog(self))

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
        ttk.Button(btns, text="Сделки…", command=self.open_journal).pack(side="left", padx=4)
        ttk.Button(btns, text="Настройки…", command=self.open_settings).pack(side="left", padx=4)
        ttk.Button(btns, text="Папка отчётов", command=lambda: self._open_path(self.h / "reports")).pack(side="left", padx=4)

        box = ttk.LabelFrame(self, text="Будут проверяться", padding=8)
        box.pack(fill="x", padx=12)
        for i, t in enumerate(CHECKS):
            ttk.Label(box, text="• " + t).grid(row=i // 2, column=i % 2, sticky="w", padx=8)
        box.columnconfigure(0, weight=1)
        box.columnconfigure(1, weight=1)

        self.status = ttk.Label(self, text="Готов.", padding=(12, 6), wraplength=1250, justify="left")
        self.status.pack(fill="x")
        fl = ttk.Frame(self, padding=(12, 0))
        fl.pack(fill="x")
        ttk.Label(fl, text="Поиск по таблицам:").pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *a: self._render())
        ttk.Entry(fl, textvariable=self.filter_var, width=30).pack(side="left", padx=6)
        ttk.Label(fl, text="Клик по заголовку столбца — сортировка. Двойной клик по строке — предмет на Wowhead.",
                  foreground="#666").pack(side="left", padx=10)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(4, 6))
        self.top_tv = self._table(vm.TOP_COLS, vm.TOP_WIDTHS, "Топ-10")
        self.v_tv = self._table(vm.VENDOR_COLS, vm.VENDOR_WIDTHS, "Вендор → Аукцион")
        self.r_tv = self._table(vm.ROUTE_COLS, vm.ROUTE_WIDTHS, "Маршрут закупки", sortable=False)
        rep = ttk.Frame(self.nb)
        self.nb.add(rep, text="Отчёт")
        self.text = tk.Text(rep, wrap="word", font=("Consolas", 10))
        sb = ttk.Scrollbar(rep, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set, state="disabled")
        self.text.tag_configure("link", foreground="#0b5ed7", underline=True)
        self.text.tag_configure("h", font=("Segoe UI", 12, "bold"))
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        bar = ttk.Frame(self, padding=(12, 0, 12, 10))
        bar.pack(fill="x")
        ttk.Button(bar, text="Предмет на Wowhead", command=lambda: self._open_selected("item")).pack(side="left", padx=4)
        ttk.Button(bar, text="Вендор на Wowhead", command=lambda: self._open_selected("npc")).pack(side="left", padx=4)
        ttk.Button(bar, text="Скопировать список закупки", command=self.copy_route).pack(side="left", padx=4)
        ttk.Button(bar, text="Открыть отчёт в браузере", command=self.open_html).pack(side="left", padx=4)
        ttk.Button(bar, text="Сохранить отчёт как…", command=self.save_report).pack(side="left", padx=4)
        self._refresh_sched()

    def _table(self, heads, widths, title, sortable=True):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text=title)
        cols = [f"c{i}" for i in range(len(heads))]
        tv = ttk.Treeview(f, columns=cols, show="headings" if title != "Маршрут закупки" else "tree headings", selectmode="browse")
        for i, (c, hd, w) in enumerate(zip(cols, heads, widths)):
            cmd = (lambda tv=tv, i=i: self._sort(tv, i)) if sortable else ""
            tv.heading(c, text=hd, command=cmd)
            tv.column(c, width=w, anchor="w")
        if title == "Маршрут закупки":
            tv.column("#0", width=0, stretch=False)
        sb = ttk.Scrollbar(f, command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.bind("<Double-1>", lambda e: self._open_selected("item"))
        return tv

    def _sort(self, tv, col):
        self.sort_state[tv] = (col, not (self.sort_state.get(tv, (None, False))[0] == col and self.sort_state[tv][1]))
        self._render()

    def _sorted(self, tv, rows):
        col, desc = self.sort_state.get(tv, (None, False))
        if col is None:
            return rows
        return sorted(rows, key=lambda r: vm.sort_key(r[1][col]), reverse=desc)

    # ---------- действия ----------
    def _refresh_sched(self):
        lr = appdata.last_run(self.h)
        last = datetime.fromisoformat(lr).strftime("%d.%m.%Y %H:%M") if lr else "ещё не запускался"
        mode = "  ·  ДЕМО-РЕЖИМ" if self.cfg.get("demo") else ""
        self.sched.config(text=f"Ежедневно · Вечером ({self.cfg['run_time']})  ·  Последний запуск: {last}{mode}")

    def run_now(self, auto=False):
        if self.running:
            return
        self.auto = auto
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
                    self.status.config(text="Ошибка: " + str(payload).rstrip(".") + (
                        f". Повтор автоматически через {self.cfg.get('retry_minutes', 30)} мин." if self.auto else ""))
                    if not self.auto:                      # при автозапуске окно не выскакивает
                        messagebox.showerror("Ошибка", str(payload))
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        self.after(300, self._poll)

    def _tick(self):
        if not self.running and not self.cfg.get("demo") and appdata.configured(self.cfg) and appdata.is_due(self.cfg, self.h, datetime.now()):
            self.run_now(auto=True)
        self.after(30000, self._tick)

    def _show(self, res, md, path, items):
        self.running = False
        self.run_btn.state(["!disabled"])
        self.res, self.items, self.last_md, self.last_path = res, items, md, path
        self._render()
        self._refresh_sched()
        warn = f" Предупреждения: {len(res.warnings)} (см. вкладку «Отчёт»)." if res.warnings else ""
        self.status.config(text=f"Готово: {len(res.top)} позиций в топе, отчёт сохранён: {path}.{warn}")
        if self.auto:                                      # автозапуск: привлекаем внимание, не блокируя работу
            self.bell()
            self.deiconify()
            self.lift()
            self.title(f"WoW Forever — отчёт готов ({len(res.top)} в топе)")

    def _fill(self, tv, rows, empty_hint):
        tv.delete(*tv.get_children())
        q = self.filter_var.get().strip().lower()
        rows = [r for r in rows if not q or any(q in str(c).lower() for c in r[1])]
        for ids, vals in self._sorted(tv, rows):
            iid = tv.insert("", "end", values=vals)
            self.rows[iid] = ids
        if not rows:
            tv.insert("", "end", values=(empty_hint,) + ("",) * (len(tv["columns"]) - 1))

    def _render(self):
        if self.res is None:
            return
        self.rows.clear()
        self._fill(self.top_tv, vm.top_rows(self.res, self.items),
                   "Нет позиций, прошедших фильтры (см. «Вендор → Аукцион» и причины отказа)")
        self._fill(self.v_tv, vm.vendor_rows(self.res, self.items),
                   "Список вендоров пуст: нажмите «Вендоры…» → «Вставить список» (ID предмета; цена; вендор; NPC; место)")
        self.r_tv.delete(*self.r_tv.get_children())
        tree = vm.route_tree(self.res, self.items)
        for parent, kids in tree:
            pid = self.r_tv.insert("", "end", values=parent, open=True, tags=("vendor",))
            for ids, vals in kids:
                iid = self.r_tv.insert(pid, "end", values=vals)
                self.rows[iid] = ids
        if not tree:
            self.r_tv.insert("", "end", values=("Пока нечего закупать: нет вендорных позиций, прошедших фильтры", "", "", "", ""))
        self.r_tv.tag_configure("vendor", background="#eef3fb")
        self._render_report()

    def _render_report(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        for ln in self.last_md.split("\n"):
            if ln.startswith("#"):
                self.text.insert("end", ln.lstrip("# ") + "\n", "h")
                continue
            pos = 0
            for m in re.finditer(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", ln):
                self.text.insert("end", ln[pos:m.start()].replace("**", ""))
                tag = f"lnk{self.text.index('end')}"
                self.text.insert("end", m.group(1), ("link", tag))
                self.text.tag_bind(tag, "<Button-1>", lambda e, u=m.group(2): webbrowser.open(u))
                self.text.tag_bind(tag, "<Enter>", lambda e: self.text.config(cursor="hand2"))
                self.text.tag_bind(tag, "<Leave>", lambda e: self.text.config(cursor=""))
                pos = m.end()
            self.text.insert("end", ln[pos:].replace("**", "") + "\n")
        self.text.config(state="disabled")

    def _selected(self):
        tv = self.nb.nametowidget(self.nb.select()).winfo_children()[0]
        sel = tv.selection() if isinstance(tv, ttk.Treeview) else ()
        return self.rows.get(sel[0]) if sel else None

    def _open_selected(self, what):
        row = self._selected()
        if not row:
            messagebox.showinfo("Wowhead", "Выберите строку с товаром в таблице.")
            return
        if self.cfg.get("demo"):
            messagebox.showinfo("Wowhead", "Это демо-данные: такого предмета на Wowhead нет.")
            return
        item_id, npc_id = row
        if what == "npc":
            if not npc_id:
                messagebox.showinfo("Wowhead", "Для этой позиции не указан NPC. Добавьте npc_id в окне «Вендоры».")
                return
            webbrowser.open(npc_url(npc_id, self.base))
        else:
            webbrowser.open(item_url(item_id, self.base))

    def copy_route(self):
        if self.res is None:
            messagebox.showinfo("Закупка", "Сначала выполните поиск.")
            return
        txt = report.route_text(report.shopping_route(self.res, self.items))
        self.clipboard_clear()
        self.clipboard_append(txt or "Нечего закупать.")
        self.status.config(text="Список закупки скопирован в буфер обмена.")

    def open_html(self):
        if not self.last_path:
            messagebox.showinfo("Отчёт", "Сначала выполните поиск.")
            return
        webbrowser.open(self.last_path.with_suffix(".html").as_uri())

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

    def open_journal(self):
        JournalDialog(self)

    def open_vendors(self):
        if self.cfg.get("demo"):
            messagebox.showinfo("Вендоры", "В демо-режиме используется встроенный вымышленный список вендоров. "
                                "Отключите демо-режим в настройках, чтобы вести свой список.")
            return
        VendorsDialog(self)


class SettingsDialog(tk.Toplevel):
    API = [("client_id", "Client ID", "из develop.battle.net → Create client"),
           ("client_secret", "Client Secret", "хранится в файле config.json; можно задать переменной FD_CLIENT_SECRET"),
           ("region", "Регион", "eu, us, kr или tw"),
           ("locale", "Язык названий", "ru_RU, en_US …"),
           ("dynamic_namespace", "Неймспейс аукциона", "dynamic-…; кнопка «Найти неймспейс» пробует варианты"),
           ("static_namespace", "Неймспейс предметов", "static-…; подставляется по шаблону, проверьте"),
           ("connected_realm_id", "ID связанного реалма", "кнопка «Реалмы…»"),
           ("auction_house_id", "ID аукциона", "кнопка «Аукционы реалма…»"),
           ("run_time", "Время ежедневного запуска", "ЧЧ:ММ, по времени компьютера"),
           ("wowhead_base", "Базовый адрес Wowhead", "ссылки строятся как адрес/item=ID и адрес/npc=ID; формат для Forever не подтверждён")]
    PCT = [("cut", "Комиссия этого аукциона, %", "Classic: 5% своя фракция, 15% нейтральный; для Forever не подтверждено"),
           ("deposit_pct", "Депозит, % от цены вендору за 12 ч", "возвращается при продаже; тут учитывается только потеря при непродаже"),
           ("p_sell", "Вероятность продать лот, %", "доля лотов, которые продаются за срок"),
           ("share", "Ваша доля рынка, %", "какую часть продаж вы реально заберёте")]
    NUM = [("min_rate", "Мин. продаж в день, шт", "реже — рынок считается тонким"),
           ("min_markup", "Мин. наценка вендорных, ×", "10 = продажа минимум в 10 раз дороже закупки"),
           ("min_net", "Мин. прибыль с шт., в меди", "100 меди = 1 серебро"),
           ("budget_item", "Бюджет на позицию, в меди", "10000 меди = 1 золото"),
           ("min_quantity", "Мин. штук на аукционе, шт", "меньше — изолированный лот, цене не верим"),
           ("sales_haircut", "Поправка продаж (0.7 = 70%)", "убыль лотов включает отмены, поэтому берём долю")]

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Настройки")
        self.geometry("720x860")
        self.vars = {}
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        s = appdata.load_settings(app.cfg)
        r = 0

        def row(key, label, hint, value, secret=False):
            nonlocal r
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=(4, 0))
            v = tk.StringVar(value=value)
            ttk.Entry(f, textvariable=v, width=44, show="*" if secret else "").grid(row=r, column=1, sticky="ew", pady=(4, 0))
            ttk.Label(f, text=hint, foreground="#777", wraplength=330).grid(row=r + 1, column=1, sticky="w")
            self.vars[key] = v
            r += 2
        for key, label, hint in self.API:
            row(key, label, hint, str(app.cfg.get(key, "")), key == "client_secret")
        ttk.Label(f, text="Расчёт", font=("Segoe UI", 10, "bold")).grid(row=r, column=0, sticky="w", pady=(10, 0))
        r += 1
        for key, label, hint in self.PCT:
            row("s_" + key, label, hint, vm.to_percent(getattr(s, key)))
        for key, label, hint in self.NUM:
            row("s_" + key, label, hint, str(getattr(s, key)))
        self.demo = tk.BooleanVar(value=bool(app.cfg.get("demo")))
        ttk.Checkbutton(f, text="Демо-режим (вымышленные данные, без ключей)", variable=self.demo).grid(row=r, column=0, columnspan=2, sticky="w", pady=6)
        r += 1
        helper = ttk.Frame(f)
        helper.grid(row=r, column=0, columnspan=2, sticky="ew")
        ttk.Button(helper, text="Найти неймспейс", command=self.find_ns).pack(side="left", padx=2)
        ttk.Button(helper, text="Реалмы…", command=self.find_realms).pack(side="left", padx=2)
        ttk.Button(helper, text="Аукционы реалма…", command=self.find_houses).pack(side="left", padx=2)
        ttk.Button(helper, text="Проверить подключение", command=self.check).pack(side="left", padx=2)
        r += 1
        self.info = tk.Text(f, height=6, wrap="word", state="disabled")
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
        for k, *_ in self.API:
            cfg[k] = self.vars[k].get().strip()
        return Client(cfg)

    def check(self):
        self.say("Проверяю подключение…")
        c = self._client()
        self.app.bg(c.check, lambda r: self.say(f"Ошибка: {r}") if isinstance(r, Exception)
                    else self.say("\n".join(("✅ " if ok else "❌ ") + m for ok, m in r)))

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
            for k, *_ in self.API:
                cfg[k] = self.vars[k].get().strip()
            hh, mm = cfg["run_time"].split(":")
            assert 0 <= int(hh) < 24 and 0 <= int(mm) < 60
            base = appdata.load_settings(cfg)
            kw = {}
            for k, *_ in self.PCT:
                kw[k] = vm.from_percent(self.vars["s_" + k].get())
            for k, *_ in self.NUM:
                kw[k] = type(getattr(base, k))(self.vars["s_" + k].get().replace(",", "."))
            cut = kw.pop("cut")
            appdata.settings_to_cfg(cfg, Settings(**{**base.__dict__, **kw}))
            appdata.set_house_cut(cfg, cut)
        except (ValueError, AssertionError):
            messagebox.showerror("Настройки", "Проверьте числа (проценты 0–100) и время запуска (ЧЧ:ММ).", parent=self)
            return
        cfg["demo"] = self.demo.get()
        appdata.save_cfg(self.app.h, cfg)
        self.app.base = cfg.get("wowhead_base")
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
        ttk.Button(btn, text="Вставить список…", command=self.paste).pack(side="left", padx=3)
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

    def paste(self):
        win = tk.Toplevel(self)
        win.title("Вставить список вендорных товаров")
        win.geometry("760x420")
        ttk.Label(win, wraplength=720, padding=8, text=(
            "По строке на товар, поля через «;»: предмет (ID или ссылка Wowhead) ; цена (8м, 1з 20с) ; вендор ; "
            "NPC (ID или ссылка) ; расположение ; остаток.\nПример: https://www.wowhead.com/forever/item=2589 ; 8м ; Стефани Тёрнер ; "
            "https://www.wowhead.com/forever/npc=777 ; Штормград, Ремесленный квартал")).pack(fill="x")
        box = tk.Text(win, height=14)
        box.pack(fill="both", expand=True, padx=8)

        def go():
            new, errors = vendors.parse_text(box.get("1.0", "end"))
            self.items.update(new)
            vendors.save(self.path, self.items)
            self.refresh()
            msg = f"Добавлено: {len(new)}."
            if errors:
                msg += "\nПропущено:\n" + "\n".join(errors[:10])
            messagebox.showinfo("Вендоры", msg, parent=win)
            if new:
                win.destroy()
        ttk.Button(win, text="Добавить", command=go).pack(pady=8)

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


class JournalDialog(tk.Toplevel):
    """Журнал реальных сделок: куплено/продано, остаток, прибыль. Покупка у вендора уменьшает его остаток."""

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Сделки")
        self.geometry("860x520")
        self.store = Store(app.h / "history.sqlite")
        self.cut = appdata.load_settings(app.cfg).cut
        cols = ("item", "name", "bought", "sold", "left", "spent", "revenue", "realized")
        self.tv = ttk.Treeview(self, columns=cols, show="headings", height=12)
        for c, hd, w in zip(cols, ("ID", "Товар", "Куплено", "Продано", "Остаток", "Потрачено", "Выручка", "Прибыль (после комиссии)"),
                            (70, 220, 70, 70, 70, 100, 100, 150)):
            self.tv.heading(c, text=hd)
            self.tv.column(c, width=w)
        self.tv.pack(fill="both", expand=True, padx=8, pady=8)
        form = ttk.Frame(self, padding=8)
        form.pack(fill="x")
        self.f = {k: tk.StringVar() for k in ("item", "qty", "price")}
        self.kind = tk.StringVar(value="buy")
        for i, (k, lab, w) in enumerate((("item", "ID предмета", 10), ("qty", "Количество", 8), ("price", "Цена за шт. (8м, 1з 20с)", 16))):
            ttk.Label(form, text=lab).grid(row=0, column=i, sticky="w")
            ttk.Entry(form, textvariable=self.f[k], width=w).grid(row=1, column=i, padx=3)
        ttk.Radiobutton(form, text="Купил", variable=self.kind, value="buy").grid(row=1, column=3, padx=6)
        ttk.Radiobutton(form, text="Продал", variable=self.kind, value="sell").grid(row=1, column=4, padx=6)
        ttk.Button(form, text="Записать", command=self.add).grid(row=1, column=5, padx=8)
        ttk.Label(self, foreground="#666", wraplength=820, padding=8, text=(
            "Прибыль считается по средней цене покупки и комиссии аукциона из настроек. "
            "Записи нужны, чтобы сверить прогноз приложения с реальностью.")).pack(fill="x")
        self.refresh()

    def refresh(self):
        self.tv.delete(*self.tv.get_children())
        names = {}
        if self.app.res:
            names = {e.cand.item_id: e.cand.name for e in self.app.res.ranked + self.app.res.rejected}
        for r in self.store.trade_summary(self.cut):
            self.tv.insert("", "end", values=(r["item_id"], names.get(r["item_id"]) or (self.store.get_item(r["item_id"]) or {}).get("name", "?"),
                                              r["bought"], r["sold"], r["left"], fmt_money(r["spent"]), fmt_money(r["revenue"]), fmt_money(r["realized"])))

    def add(self):
        try:
            item, qty, price = int(self.f["item"].get()), int(self.f["qty"].get()), parse_money(self.f["price"].get())
            self.store.add_trade(int(time.time()), item, self.kind.get(), qty, price)
        except ValueError as exc:
            messagebox.showerror("Сделки", f"Проверьте поля: {exc}", parent=self)
            return
        if self.kind.get() == "buy" and not self.app.cfg.get("demo"):
            path = self.app.h / "vendors.json"
            items = vendors.load(path)
            vendors.apply_purchase(items, item, qty)           # остаток у вендора уменьшается
            vendors.save(path, items)
        self.refresh()


class WizardDialog(tk.Toplevel):
    """Первый запуск: что нужно сделать, по шагам, с кнопками."""
    STEPS = [
        "1. Зайдите на develop.battle.net (войдите своим аккаунтом Battle.net) → Create client. Скопируйте Client ID и Client Secret.",
        "2. Нажмите «Настройки…», вставьте ключи и регион, затем «Найти неймспейс».",
        "3. Там же нажмите «Реалмы…» и «Аукционы реалма…», впишите ID своего реалма и аукциона.",
        "4. Нажмите «Проверить подключение»: приложение покажет, что работает, а что нет.",
        "5. Внесите вендорные товары: «Вендоры…» → «Вставить список…» (ID с Wowhead, цена, вендор, место).",
        "6. «Выполнить сейчас». Дальше приложение само запустится в заданное время, пока оно открыто.",
    ]

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Первый запуск")
        self.geometry("680x420")
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Приложению нужен доступ к API Blizzard", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        for t in self.STEPS:
            ttk.Label(f, text=t, wraplength=630, justify="left").pack(anchor="w", pady=3)
        ttk.Label(f, foreground="#666", wraplength=630, text=(
            "Неймспейсы и форматы данных Forever в документации Blizzard не подтверждены, поэтому шаг 4 важен. "
            "Хотите сначала посмотреть, как всё выглядит? Включите демо-режим.")).pack(anchor="w", pady=8)
        b = ttk.Frame(f)
        b.pack(anchor="w")
        ttk.Button(b, text="Открыть настройки", command=lambda: (self.destroy(), app.open_settings())).pack(side="left", padx=3)
        ttk.Button(b, text="Демо-режим", command=self.demo).pack(side="left", padx=3)
        ttk.Button(b, text="Позже", command=self.destroy).pack(side="left", padx=3)

    def demo(self):
        self.app.cfg["demo"] = True
        self.app._refresh_sched()
        self.destroy()
        self.app.run_now()
