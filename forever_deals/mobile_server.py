"""Маленький локальный веб-сервер: отдаёт телефону страницу и последний mobile.json по адресу http://IP:порт/токен/ в домашней сети.
Токен в адресе защищает от случайных соседей по сети; наружу (в интернет) сервер не публикуется."""
from __future__ import annotations

import json
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

STATIC = {"logic.js": "application/javascript; charset=utf-8", "manifest.webmanifest": "application/manifest+json",
          "icon.svg": "image/svg+xml"}
PAGE = Path(__file__).parent / "mobile"


def ensure_token(cfg: dict) -> str:
    if not cfg.get("mobile_token"):
        cfg["mobile_token"] = secrets.token_hex(8)
    return cfg["mobile_token"]


def local_ips() -> list:
    """Адреса этого компьютера в локальной сети (без обращения к интернету)."""
    ips = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))          # пакеты не уходят, система лишь выбирает интерфейс
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        ips += [i for i in socket.gethostbyname_ex(socket.gethostname())[2] if not i.startswith("127.")]
    except OSError:
        pass
    return list(dict.fromkeys(i for i in ips if not i.startswith("127.")))


class MobileServer:
    def __init__(self, home, token: str, port: int = 8765, host: str = "0.0.0.0"):
        self.home, self.token, self.host, self.port = Path(home), token, host, port
        self.httpd = None

    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, ctype, body: bytes, cache="no-store"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", cache)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = unquote(urlsplit(self.path).path)
                prefix = f"/{outer.token}/"
                if not path.startswith(prefix):
                    return self._send(404, "text/plain; charset=utf-8", b"404")
                name = path[len(prefix):]
                try:
                    if name == "":
                        return self._send(200, "text/html; charset=utf-8", (PAGE / "index.html").read_bytes())
                    if name == "data.json":
                        return self._send(200, "application/json; charset=utf-8", (outer.home / "mobile.json").read_bytes())
                    if name in STATIC:
                        return self._send(200, STATIC[name], (PAGE / name).read_bytes(), cache="max-age=300")
                except OSError:
                    msg = json.dumps({"error": "Данных ещё нет: выполните поиск на компьютере."}, ensure_ascii=False)
                    return self._send(404, "application/json; charset=utf-8", msg.encode("utf-8"))
                self._send(404, "text/plain; charset=utf-8", b"404")

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    def urls(self, ips=None) -> list:
        return [f"http://{ip}:{self.port}/{self.token}/" for ip in (local_ips() if ips is None else ips)]
