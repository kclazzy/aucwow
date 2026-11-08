"""Безопасный вывод: на Windows консоль может быть в cp1252/cp866, и русский текст не должен ронять приложение."""
from __future__ import annotations

import sys


def make_safe(stream):
    """Неподходящие символы заменяются, а не вызывают UnicodeEncodeError. Для None (exe без консоли) и обычных потоков ничего не делает."""
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(errors="replace")


def setup():
    make_safe(sys.stdout)
    make_safe(sys.stderr)
