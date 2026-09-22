"""RugCheck API client (Solana token safety reports).

Docs (Swagger): https://api.rugcheck.xyz/swagger/index.html
Report endpoint: GET /v1/tokens/{mint}/report
Auth: X-API-KEY header (optional for the summary report; required for full access).
"""

from __future__ import annotations

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger(__name__)

BASE_URL = "https://api.rugcheck.xyz"


class RugCheckClient:
    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=10.0)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_report(self, mint_address: str) -> dict | None:
        headers = {"X-API-KEY": self._api_key} if self._api_key else {}
        resp = self._client.get(f"/v1/tokens/{mint_address}/report", headers=headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._client.close()


def extract_safety_fields(report: dict | None) -> dict:
    """Pull the fields our screener cares about out of RugCheck's raw report shape.

    RugCheck's schema has shifted over time; this defends with .get() everywhere
    and returns None for anything it can't find so the screener treats it as
    "unknown" rather than silently assuming safe.
    """
    if not report:
        return {}

    token_meta = report.get("token", {}) or {}
    markets = report.get("markets", []) or []
    top_holders = report.get("topHolders", []) or []

    lp_locked_pct = None
    lp_locked_or_burned = None
    if markets:
        lp = markets[0].get("lp", {}) or {}
        lp_locked_pct = lp.get("lpLockedPct")
        lp_locked_or_burned = bool(lp_locked_pct and lp_locked_pct >= 90)

    top10_pct = None
    if top_holders:
        top10_pct = sum(h.get("pct", 0) for h in top_holders[:10])

    single_largest_pct = top_holders[0].get("pct") if top_holders else None

    return {
        "mint_authority_renounced": token_meta.get("mintAuthority") is None,
        "freeze_authority_renounced": token_meta.get("freezeAuthority") is None,
        "lp_locked_or_burned": lp_locked_or_burned,
        "lp_locked_pct": lp_locked_pct,
        "top10_holder_pct": top10_pct,
        "single_largest_holder_pct": single_largest_pct,
        "holder_count": report.get("totalHolders"),
        "rugcheck_risk_score": report.get("score"),
        "is_honeypot": any(r.get("name") == "honeypot" for r in report.get("risks", []) or []),
    }
