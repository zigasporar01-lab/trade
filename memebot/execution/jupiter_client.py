"""Jupiter Swap API client (Solana DEX aggregator).

Docs: https://dev.jup.ag/docs/api/swap-api/quote
Keyless free tier: https://lite-api.jup.ag/swap/v1 (low rate limits, fine for
paper trading / a small live bot). Paid tier at https://api.jup.ag/swap/v1
with an X-API-Key header for higher volume.

Used in BOTH modes: paper mode uses get_quote() for realistic simulated fill
prices (including real slippage/route impact), live mode also uses
get_swap_transaction() to build the actual on-chain transaction.
"""

from __future__ import annotations

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger(__name__)

SOL_MINT = "So11111111111111111111111111111111111111112"


class JupiterClient:
    def __init__(self, base_url: str, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=10.0)

    def _headers(self) -> dict:
        return {"X-API-Key": self._api_key} if self._api_key else {}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=6))
    def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount_lamports: int,
        slippage_bps: int = 150,
    ) -> dict:
        """amount_lamports is in the input token's base units (for SOL, 1e9 lamports/SOL)."""
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": amount_lamports,
            "slippageBps": slippage_bps,
            "restrictIntermediateTokens": "true",
        }
        resp = self._client.get(f"{self._base_url}/swap/v1/quote", params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=6))
    def get_swap_transaction(self, quote_response: dict, user_public_key: str) -> dict:
        """Returns a base64-encoded unsigned transaction the caller must sign."""
        payload = {
            "quoteResponse": quote_response,
            "userPublicKey": user_public_key,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": "auto",
        }
        resp = self._client.post(f"{self._base_url}/swap/v1/swap", json=payload, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._client.close()


def implied_price(quote_response: dict) -> float | None:
    """out_amount / in_amount, adjusted by the caller for decimals."""
    try:
        in_amount = float(quote_response["inAmount"])
        out_amount = float(quote_response["outAmount"])
        if in_amount <= 0:
            return None
        return out_amount / in_amount
    except (KeyError, ValueError, TypeError):
        return None
