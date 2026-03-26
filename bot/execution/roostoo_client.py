# bot/execution/roostoo_client.py

import hashlib
import hmac
import os
import time
from typing import Any, Optional, Union

import requests


DEFAULT_BASE_URL = "https://mock-api.roostoo.com"
DEFAULT_TIMEOUT = 10
DEFAULT_BALANCE_CACHE_TTL = 1.0

API_KEY_HEADER = "RST-API-KEY"
SIGNATURE_HEADER = "MSG-SIGNATURE"
FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"


class RoostooClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        balance_cache_ttl: float = DEFAULT_BALANCE_CACHE_TTL,
    ) -> None:
        self.api_key = api_key or os.getenv("ROOSTOO_API_KEY", "")
        self.api_secret = api_secret or os.getenv("ROOSTOO_API_SECRET", "")
        self.base_url = (base_url or os.getenv("ROOSTOO_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.timeout = timeout
        self.balance_cache_ttl = balance_cache_ttl
        self.session = requests.Session()

        self._last_balance_snapshot: Optional[dict[str, Any]] = None
        self._last_balance_ts = 0.0

        if not self.api_key:
            raise ValueError("Missing ROOSTOO_API_KEY")
        if not self.api_secret:
            raise ValueError("Missing ROOSTOO_API_SECRET")

    @staticmethod
    def _timestamp_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _build_query_string(params: dict[str, Any]) -> str:
        return "&".join(f"{key}={params[key]}" for key in sorted(params))

    def _sign(self, params: dict[str, Any]) -> str:
        query_string = self._build_query_string(params)
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _headers(self, signed: bool = False) -> dict[str, str]:
        if not signed:
            return {}

        return {
            API_KEY_HEADER: self.api_key,
            "Content-Type": FORM_CONTENT_TYPE,
        }

    def _handle_response(
        self,
        response: requests.Response,
        allow_false_success: bool = False,
    ) -> dict[str, Any]:
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Non-JSON response from Roostoo: {response.text}") from exc

        if isinstance(data, dict) and data.get("Success") is False and not allow_false_success:
            raise RuntimeError(data.get("ErrMsg", "Unknown Roostoo API error"))

        return data

    def _invalidate_balance_cache(self) -> None:
        self._last_balance_snapshot = None
        self._last_balance_ts = 0.0

    def _signed_get(
        self,
        path: str,
        params: dict[str, Any],
        allow_false_success: bool = False,
    ) -> dict[str, Any]:
        signed_params = {key: params[key] for key in sorted(params)}
        headers = self._headers(signed=True)
        headers[SIGNATURE_HEADER] = self._sign(signed_params)

        response = self.session.get(
            f"{self.base_url}{path}",
            params=signed_params,
            headers=headers,
            timeout=self.timeout,
        )
        return self._handle_response(response, allow_false_success=allow_false_success)

    def _signed_post(
        self,
        path: str,
        payload: dict[str, Any],
        allow_false_success: bool = False,
    ) -> dict[str, Any]:
        signed_payload = {key: payload[key] for key in sorted(payload)}
        headers = self._headers(signed=True)
        headers[SIGNATURE_HEADER] = self._sign(signed_payload)

        response = self.session.post(
            f"{self.base_url}{path}",
            data=self._build_query_string(signed_payload),
            headers=headers,
            timeout=self.timeout,
        )
        return self._handle_response(response, allow_false_success=allow_false_success)

    @staticmethod
    def extract_free_balance(balance: dict[str, Any], asset: str) -> float:
        if not isinstance(balance, dict):
            return 0.0

        asset = asset.upper()

        for wallet_name in ("SpotWallet", "MarginWallet"):
            wallet = balance.get(wallet_name, {})
            if not isinstance(wallet, dict):
                continue

            asset_info = wallet.get(asset)
            if isinstance(asset_info, dict):
                return RoostooClient._to_float(asset_info.get("Free"))

            for coin, coin_info in wallet.items():
                if str(coin).upper() == asset and isinstance(coin_info, dict):
                    return RoostooClient._to_float(coin_info.get("Free"))

        return 0.0

    def get_server_time(self) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}/v3/serverTime",
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def get_exchange_info(self) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}/v3/exchangeInfo",
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def get_ticker(self, pair: Optional[str] = None) -> dict[str, Any]:
        params: dict[str, Any] = {"timestamp": self._timestamp_ms()}
        if pair:
            params["pair"] = pair

        response = self.session.get(
            f"{self.base_url}/v3/ticker",
            params=params,
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def get_balance(self, force_refresh: bool = False) -> dict[str, Any]:
        now = time.time()

        if (
            not force_refresh
            and self._last_balance_snapshot is not None
            and (now - self._last_balance_ts) <= self.balance_cache_ttl
        ):
            return self._last_balance_snapshot

        balance = self._signed_get(
            "/v3/balance",
            {"timestamp": self._timestamp_ms()},
        )

        self._last_balance_snapshot = balance
        self._last_balance_ts = now
        return balance

    def get_free_balance(
        self,
        asset: str,
        balance_snapshot: Optional[dict[str, Any]] = None,
        force_refresh: bool = False,
    ) -> float:
        balance = balance_snapshot or self.get_balance(force_refresh=force_refresh)
        return self.extract_free_balance(balance, asset)

    def pending_count(self) -> dict[str, Any]:
        return self._signed_get(
            "/v3/pending_count",
            {"timestamp": self._timestamp_ms()},
            allow_false_success=True,
        )

    def place_order(
        self,
        pair: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
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

        result = self._signed_post("/v3/place_order", payload)
        self._invalidate_balance_cache()
        return result

    def query_order(
        self,
        order_id: Optional[Union[int, str]] = None,
        pair: Optional[str] = None,
        pending_only: Optional[bool] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        if order_id is not None and any(value is not None for value in (pair, pending_only, offset, limit)):
            raise ValueError("When order_id is sent, do not send pair/pending_only/offset/limit")

        payload: dict[str, Any] = {"timestamp": self._timestamp_ms()}

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
    ) -> dict[str, Any]:
        if order_id is not None and pair is not None:
            raise ValueError("Send only one of order_id or pair")
        if order_id is None and pair is None:
            raise ValueError("Send either order_id or pair")

        payload: dict[str, Any] = {"timestamp": self._timestamp_ms()}

        if order_id is not None:
            payload["order_id"] = str(order_id)
        else:
            payload["pair"] = pair

        result = self._signed_post("/v3/cancel_order", payload)
        self._invalidate_balance_cache()
        return result

    def close(self) -> None:
        self.session.close()
