"""Разбор файлов SavedVariables (Lua-таблицы): только данные, код не выполняется."""
from __future__ import annotations

import re

_NUM = re.compile(r"-?(?:0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ESC = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "\n": "\n", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


class _P:
    def __init__(self, text):
        self.t, self.i = text, 0

    def fail(self, msg):
        raise ValueError(f"Lua: {msg} (позиция {self.i})")

    def skip(self):
        t = self.t
        while self.i < len(t):
            if t[self.i] in " \t\r\n":
                self.i += 1
            elif t.startswith("--", self.i):
                if t.startswith("--[[", self.i):
                    end = t.find("]]", self.i + 4)
                    if end < 0:
                        self.fail("не закрыт комментарий")
                    self.i = end + 2
                else:
                    nl = t.find("\n", self.i)
                    self.i = len(t) if nl < 0 else nl + 1
            else:
                break

    def peek(self):
        self.skip()
        return self.t[self.i] if self.i < len(self.t) else ""

    def expect(self, ch):
        if self.peek() != ch:
            self.fail(f"ожидалось {ch!r}")
        self.i += 1

    def string(self):
        q = self.t[self.i]
        self.i += 1
        buf = bytearray()
        while True:
            if self.i >= len(self.t):
                self.fail("не закрыта строка")
            c = self.t[self.i]
            if c == q:
                self.i += 1
                return buf.decode("utf-8", errors="replace")
            if c == "\\":
                self.i += 1
                d = re.match(r"\d{1,3}", self.t[self.i:self.i + 3])
                if d:
                    buf.append(int(d.group()) & 255)
                    self.i += len(d.group())
                    continue
                c = _ESC.get(self.t[self.i], self.t[self.i])
            buf += c.encode("utf-8")
            self.i += 1

    def value(self):
        c = self.peek()
        if c == "":
            self.fail("неожиданный конец файла")
        if c == "{":
            return self.table()
        if c in "\"'":
            return self.string()
        m = _NUM.match(self.t, self.i)
        if m:
            self.i = m.end()
            txt = m.group()
            return int(txt, 16) if "x" in txt.lower() else (float(txt) if re.search(r"[.eE]", txt) else int(txt))
        m = _NAME.match(self.t, self.i)
        if m:
            self.i = m.end()
            return {"true": True, "false": False, "nil": None}.get(m.group(), m.group())
        self.fail("ожидалось значение")

    def table(self):
        self.expect("{")
        out, idx = {}, 1
        while True:
            c = self.peek()
            if c == "}":
                self.i += 1
                return out
            if c == "":
                self.fail("не закрыта таблица")
            if c == "[":
                self.i += 1
                key = self.value()
                self.expect("]")
                self.expect("=")
                out[key] = self.value()
            else:
                m = _NAME.match(self.t, self.i)
                save = self.i
                if m and self._followed_by_eq(m.end()):
                    self.i = m.end()
                    self.expect("=")
                    out[m.group()] = self.value()
                else:
                    self.i = save
                    out[idx] = self.value()
                    idx += 1
            if self.peek() in ",;":
                self.i += 1

    def _followed_by_eq(self, pos):
        j = pos
        while j < len(self.t) and self.t[j] in " \t\r\n":
            j += 1
        return j < len(self.t) and self.t[j] == "=" and not self.t.startswith("==", j)


def parse(text: str) -> dict:
    """Верхний уровень: Имя = значение. -> {имя: значение}. ValueError при некорректном файле."""
    p = _P(text)
    out = {}
    while p.peek():
        m = _NAME.match(p.t, p.i)
        if not m:
            p.fail("ожидалось имя переменной")
        p.i = m.end()
        p.expect("=")
        out[m.group()] = p.value()
    return out
