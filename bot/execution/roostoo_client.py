import os
import time
import hmac
import hashlib
from typing import Any, Dict, Optional, Union

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

        if not self.api_key:
            raise ValueError("Missing ROOSTOO_API_KEY")
        if not self.api_secret:
            raise ValueError("Missing ROOSTOO_API_SECRET")

    @staticmethod
    def _timestamp_ms() -> int:
        return int(time.time() * 1000)

    def _build_query_string(self, params: Dict[str, Any]) -> str:
        return "&".join(f"{k}={str(params[k])}" for k in sorted(params.keys()))

    def _sign(self, params: Dict[str, Any]) -> str:
        query_string = self._build_query_string(params)
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _headers(self, signed: bool = False) -> Dict[str, str]:
        headers: Dict[str, str] = {}
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

        try:
            data = response.json()
        except ValueError:
            raise RuntimeError(f"Non-JSON response from Roostoo: {response.text}")

        if (
            isinstance(data, dict)
            and data.get("Success") is False
            and not allow_false_success
        ):
            err = data.get("ErrMsg", "Unknown Roostoo API error")
            raise RuntimeError(err)

        return data

    def _signed_get(
        self,
        path: str,
        params: Dict[str, Any],
        allow_false_success: bool = False,
    ) -> Dict[str, Any]:
        sorted_params = {k: params[k] for k in sorted(params.keys())}
        headers = self._headers(signed=True)
        headers["MSG-SIGNATURE"] = self._sign(sorted_params)

        response = self.session.get(
            f"{self.base_url}{path}",
            params=sorted_params,
            headers=headers,
            timeout=self.timeout,
        )
        return self._handle_response(response, allow_false_success=allow_false_success)

    def _signed_post(
        self,
        path: str,
        payload: Dict[str, Any],
        allow_false_success: bool = False,
    ) -> Dict[str, Any]:
        sorted_payload = {k: payload[k] for k in sorted(payload.keys())}
        headers = self._headers(signed=True)
        headers["MSG-SIGNATURE"] = self._sign(sorted_payload)

        body = self._build_query_string(sorted_payload)

        response = self.session.post(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            timeout=self.timeout,
        )
        return self._handle_response(response, allow_false_success=allow_false_success)

    def get_server_time(self) -> Dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}/v3/serverTime",
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def get_exchange_info(self) -> Dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}/v3/exchangeInfo",
            timeout=self.timeout,
        )
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

    def get_free_balance(self, coin: str) -> float:
        data = self.get_balance()
        wallet = data.get("Wallet", {})
        coin_info = wallet.get(coin, {})
        return float(coin_info.get("Free", 0))

    def pending_count(self) -> Dict[str, Any]:
        params = {"timestamp": self._timestamp_ms()}
        return self._signed_get(
            "/v3/pending_count",
            params,
            allow_false_success=True,
        )

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
        order_id: Optional[Union[int, str]] = None,
        pair: Optional[str] = None,
        pending_only: Optional[bool] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        if order_id is not None and any(
            x is not None for x in [pair, pending_only, offset, limit]
        ):
            raise ValueError(
                "When order_id is sent, do not send pair/pending_only/offset/limit"
            )

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
        order_id: Optional[Union[int, str]] = None,
        pair: Optional[str] = None,
    ) -> Dict[str, Any]:
        if order_id is not None and pair is not None:
            raise ValueError("Send only one of order_id or pair")

        payload: Dict[str, Any] = {"timestamp": self._timestamp_ms()}

        if order_id is not None:
            payload["order_id"] = str(order_id)
        elif pair is not None:
            payload["pair"] = pair
        else:
            raise ValueError("Send either order_id or pair")

        return self._signed_post("/v3/cancel_order", payload)
