"""Simulated broker: uses real Jupiter quotes (real routes, real price impact,
real slippage math) but never signs or sends a transaction. No funds at risk.

This is the default and recommended mode — see README for why paper mode
should run for a meaningful sample size before ever switching to live.
"""

from __future__ import annotations

import uuid

import structlog

from memebot.execution.broker import FillResult
from memebot.execution.jupiter_client import SOL_MINT, JupiterClient, implied_price

log = structlog.get_logger(__name__)

LAMPORTS_PER_SOL = 1_000_000_000


class PaperBroker:
    def __init__(self, jupiter: JupiterClient) -> None:
        self._jupiter = jupiter

    def buy(self, token_address: str, size_sol: float, slippage_bps: int) -> FillResult:
        amount_lamports = int(size_sol * LAMPORTS_PER_SOL)
        try:
            quote = self._jupiter.get_quote(SOL_MINT, token_address, amount_lamports, slippage_bps)
        except Exception as exc:  # noqa: BLE001 - surface any HTTP/route failure as a failed fill
            log.warning("paper_broker.buy_quote_failed", token=token_address, error=str(exc))
            return FillResult(success=False, filled_price=None, filled_size=None, tx_signature=None, error=str(exc))

        price = implied_price(quote)
        out_amount = quote.get("outAmount")
        log.info("paper_broker.buy_simulated", token=token_address, size_sol=size_sol, price=price)
        return FillResult(
            success=True,
            filled_price=price,
            filled_size=float(out_amount) if out_amount else None,
            tx_signature=f"PAPER-{uuid.uuid4().hex[:16]}",
        )

    def sell(self, token_address: str, size_tokens: float, slippage_bps: int) -> FillResult:
        try:
            quote = self._jupiter.get_quote(token_address, SOL_MINT, int(size_tokens), slippage_bps)
        except Exception as exc:  # noqa: BLE001
            log.warning("paper_broker.sell_quote_failed", token=token_address, error=str(exc))
            return FillResult(success=False, filled_price=None, filled_size=None, tx_signature=None, error=str(exc))

        price = implied_price(quote)
        out_amount = quote.get("outAmount")
        log.info("paper_broker.sell_simulated", token=token_address, size_tokens=size_tokens, price=price)
        return FillResult(
            success=True,
            filled_price=price,
            filled_size=(float(out_amount) / LAMPORTS_PER_SOL) if out_amount else None,
            tx_signature=f"PAPER-{uuid.uuid4().hex[:16]}",
        )
