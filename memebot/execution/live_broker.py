"""Real on-chain execution via Jupiter. This spends real SOL.

Safety gates, in addition to everything in the risk/safety layers:
  1. Requires MODE=live in the environment (config.yaml alone can't enable it).
  2. Requires CONFIRM_LIVE_TRADING=YES_I_UNDERSTAND_THE_RISK in the environment
     — a second, explicit opt-in so a stray "mode: live" in a shared config
     file can never move real money on its own.
  3. Requires a dedicated wallet private key (never reuse a main wallet).
  4. Refuses any single order above `max_position_size_pct` of configured capital,
     re-checked here independently of the position sizer upstream.
"""

from __future__ import annotations

import base64

import httpx
import structlog
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from memebot.config import Settings
from memebot.execution.broker import FillResult
from memebot.execution.jupiter_client import SOL_MINT, JupiterClient, implied_price

log = structlog.get_logger(__name__)

LAMPORTS_PER_SOL = 1_000_000_000
REQUIRED_CONFIRMATION_VALUE = "YES_I_UNDERSTAND_THE_RISK"


class LiveTradingNotConfirmedError(RuntimeError):
    pass


class LiveBroker:
    def __init__(self, settings: Settings, jupiter: JupiterClient) -> None:
        import os

        if settings.trading.mode.strip().lower() != "live":
            raise LiveTradingNotConfirmedError("MODE is not 'live' — refusing to construct LiveBroker.")
        if os.getenv("CONFIRM_LIVE_TRADING") != REQUIRED_CONFIRMATION_VALUE:
            raise LiveTradingNotConfirmedError(
                "Set CONFIRM_LIVE_TRADING=YES_I_UNDERSTAND_THE_RISK in your environment "
                "to enable live trading. This is a deliberate second opt-in."
            )
        if not settings.solana_wallet_private_key:
            raise LiveTradingNotConfirmedError("SOLANA_WALLET_PRIVATE_KEY is not set.")

        self._settings = settings
        self._jupiter = jupiter
        self._keypair = Keypair.from_base58_string(settings.solana_wallet_private_key)
        self._rpc = httpx.Client(base_url=settings.solana_rpc_url, timeout=15.0)
        self._max_size_sol = settings.trading.capital_sol * settings.trading.max_position_size_pct
        log.warning("live_broker.initialized", public_key=str(self._keypair.pubkey()))

    def buy(self, token_address: str, size_sol: float, slippage_bps: int) -> FillResult:
        if size_sol > self._max_size_sol:
            msg = f"Order size {size_sol} SOL exceeds hard cap {self._max_size_sol} SOL for this wallet."
            log.error("live_broker.order_rejected", reason=msg)
            return FillResult(success=False, filled_price=None, filled_size=None, tx_signature=None, error=msg)

        amount_lamports = int(size_sol * LAMPORTS_PER_SOL)
        return self._execute_swap(SOL_MINT, token_address, amount_lamports, slippage_bps)

    def sell(self, token_address: str, size_tokens: float, slippage_bps: int) -> FillResult:
        return self._execute_swap(token_address, SOL_MINT, int(size_tokens), slippage_bps)

    def _execute_swap(self, input_mint: str, output_mint: str, amount: int, slippage_bps: int) -> FillResult:
        try:
            quote = self._jupiter.get_quote(input_mint, output_mint, amount, slippage_bps)
            swap = self._jupiter.get_swap_transaction(quote, str(self._keypair.pubkey()))
            raw_tx = base64.b64decode(swap["swapTransaction"])
            tx = VersionedTransaction.from_bytes(raw_tx)
            signed_tx = VersionedTransaction(tx.message, [self._keypair])

            resp = self._rpc.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [
                        base64.b64encode(bytes(signed_tx)).decode("utf-8"),
                        {"encoding": "base64", "skipPreflight": False, "maxRetries": 3},
                    ],
                },
            )
            resp.raise_for_status()
            body = resp.json()
            if "error" in body:
                raise RuntimeError(body["error"])

            signature = body["result"]
            price = implied_price(quote)
            log.warning("live_broker.swap_sent", signature=signature, price=price)
            return FillResult(
                success=True,
                filled_price=price,
                filled_size=float(quote.get("outAmount", 0)),
                tx_signature=signature,
            )
        except Exception as exc:  # noqa: BLE001 - any failure here must not crash the bot loop
            log.error("live_broker.swap_failed", error=str(exc))
            return FillResult(success=False, filled_price=None, filled_size=None, tx_signature=None, error=str(exc))

    def close(self) -> None:
        self._rpc.close()
