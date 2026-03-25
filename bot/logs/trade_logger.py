from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class TradeLogger:
    def __init__(self, file_path: str = "bot/logs/trades.csv") -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        self.fieldnames = [
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

        needs_header = (
            (not self.file_path.exists())
            or self.file_path.stat().st_size == 0
        )

        if needs_header:
            with open(self.file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames)
                writer.writeheader()

    @staticmethod
    def _to_json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )

    def log_trade(
        self,
        *,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        order_id: str,
        api_response: Any,
        pnl: Optional[float] = None,
        signal_reason: Optional[str] = None,
        strategy_state: Optional[dict[str, Any]] = None,
        pair: Optional[str] = None,
    ) -> None:
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "pair": pair or (
                str(strategy_state.get("pair", ""))
                if isinstance(strategy_state, dict)
                else ""
            ),
            "side": side,
            "price": price,
            "quantity": quantity,
            "order_id": str(order_id),
            "api_response": self._to_json(api_response),
            "pnl": pnl if pnl is not None else "",
            "signal_reason": signal_reason or "",
            "strategy_state": (
                self._to_json(strategy_state) if strategy_state else ""
            ),
        }

        with open(self.file_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            writer.writerow(row)
