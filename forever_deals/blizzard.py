"""Клиент API Blizzard (только чтение). Неймспейсы Forever не подтверждены: всё настраивается."""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

NAMESPACE_GUESSES = ["dynamic-classic-{r}", "dynamic-classicann-{r}", "dynamic-forever-{r}",
                     "dynamic-classic1x-{r}", "dynamic-{r}"]


class ApiError(Exception):
    pass


class Client:
    def __init__(self, cfg: dict, opener=urllib.request.urlopen):
        self.cfg = cfg
        self._open = opener
        self._token = None
        self._token_until = 0.0

    @property
    def host(self):
        return f"https://{self.cfg['region']}.api.blizzard.com"

    def _request(self, req):
        try:
            with self._open(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ApiError(f"HTTP {exc.code} для {req.full_url.split('?')[0]}") from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"нет связи: {exc.reason}") from exc

    def token(self):
        if self._token and time.time() < self._token_until:
            return self._token
        cid, secret = self.cfg.get("client_id", ""), self.cfg.get("client_secret", "")
        if not cid or not secret:
            raise ApiError("укажите Client ID и Client Secret в настройках")
        auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        req = urllib.request.Request("https://oauth.battle.net/token", data=b"grant_type=client_credentials",
                                     headers={"Authorization": f"Basic {auth}"}, method="POST")
        data = self._request(req)
        self._token = data["access_token"]
        self._token_until = time.time() + data.get("expires_in", 3600) - 60
        return self._token

    def url(self, path: str, namespace: str, **extra) -> str:
        q = {"namespace": namespace, "locale": self.cfg.get("locale", "en_US"), **extra}
        return f"{self.host}{path}?{urllib.parse.urlencode(q)}"

    def get(self, path: str, namespace: str):
        req = urllib.request.Request(self.url(path, namespace),
                                     headers={"Authorization": f"Bearer {self.token()}"})
        return self._request(req)

    def public_url(self, path, namespace):
        return self.url(path, namespace)

    # --- настройка ---
    def discover_namespaces(self):
        found = []
        for tpl in NAMESPACE_GUESSES:
            ns = tpl.format(r=self.cfg["region"])
            try:
                self.get("/data/wow/connected-realm/index", ns)
                found.append(ns)
            except ApiError:
                continue
        return found

    def connected_realms(self, limit=60):
        ns = self.cfg["dynamic_namespace"]
        index = self.get("/data/wow/connected-realm/index", ns)
        ids = [int(r["href"].split("/connected-realm/")[1].split("?")[0]) for r in index.get("connected_realms", [])][:limit]

        def one(i):
            try:
                d = self.get(f"/data/wow/connected-realm/{i}", ns)
                return i, ", ".join(r.get("name", "?") for r in d.get("realms", []))
            except ApiError:
                return i, "?"
        with ThreadPoolExecutor(8) as ex:
            return list(ex.map(one, ids))

    def auction_houses(self):
        realm = self.cfg["connected_realm_id"]
        d = self.get(f"/data/wow/connected-realm/{realm}/auctions/index", self.cfg["dynamic_namespace"])
        return [(h["id"], h.get("name", str(h["id"]))) for h in d.get("auctions", d.get("auction_houses", []))]

    # --- данные ---
    def auction_path(self):
        return self.cfg["auction_path"].format(realm=self.cfg["connected_realm_id"], house=self.cfg["auction_house_id"])

    def auction_listings(self) -> dict:
        d = self.get(self.auction_path(), self.cfg["dynamic_namespace"])
        out = {}
        for a in d.get("auctions", []):
            qty = int(a.get("quantity") or 0)
            if a.get("unit_price"):
                price = int(a["unit_price"])
            elif a.get("buyout") and qty:
                price = int(a["buyout"]) // qty
            else:
                continue                      # только ставка без выкупа
            out.setdefault(a["item"]["id"], []).append((price, qty))
        return out

    def fetch_item(self, item_id: int) -> dict:
        d = self.get(self.cfg["item_path"].format(id=item_id), self.cfg["static_namespace"])
        return {"name": d.get("name", f"#{item_id}"),
                "class_id": d.get("item_class", {}).get("id"),
                "subclass_id": d.get("item_subclass", {}).get("id"),
                "purchase_price": int(d.get("purchase_price") or 0),
                "sell_price": int(d.get("sell_price") or 0)}

    def sources(self):
        return [("Аукцион (API Blizzard)", self.public_url(self.auction_path(), self.cfg["dynamic_namespace"]).split("&locale")[0]),
                ("Предметы (API Blizzard)", self.public_url(self.cfg["item_path"].format(id="{id}"), self.cfg["static_namespace"]).split("&locale")[0])]
