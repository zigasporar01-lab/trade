"""X (Twitter) API v2 client for social due-diligence.

X moved to pure pay-per-use pricing in Feb 2026 with no free tier
(~$0.005/post read, $0.010/user profile read). This client is built to
minimize spend:
  - in-memory TTL cache (memebot.social.cache_ttl_minutes)
  - hard cap on reads per token scan (memebot.social.max_reads_per_token_scan)
  - a single search call fetches both tweet text AND author expansions,
    avoiding a second per-author profile lookup.

Docs: https://docs.x.com/x-api/introduction (recent search: GET /2/tweets/search/recent)
"""

from __future__ import annotations

import time
from datetime import datetime

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from memebot.models import SocialMention

log = structlog.get_logger(__name__)

BASE_URL = "https://api.twitter.com"


class TwitterClient:
    def __init__(
        self,
        bearer_token: str | None,
        client: httpx.Client | None = None,
        cache_ttl_seconds: int = 1200,
    ) -> None:
        self._bearer_token = bearer_token
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=10.0)
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[float, list[SocialMention]]] = {}

    @property
    def configured(self) -> bool:
        return bool(self._bearer_token)

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
    def _search_recent(self, query: str, max_results: int) -> dict:
        headers = {"Authorization": f"Bearer {self._bearer_token}"}
        params = {
            "query": query,
            "max_results": max(10, min(max_results, 100)),
            "tweet.fields": "created_at,public_metrics,author_id",
            "expansions": "author_id",
            "user.fields": "created_at,public_metrics,username",
        }
        resp = self._client.get("/2/tweets/search/recent", headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()

    def search_token_mentions(
        self,
        symbol: str,
        token_address: str,
        max_reads: int = 25,
    ) -> list[SocialMention]:
        """Search recent mentions of a token by cashtag/symbol OR raw contract
        address (scammers can't fake mentions of the real contract address the
        way they can spam a cashtag), capped at max_reads to control spend.
        """
        if not self.configured:
            return []

        cache_key = f"{symbol}:{token_address}"
        cached = self._cache.get(cache_key)
        if cached and (time.time() - cached[0]) < self._cache_ttl:
            return cached[1]

        query = f'("${symbol}" OR "{token_address}") -is:retweet lang:en'
        data = self._search_recent(query, max_results=max_reads)

        users_by_id = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
        mentions: list[SocialMention] = []
        for tweet in data.get("data", []):
            author = users_by_id.get(tweet.get("author_id"), {})
            created_at = None
            if author.get("created_at"):
                created_at = datetime.strptime(author["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
            tweet_created_at = datetime.strptime(tweet["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
            metrics = tweet.get("public_metrics", {}) or {}
            mentions.append(
                SocialMention(
                    author_id=tweet.get("author_id", ""),
                    author_handle=author.get("username", "unknown"),
                    author_created_at=created_at,
                    author_followers=(author.get("public_metrics", {}) or {}).get("followers_count", 0),
                    text=tweet.get("text", ""),
                    created_at=tweet_created_at,
                    like_count=metrics.get("like_count", 0),
                    retweet_count=metrics.get("retweet_count", 0),
                )
            )

        self._cache[cache_key] = (time.time(), mentions)
        return mentions

    def close(self) -> None:
        self._client.close()
