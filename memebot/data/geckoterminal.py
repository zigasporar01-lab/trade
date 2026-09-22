"""GeckoTerminal public OHLCV API client. No API key required.

Docs: https://apiguide.geckoterminal.com/
Rate limit: 30 requests/minute. We use this for 4h candles since DexScreener's
free API only exposes current snapshots, not historical OHLCV.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from memebot.models import Candle

log = structlog.get_logger(__name__)

BASE_URL = "https://api.geckoterminal.com/api/v2"


class GeckoTerminalClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=10.0)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = self._client.get(path, params=params, headers={"Accept": "application/json;version=20230302"})
        resp.raise_for_status()
        return resp.json()

    def get_ohlcv(
        self,
        network: str,
        pool_address: str,
        aggregate_hours: int = 4,
        limit: int = 60,
    ) -> list[Candle]:
        """Fetch aggregated hourly candles (e.g. aggregate=4 -> 4h candles)."""
        data = self._get(
            f"/networks/{network}/pools/{pool_address}/ohlcv/hour",
            params={"aggregate": aggregate_hours, "limit": limit, "currency": "usd"},
        )
        rows = (data.get("data", {}).get("attributes", {}) or {}).get("ohlcv_list", [])
        candles = [
            Candle(
                timestamp=datetime.fromtimestamp(row[0], tz=timezone.utc).replace(tzinfo=None),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in rows
        ]
        candles.sort(key=lambda c: c.timestamp)
        return candles

    def close(self) -> None:
        self._client.close()
