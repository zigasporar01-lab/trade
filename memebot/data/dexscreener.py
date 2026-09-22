"""DexScreener public REST API client. No API key required.

Docs: https://docs.dexscreener.com/api/reference
Rate limit: 300 requests/minute for pair/token/search endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from memebot.models import TokenMarket

log = structlog.get_logger(__name__)

BASE_URL = "https://api.dexscreener.com"


class DexScreenerClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=10.0)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    def get_token_pairs(self, chain_id: str, token_address: str) -> list[TokenMarket]:
        """Return all trading pairs for a token address, sorted by liquidity desc."""
        data = self._get(f"/tokens/v1/{chain_id}/{token_address}")
        pairs = data if isinstance(data, list) else data.get("pairs") or []
        markets = [_pair_to_market(p) for p in pairs if p]
        markets.sort(key=lambda m: m.liquidity_usd, reverse=True)
        return markets

    def search_pairs(self, query: str) -> list[TokenMarket]:
        """Free-text search, e.g. by symbol or contract address."""
        data = self._get("/latest/dex/search", params={"q": query})
        pairs = data.get("pairs") or []
        return [_pair_to_market(p) for p in pairs if p]

    def get_new_pairs(self, chain_id: str, query_terms: list[str]) -> list[TokenMarket]:
        """Best-effort discovery: DexScreener has no dedicated 'new pairs' feed on the
        free API, so we search a rotating set of terms (e.g. trending queries the
        caller supplies) and rely on the age/liquidity filters downstream to do the
        real filtering. For production-grade discovery, pair this with a paid
        on-chain new-pool listener (Helius webhooks / pump.fun program logs).
        """
        seen: dict[str, TokenMarket] = {}
        for term in query_terms:
            for market in self.search_pairs(term):
                if market.chain == chain_id:
                    seen[market.pair_address] = market
        return list(seen.values())

    def close(self) -> None:
        self._client.close()


def _pair_to_market(p: dict) -> TokenMarket:
    base = p.get("baseToken", {})
    liquidity = p.get("liquidity", {}) or {}
    txns = (p.get("txns", {}) or {}).get("h24", {}) or {}
    info = p.get("info", {}) or {}
    socials = {s.get("type"): s.get("url") for s in info.get("socials", []) if isinstance(s, dict)}

    created_at = None
    if p.get("pairCreatedAt"):
        created_at = datetime.fromtimestamp(p["pairCreatedAt"] / 1000, tz=timezone.utc).replace(tzinfo=None)

    return TokenMarket(
        chain=p.get("chainId", ""),
        pair_address=p.get("pairAddress", ""),
        token_address=base.get("address", ""),
        symbol=base.get("symbol", ""),
        name=base.get("name", ""),
        price_usd=float(p.get("priceUsd") or 0.0),
        liquidity_usd=float(liquidity.get("usd") or 0.0),
        volume_24h_usd=float((p.get("volume", {}) or {}).get("h24") or 0.0),
        price_change_24h_pct=float((p.get("priceChange", {}) or {}).get("h24") or 0.0),
        txns_24h_buys=int(txns.get("buys") or 0),
        txns_24h_sells=int(txns.get("sells") or 0),
        pair_created_at=created_at,
        fdv_usd=float(p["fdv"]) if p.get("fdv") else None,
        twitter_handle=socials.get("twitter"),
        website=info.get("websites", [{}])[0].get("url") if info.get("websites") else None,
    )
