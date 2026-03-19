import os
import time
import hmac
import hashlib
from typing import Any, Dict, Optional

import requests


class RoostooClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 10,
    ):
        self.api_key = api_key or os.getenv("ROOSTOO_API_KEY", "")
        self.api_secret = api_secret or os.getenv("ROOSTOO_API_SECRET", "")
        self.base_url = (base_url or os.getenv("ROOSTOO_BASE_URL", "https://mock-api.roostoo.com")).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    @staticmethod
    def _timestamp_ms() -> int:
        return int(time.time() * 1000)

    def _build_query_string(self, params: Dict[str, Any]) -> str:
        return "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))

    def _sign(self, params: Dict[str, Any]) -> str:
        query_string = self._build_query_string(params)
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _headers(self, signed: bool = False) -> Dict[str, str]:
        headers = {}
        if signed:
            headers["RST-API-KEY"] = self.api_key
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        return headers

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        response.raise_for_status()
        data = response.json()

        # Roostoo often returns Success=false instead of 4xx/5xx
        if isinstance(data, dict) and data.get("Success") is False:
            err = data.get("ErrMsg", "Unknown Roostoo API error")
            raise RuntimeError(err)

        return data

    def get_server_time(self) -> Dict[str, Any]:
        url = f"{self.base_url}/v3/serverTime"
        response = self.session.get(url, timeout=self.timeout)
        return self._handle_response(response)

    def get_exchange_info(self) -> Dict[str, Any]:
        url = f"{self.base_url}/v3/exchangeInfo"
        response = self.session.get(url, timeout=self.timeout)
        return self._handle_response(response)

    def get_ticker(self, pair: Optional[str] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/v3/ticker"
        params: Dict[str, Any] = {"timestamp": self._timestamp_ms()}
        if pair:
            params["pair"] = pair

        response = self.session.get(url, params=params, timeout=self.timeout)
        return self._handle_response(response)

    def get_balance(self) -> Dict[str, Any]:
        url = f"{self.base_url}/v3/balance"
        params = {"timestamp": self._timestamp_ms()}
        headers = self._headers(signed=True)
        headers["MSG-SIGNATURE"] = self._sign(params)

        response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
        return self._handle_response(response)

    def pending_count(self) -> Dict[str, Any]:
        url = f"{self.base_url}/v3/pending_count"
        params = {"timestamp": self._timestamp_ms()}
        headers = self._headers(signed=True)
        headers["MSG-SIGNATURE"] = self._sign(params)

        response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
        return self._handle_response(response)

    def place_order(
        self,
        pair: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/v3/place_order"

        payload: Dict[str, Any] = {
            "timestamp": self._timestamp_ms(),
            "pair": pair,
            "side": side.upper(),
            "quantity": quantity,
            "type": order_type.upper(),
        }

        if payload["type"] == "LIMIT":
            if price is None:
                raise ValueError("LIMIT order requires price")
            payload["price"] = price

        headers = self._headers(signed=True)
        headers["MSG-SIGNATURE"] = self._sign(payload)

        response = self.session.post(url, data=payload, headers=headers, timeout=self.timeout)
        return self._handle_response(response)

    def query_order(
        self,
        order_id: Optional[int] = None,
        pair: Optional[str] = None,
        pending_only: Optional[bool] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/v3/query_order"

        payload: Dict[str, Any] = {"timestamp": self._timestamp_ms()}
        if order_id is not None:
            payload["order_id"] = order_id
        if pair is not None:
            payload["pair"] = pair
        if pending_only is not None:
            payload["pending_only"] = pending_only

        headers = self._headers(signed=True)
        headers["MSG-SIGNATURE"] = self._sign(payload)

        response = self.session.post(url, data=payload, headers=headers, timeout=self.timeout)
        return self._handle_response(response)

    def cancel_order(
        self,
        order_id: Optional[int] = None,
        pair: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/v3/cancel_order"

        payload: Dict[str, Any] = {"timestamp": self._timestamp_ms()}
        if order_id is not None:
            payload["order_id"] = order_id
        if pair is not None:
            payload["pair"] = pair

        headers = self._headers(signed=True)
        headers["MSG-SIGNATURE"] = self._sign(payload)

        response = self.session.post(url, data=payload, headers=headers, timeout=self.timeout)
        return self._handle_response(response)
