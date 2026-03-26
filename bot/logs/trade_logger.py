# bot/logs/trade_logger.py

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TRADE_LOG_FIELDS = [
    "timestamp",
    "symbol",
    "pair",
    "side",
    "price",
    "quantity",
    "order_id",
    "api_response",
    "pnl",
    "signal_reason",
    "strategy_state",
]


class TradeLogger:
    def __init__(self, file_path: str = "bot/logs/trades.csv") -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.fieldnames = TRADE_LOG_FIELDS

        if not self.file_path.exists() or self.file_path.stat().st_size == 0:
            self._write_header()

    def _write_header(self) -> None:
        with open(self.file_path, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            writer.writeheader()

    @staticmethod
    def _to_json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )

    @staticmethod
    def _resolve_pair(pair: str | None, strategy_state: dict[str, Any] | None) -> str:
        if pair:
            return pair
        if isinstance(strategy_state, dict):
            return str(strategy_state.get("pair", ""))
        return ""

    def log_trade(
        self,
        *,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        order_id: str,
        api_response: Any,
        pnl: float | None = None,
        signal_reason: str | None = None,
        strategy_state: dict[str, Any] | None = None,
        pair: str | None = None,
    ) -> None:
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "pair": self._resolve_pair(pair, strategy_state),
            "side": side,
            "price": price,
            "quantity": quantity,
            "order_id": str(order_id),
            "api_response": self._to_json(api_response),
            "pnl": pnl if pnl is not None else "",
            "signal_reason": signal_reason or "",
            "strategy_state": self._to_json(strategy_state) if strategy_state else "",
        }

        with open(self.file_path, "a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            writer.writerow(row)
