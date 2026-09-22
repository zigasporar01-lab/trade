"""Combines on-chain + social screens into one gate, plus the two-scan
reconfirmation rule: a candidate must come back SAFE on two separate scans,
at least `reconfirm_gap_minutes` apart, before it's eligible to trade.

This is the "don't make quick decisions" rule made concrete: even a token
that looks perfect on the first scan has to still look perfect 15+ minutes
later before we touch it. Rugs are frequently telegraphed by a rapid change
in holder distribution or a liquidity pull in the minutes after launch buzz
starts — a single point-in-time check can't see that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from memebot.config import Settings
from memebot.data.dexscreener import DexScreenerClient
from memebot.data.goplus import GoPlusClient
from memebot.data.goplus import extract_safety_fields as goplus_fields
from memebot.data.rugcheck import RugCheckClient
from memebot.data.rugcheck import extract_safety_fields as rugcheck_fields
from memebot.data.twitter import TwitterClient
from memebot.models import SafetyResult, SocialResult, Verdict
from memebot.safety.onchain import evaluate_onchain_safety, merge_reports
from memebot.safety.social import build_social_report, evaluate_social_safety


@dataclass
class ScanRecord:
    timestamp: datetime
    onchain: SafetyResult
    social: SocialResult

    @property
    def passed(self) -> bool:
        return self.onchain.verdict == Verdict.SAFE and self.social.verdict != Verdict.DANGER


@dataclass
class CandidateHistory:
    token_address: str
    scans: list[ScanRecord] = field(default_factory=list)

    def is_confirmed(self, required_scans: int, gap_minutes: int) -> bool:
        passing = [s for s in self.scans if s.passed]
        if len(passing) < required_scans:
            return False
        passing_sorted = sorted(passing, key=lambda s: s.timestamp)
        first, last = passing_sorted[0], passing_sorted[-1]
        gap = (last.timestamp - first.timestamp).total_seconds() / 60.0
        return gap >= gap_minutes


class SafetyScreener:
    """Stateful orchestrator: run one scan, remember history per token."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.dexscreener = DexScreenerClient()
        self.rugcheck = RugCheckClient(api_key=settings.rugcheck_api_key)
        self.goplus = GoPlusClient(api_key=settings.goplus_api_key)
        self.twitter = TwitterClient(
            bearer_token=settings.x_bearer_token,
            cache_ttl_seconds=settings.social.cache_ttl_minutes * 60,
        )
        self._history: dict[str, CandidateHistory] = {}

    def scan(self, token_address: str, symbol: str) -> ScanRecord:
        rc_raw = self.rugcheck.get_report(token_address)
        gp_raw = self.goplus.get_token_security(token_address)
        merged = merge_reports(rugcheck_fields(rc_raw), goplus_fields(gp_raw), token_address)
        onchain_result = evaluate_onchain_safety(merged, self.settings.safety)

        mentions = self.twitter.search_token_mentions(
            symbol=symbol,
            token_address=token_address,
            max_reads=self.settings.social.max_reads_per_token_scan,
        )
        social_report = build_social_report(token_address, mentions, self.settings.social)
        social_result = evaluate_social_safety(social_report, self.settings.social)

        record = ScanRecord(timestamp=datetime.utcnow(), onchain=onchain_result, social=social_result)
        history = self._history.setdefault(token_address, CandidateHistory(token_address))
        history.scans.append(record)
        return record

    def is_tradable(self, token_address: str) -> bool:
        history = self._history.get(token_address)
        if not history:
            return False
        return history.is_confirmed(
            required_scans=self.settings.discovery.reconfirm_scans_required,
            gap_minutes=self.settings.discovery.reconfirm_gap_minutes,
        )

    def scan_count(self, token_address: str) -> int:
        history = self._history.get(token_address)
        return len(history.scans) if history else 0

    def close(self) -> None:
        self.dexscreener.close()
        self.rugcheck.close()
        self.goplus.close()
        self.twitter.close()
