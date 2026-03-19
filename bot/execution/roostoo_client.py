import hashlib
import hmac
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests


class RoostooClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: str = "https://mock-api.roostoo.com",
        timeout: int = 15,
    ) -> None:
        self.api_key = api_key or os.getenv("ROOSTOO_API_KEY")
        self.api_secret = api_secret or os.getenv("ROOSTOO_API_SECRET")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @staticmethod
    def _timestamp_ms() -> str:
        return str(int(time.time() * 1000))

    @staticmethod
    def _serialize_params(params: Dict[str, Any]) -> str:
        cleaned = {k: v for k, v in params.items() if v is not None}
        sorted_items = sorted(cleaned.items(), key=lambda x: x[0])
        return urlencode(sorted_items)

    def _sign(self, params: Dict[str, Any]) -> tuple[str, str]:
        if not self.api_secret:
            raise ValueError("Missing ROOSTOO_API_SECRET")
        payload = self._serialize_params(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return payload, signature

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
        ts_only: bool = False,
    ) -> Dict[str, Any]:
        params = dict(params or {})
        headers: Dict[str, str] = {}

        if signed or ts_only:
            params["timestamp"] = self._timestamp_ms()

        if signed:
            if not self.api_key:
                raise ValueError("Missing ROOSTOO_API_KEY")
            payload, signature = self._sign(params)
            headers["RST-API-KEY"] = self.api_key
            headers["MSG-SIGNATURE"] = signature

            if method.upper() == "GET":
                url = f"{self.base_url}{path}?{payload}"
                response = requests.get(url, headers=headers, timeout=self.timeout)
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                url = f"{self.base_url}{path}"
                response = requests.post(url, headers=headers, data=payload, timeout=self.timeout)
        else:
            url = f"{self.base_url}{path}"
            if method.upper() == "GET":
                response = requests.get(url, params=params, headers=headers, timeout=self.timeout)
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                response = requests.post(url, headers=headers, data=params, timeout=self.timeout)

        response.raise_for_status()
        data = response.json()

        # Roostoo often returns {"Success": false, "ErrMsg": "..."} with HTTP 200
        if isinstance(data, dict) and data.get("Success") is False:
            raise RuntimeError(f"Roostoo API error: {data.get('ErrMsg', 'Unknown error')}")

        return data

    # ---------- public ----------
    def server_time(self) -> Dict[str, Any]:
        return self._request("GET", "/v3/serverTime")

    def exchange_info(self) -> Dict[str, Any]:
        return self._request("GET", "/v3/exchangeInfo")

    def ticker(self, pair: Optional[str] = None) -> Dict[str, Any]:
        params = {"pair": pair} if pair else {}
        return self._request("GET", "/v3/ticker", params=params, ts_only=True)

    # ---------- signed ----------
    def balance(self) -> Dict[str, Any]:
        return self._request("GET", "/v3/balance", signed=True)

    def pending_count(self) -> Dict[str, Any]:
        return self._request("GET", "/v3/pending_count", signed=True)

    def place_order(
        self,
        *,
        pair: str,
        side: str,
        order_type: str,
        quantity: str | float,
        price: Optional[str | float] = None,
    ) -> Dict[str, Any]:
        side = side.upper()
        order_type = order_type.upper()

        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if order_type not in {"MARKET", "LIMIT"}:
            raise ValueError("order_type must be MARKET or LIMIT")
        if order_type == "LIMIT" and price is None:
            raise ValueError("LIMIT orders require price")

        payload: Dict[str, Any] = {
            "pair": pair,
            "side": side,
            "type": order_type,
            "quantity": str(quantity),
        }
        if price is not None:
            payload["price"] = str(price)

        return self._request("POST", "/v3/place_order", params=payload, signed=True)

    def query_order(
        self,
        *,
        order_id: Optional[int | str] = None,
        pair: Optional[str] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
        pending_only: Optional[bool] = None,
    ) -> Dict[str, Any]:
        if order_id is not None and any(v is not None for v in [pair, offset, limit, pending_only]):
            raise ValueError("When order_id is provided, do not pass pair/offset/limit/pending_only")

        payload: Dict[str, Any] = {}
        if order_id is not None:
            payload["order_id"] = str(order_id)
        else:
            if pair is not None:
                payload["pair"] = pair
            if offset is not None:
                payload["offset"] = str(offset)
            if limit is not None:
                payload["limit"] = str(limit)
            if pending_only is not None:
                payload["pending_only"] = "TRUE" if pending_only else "FALSE"

        return self._request("POST", "/v3/query_order", params=payload, signed=True)

    def cancel_order(
        self,
        *,
        order_id: Optional[int | str] = None,
        pair: Optional[str] = None,
    ) -> Dict[str, Any]:
        if order_id is not None and pair is not None:
            raise ValueError("Pass either order_id or pair, not both")

        payload: Dict[str, Any] = {}
        if order_id is not None:
            payload["order_id"] = str(order_id)
        elif pair is not None:
            payload["pair"] = pair

        return self._request("POST", "/v3/cancel_order", params=payload, signed=True)


if __name__ == "__main__":
    client = RoostooClient()

    print("Server time:")
    print(client.server_time())

    print("\nExchange info:")
    print(client.exchange_info())

    print("\nTicker BTC/USD:")
    print(client.ticker("BTC/USD"))

    print("\nBalance:")
    print(client.balance())
