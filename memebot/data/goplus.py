"""GoPlus Security Token Security API client — used as a second, independent
opinion alongside RugCheck. We only ever downgrade a verdict on disagreement,
never upgrade one based on a single source.

Docs: https://docs.gopluslabs.io/reference/api-overview
Solana endpoint: GET /api/v1/solana/token_security?contract_addresses=<mint>
"""

from __future__ import annotations

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger(__name__)

BASE_URL = "https://api.gopluslabs.io"


class GoPlusClient:
    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=10.0)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_token_security(self, mint_address: str) -> dict | None:
        headers = {"Authorization": self._api_key} if self._api_key else {}
        resp = self._client.get(
            "/api/v1/solana/token_security",
            params={"contract_addresses": mint_address},
            headers=headers,
        )
        resp.raise_for_status()
        body = resp.json()
        result = (body.get("result") or {}).get(mint_address)
        return result

    def close(self) -> None:
        self._client.close()


def extract_safety_fields(result: dict | None) -> dict:
    if not result:
        return {}

    def _pct(key: str) -> float | None:
        val = result.get(key)
        try:
            return float(val) * 100 if val is not None else None
        except (TypeError, ValueError):
            return None

    holders = result.get("holders", []) or []
    top10_pct = None
    if holders:
        try:
            top10_pct = sum(float(h.get("percent", 0)) * 100 for h in holders[:10])
        except (TypeError, ValueError):
            top10_pct = None

    return {
        "mint_authority_renounced": result.get("mintable", {}).get("status") == "0"
        if isinstance(result.get("mintable"), dict)
        else None,
        "freeze_authority_renounced": result.get("freezable", {}).get("status") == "0"
        if isinstance(result.get("freezable"), dict)
        else None,
        "buy_tax_pct": _pct("buy_tax"),
        "sell_tax_pct": _pct("sell_tax"),
        "is_honeypot": result.get("is_honeypot") == "1",
        "top10_holder_pct": top10_pct,
        "goplus_confidence": 1.0,
    }
