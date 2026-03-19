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
        self.base_url = (
            base_url or os.getenv("ROOSTOO_BASE_URL", "https://mock-api.roostoo.com")
        ).rstrip("/")
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

    def _handle_response(
        self,
        response: requests.Response,
        allow_false_success: bool = False,
    ) -> Dict[str, Any]:
        response.raise_for_status()
        data = response.json()

        if (
            isinstance(data, dict)
            and data.get("Success") is False
            and not allow_false_success
        ):
            err = data.get("ErrMsg", "Unknown Roostoo API error")
            raise RuntimeError(err)

        return data

    def _signed_get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        headers = self._headers(signed=True)
        headers["MSG-SIGNATURE"] = self._sign(params)

        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            headers=headers,
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def _signed_post(
        self,
        path: str,
        payload: Dict[str, Any],
        allow_false_success: bool = False,
    ) -> Dict[str, Any]:
        headers = self._headers(signed=True)
        headers["MSG-SIGNATURE"] = self._sign(payload)

        # send the exact sorted form string that was signed
        body = self._build_query_string(payload)

        response = self.session.post(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            timeout=self.timeout,
        )
        return self._handle_response(response, allow_false_success=allow_false_success)

    def get_server_time(self) -> Dict[str, Any]:
        response = self.session.get(f"{self.base_url}/v3/serverTime", timeout=self.timeout)
        return self._handle_response(response)

    def get_exchange_info(self) -> Dict[str, Any]:
        response = self.session.get(f"{self.base_url}/v3/exchangeInfo", timeout=self.timeout)
        return self._handle_response(response)

    def get_ticker(self, pair: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"timestamp": self._timestamp_ms()}
        if pair:
            params["pair"] = pair

        response = self.session.get(
            f"{self.base_url}/v3/ticker",
            params=params,
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def get_balance(self) -> Dict[str, Any]:
        params = {"timestamp": self._timestamp_ms()}
        return self._signed_get("/v3/balance", params)

    def pending_count(self) -> Dict[str, Any]:
        params = {"timestamp": self._timestamp_ms()}
        headers = self._headers(signed=True)
        headers["MSG-SIGNATURE"] = self._sign(params)

        response = self.session.get(
            f"{self.base_url}/v3/pending_count",
            params=params,
            headers=headers,
            timeout=self.timeout,
        )
        # allow Success=false when there are simply no pending orders
        return self._handle_response(response, allow_false_success=True)

    def place_order(
        self,
        pair: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "pair": pair,
            "quantity": str(quantity),
            "side": side.upper(),
            "timestamp": self._timestamp_ms(),
            "type": order_type.upper(),
        }

        if payload["type"] == "LIMIT":
            if price is None:
                raise ValueError("LIMIT order requires price")
            payload["price"] = str(price)

        return self._signed_post("/v3/place_order", payload)

    def query_order(
        self,
        order_id: Optional[int] = None,
        pair: Optional[str] = None,
        pending_only: Optional[bool] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        if order_id is not None and any(
            x is not None for x in [pair, pending_only, offset, limit]
        ):
            raise ValueError("When order_id is sent, do not send pair/pending_only/offset/limit")

        payload: Dict[str, Any] = {"timestamp": self._timestamp_ms()}

        if order_id is not None:
            payload["order_id"] = str(order_id)
        else:
            if pair is not None:
                payload["pair"] = pair
            if pending_only is not None:
                payload["pending_only"] = "TRUE" if pending_only else "FALSE"
            if offset is not None:
                payload["offset"] = str(offset)
            if limit is not None:
                payload["limit"] = str(limit)

        return self._signed_post(
            "/v3/query_order",
            payload,
            allow_false_success=True,
        )

    def cancel_order(
        self,
        order_id: Optional[int] = None,
        pair: Optional[str] = None,
    ) -> Dict[str, Any]:
        if order_id is not None and pair is not None:
            raise ValueError("Send only one of order_id or pair")

        payload: Dict[str, Any] = {"timestamp": self._timestamp_ms()}
        if order_id is not None:
            payload["order_id"] = str(order_id)
        elif pair is not None:
            payload["pair"] = pair

        return self._signed_post("/v3/cancel_order", payload)
