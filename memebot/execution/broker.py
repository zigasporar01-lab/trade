"""Broker interface both PaperBroker and LiveBroker implement, so the bot's
core loop never needs to know which mode it's running in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class FillResult:
    success: bool
    filled_price: float | None
    filled_size: float | None
    tx_signature: str | None
    error: str | None = None


class Broker(Protocol):
    def buy(self, token_address: str, size_sol: float, slippage_bps: int) -> FillResult: ...

    def sell(self, token_address: str, size_tokens: float, slippage_bps: int) -> FillResult: ...
