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
        before_timestamp: int | None = None,
    ) -> list[Candle]:
        """Fetch aggregated hourly candles (e.g. aggregate=4 -> 4h candles).

        before_timestamp (unix seconds) pages backward in time for deeper
        history — max 1000 candles per call, per GeckoTerminal's API limits.
        """
        params = {"aggregate": aggregate_hours, "limit": limit, "currency": "usd"}
        if before_timestamp is not None:
            params["before_timestamp"] = before_timestamp
        data = self._get(f"/networks/{network}/pools/{pool_address}/ohlcv/hour", params=params)
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

    def get_ohlcv_history(
        self,
        network: str,
        pool_address: str,
        aggregate_hours: int = 4,
        total_candles: int = 500,
        page_size: int = 500,
    ) -> list[Candle]:
        """Paginate backward via before_timestamp to build a longer history
        than a single call returns. Stops early if the pool has no more
        history (GeckoTerminal returns an empty/shorter page).
        """
        collected: list[Candle] = []
        before_timestamp: int | None = None

        while len(collected) < total_candles:
            remaining = total_candles - len(collected)
            page = self.get_ohlcv(
                network=network,
                pool_address=pool_address,
                aggregate_hours=aggregate_hours,
                limit=min(page_size, remaining),
                before_timestamp=before_timestamp,
            )
            if not page:
                break
            collected = page + collected
            before_timestamp = int(page[0].timestamp.replace(tzinfo=timezone.utc).timestamp())
            if len(page) < min(page_size, remaining):
                break  # pool's history is shorter than requested

        return collected

    def close(self) -> None:
        self._client.close()
