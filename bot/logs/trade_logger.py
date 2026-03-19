from __future__ import annotations

import csv
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional


class TradeLogger:
    def __init__(self, file_path: str = "logs/trades.csv") -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        self.fieldnames = [
            "timestamp",
            "symbol",
            "side",
            "price",
            "quantity",
            "order_id",
            "api_response",
            "pnl",
            "signal_reason",
            "strategy_state",
        ]

        if not self.file_path.exists():
            with open(self.file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames)
                writer.writeheader()

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
    ) -> None:
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "side": side,
            "price": price,
            "quantity": quantity,
            "order_id": order_id,
            "api_response": json.dumps(api_response, ensure_ascii=False),
            "pnl": pnl if pnl is not None else "",
            "signal_reason": signal_reason or "",
            "strategy_state": json.dumps(strategy_state, ensure_ascii=False) if strategy_state else "",
        }

        with open(self.file_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            writer.writerow(row)
