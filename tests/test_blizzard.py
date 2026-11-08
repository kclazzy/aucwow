import io, json, unittest
from forever_deals.blizzard import Client, ApiError

CFG = {"region": "eu", "locale": "ru_RU", "client_id": "id", "client_secret": "sec",
       "dynamic_namespace": "dynamic-x-eu", "static_namespace": "static-x-eu",
       "connected_realm_id": 5, "auction_house_id": 2,
       "auction_path": "/data/wow/connected-realm/{realm}/auctions/{house}", "item_path": "/data/wow/item/{id}"}


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake_opener(calls):
    def opener(req, timeout=0):
        url = req.full_url
        calls.append(url)
        if "oauth.battle.net" in url:
            return Resp(json.dumps({"access_token": "T", "expires_in": 3600}).encode())
        if "/auctions/2" in url:
            return Resp(json.dumps({"auctions": [
                {"id": 1, "item": {"id": 10}, "quantity": 20, "unit_price": 150},
                {"id": 2, "item": {"id": 11}, "quantity": 1, "buyout": 5000},
                {"id": 3, "item": {"id": 12}, "quantity": 1, "bid": 99}]}).encode())
        if "/item/10" in url:
            return Resp(json.dumps({"name": "Нить", "item_class": {"id": 7}, "item_subclass": {"id": 5},
                                    "purchase_price": 8, "sell_price": 2}).encode())
        raise AssertionError(url)
    return opener


class BlizzardTest(unittest.TestCase):
    def test_listings_unit_price_and_buyout_and_bid_only(self):
        calls = []
        c = Client(CFG, fake_opener(calls))
        out = c.auction_listings()
        self.assertEqual(out, {10: [(150, 20)], 11: [(5000, 1)]})
        self.assertIn("namespace=dynamic-x-eu", calls[-1])

    def test_item_parsing(self):
        c = Client(CFG, fake_opener([]))
        self.assertEqual(c.fetch_item(10), {"name": "Нить", "class_id": 7, "subclass_id": 5, "purchase_price": 8, "sell_price": 2})

    def test_missing_credentials_message(self):
        with self.assertRaises(ApiError):
            Client({**CFG, "client_id": ""}, fake_opener([])).token()


if __name__ == "__main__":
    unittest.main()
