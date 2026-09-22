"""Shared data types passed between layers (data -> safety -> strategy -> risk -> execution)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Verdict(str, Enum):
    SAFE = "SAFE"
    WARN = "WARN"
    DANGER = "DANGER"


@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class TokenMarket:
    """Snapshot of a token/pair from DexScreener."""

    chain: str
    pair_address: str
    token_address: str
    symbol: str
    name: str
    price_usd: float
    liquidity_usd: float
    volume_24h_usd: float
    price_change_24h_pct: float
    txns_24h_buys: int
    txns_24h_sells: int
    pair_created_at: datetime | None
    fdv_usd: float | None = None
    twitter_handle: str | None = None
    website: str | None = None

    @property
    def age_minutes(self) -> float | None:
        if not self.pair_created_at:
            return None
        return (datetime.utcnow() - self.pair_created_at).total_seconds() / 60.0


@dataclass
class OnchainReport:
    """Normalized safety facts about a token, merged from RugCheck + GoPlus."""

    token_address: str
    mint_authority_renounced: bool | None
    freeze_authority_renounced: bool | None
    lp_locked_or_burned: bool | None
    lp_locked_pct: float | None
    top10_holder_pct: float | None
    single_largest_holder_pct: float | None
    holder_count: int | None
    buy_tax_pct: float | None
    sell_tax_pct: float | None
    is_honeypot: bool | None
    rugcheck_risk_score: float | None
    goplus_confidence: float | None
    raw_sources: dict = field(default_factory=dict)


@dataclass
class SafetyResult:
    verdict: Verdict
    reasons: list[str]
    report: OnchainReport | None


@dataclass
class SocialMention:
    author_id: str
    author_handle: str
    author_created_at: datetime | None
    author_followers: int
    text: str
    created_at: datetime
    like_count: int = 0
    retweet_count: int = 0


@dataclass
class SocialReport:
    token_address: str
    mentions: list[SocialMention]
    unique_authors: int
    new_account_ratio: float
    negative_sentiment_ratio: float
    fetched_at: datetime


@dataclass
class SocialResult:
    verdict: Verdict
    reasons: list[str]
    report: SocialReport | None


@dataclass
class Signal:
    should_enter: bool
    reasons: list[str]
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    atr: float | None = None


@dataclass
class Position:
    token_address: str
    symbol: str
    entry_price: float
    size_sol: float
    size_tokens: float
    stop_loss: float
    take_profit: float
    risk_unit: float  # entry_price - initial stop_loss, fixed at open; trailing stop is anchored to this
    opened_at: datetime
    max_hold_until: datetime
    high_water_mark: float
    trailing_active: bool = False
    status: str = "open"  # open | closed
    close_price: float | None = None
    closed_at: datetime | None = None
    close_reason: str | None = None

    @property
    def pnl_pct(self) -> float | None:
        if self.close_price is None:
            return None
        return (self.close_price - self.entry_price) / self.entry_price

    @property
    def pnl_sol(self) -> float | None:
        pnl_pct = self.pnl_pct
        if pnl_pct is None:
            return None
        return self.size_sol * pnl_pct
