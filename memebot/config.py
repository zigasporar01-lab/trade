from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"


class TradingConfig(BaseModel):
    mode: str = "paper"
    chain: str = "solana"
    base_currency: str = "SOL"
    capital_sol: float = 0.5
    max_concurrent_positions: int = 2
    max_position_size_pct: float = 0.15
    risk_per_trade_pct: float = 0.01
    max_daily_loss_pct: float = 0.05
    max_consecutive_losses: int = 3
    cooldown_minutes_after_loss_streak: int = 240
    slippage_bps: int = 150


class DiscoveryConfig(BaseModel):
    min_liquidity_usd: float = 15000
    min_24h_volume_usd: float = 20000
    min_token_age_minutes: int = 60
    max_token_age_hours: int = 168
    min_holder_count: int = 100
    reconfirm_scans_required: int = 2
    reconfirm_gap_minutes: int = 15


class SafetyConfig(BaseModel):
    require_mint_authority_renounced: bool = True
    require_freeze_authority_renounced: bool = True
    require_lp_locked_or_burned: bool = True
    min_lp_locked_pct: float = 90
    max_top10_holder_pct: float = 30
    max_single_holder_pct: float = 15
    max_buy_tax_pct: float = 10
    max_sell_tax_pct: float = 10
    reject_on_honeypot_flag: bool = True
    max_rugcheck_risk_score: float = 4000
    min_goplus_confidence: float = 0.6


class SocialConfig(BaseModel):
    enabled: bool = True
    min_unique_authors_24h: int = 3
    min_mentions_24h: int = 5
    max_new_account_ratio: float = 0.6
    min_account_age_days: int = 14
    max_negative_sentiment_ratio: float = 0.6
    cache_ttl_minutes: int = 20
    max_reads_per_token_scan: int = 25


class StrategyConfig(BaseModel):
    timeframe: str = "4h"
    ohlcv_aggregate_hours: int = 4
    candles_lookback: int = 60
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    rsi_overbought: float = 75
    rsi_oversold: float = 25
    bb_period: int = 20
    bb_std_dev: float = 2.0
    atr_period: int = 14
    min_breakout_volume_multiplier: float = 1.5
    require_higher_tf_confirmation: bool = True
    higher_tf_aggregate_hours: int = 24
    higher_tf_ema_fast: int = 9
    higher_tf_ema_slow: int = 21


class ExitsConfig(BaseModel):
    stop_loss_atr_multiplier: float = 1.75
    take_profit_risk_reward: float = 2.5
    max_hold_hours: int = 8
    trailing_stop_activate_rr: float = 1.5
    partial_exit_enabled: bool = True
    partial_exit_pct: float = 0.5


class LoopConfig(BaseModel):
    discovery_interval_minutes: int = 15
    position_monitor_interval_minutes: int = 5


class Settings(BaseModel):
    trading: TradingConfig = Field(default_factory=TradingConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    social: SocialConfig = Field(default_factory=SocialConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    exits: ExitsConfig = Field(default_factory=ExitsConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)

    # Secrets / env-derived, not part of config.yaml
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    solana_wallet_private_key: str | None = None
    jupiter_api_key: str | None = None
    jupiter_base_url: str = "https://lite-api.jup.ag"
    rugcheck_api_key: str | None = None
    goplus_api_key: str | None = None
    x_bearer_token: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @property
    def is_live(self) -> bool:
        return self.mode_normalized == "live"

    @property
    def mode_normalized(self) -> str:
        return self.trading.mode.strip().lower()


def load_settings(config_path: Path | None = None, env_path: Path | None = None) -> Settings:
    """Load config.yaml + .env into a validated Settings object.

    Config file controls strategy/risk knobs. Environment variables carry
    secrets and never live in the yaml file.
    """
    load_dotenv(env_path or (REPO_ROOT / ".env"))

    raw: dict[str, Any] = {}
    path = config_path or DEFAULT_CONFIG_PATH
    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

    settings = Settings(**raw)

    settings.solana_rpc_url = os.getenv("SOLANA_RPC_URL", settings.solana_rpc_url)
    settings.solana_wallet_private_key = os.getenv("SOLANA_WALLET_PRIVATE_KEY") or None
    settings.jupiter_api_key = os.getenv("JUPITER_API_KEY") or None
    settings.jupiter_base_url = os.getenv("JUPITER_BASE_URL", settings.jupiter_base_url)
    settings.rugcheck_api_key = os.getenv("RUGCHECK_API_KEY") or None
    settings.goplus_api_key = os.getenv("GOPLUS_API_KEY") or None
    settings.x_bearer_token = os.getenv("X_BEARER_TOKEN") or None
    settings.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or None
    settings.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID") or None

    # Environment MODE overrides yaml, so a shared config.yaml can't
    # accidentally flip someone into live trading.
    env_mode = os.getenv("MODE")
    if env_mode:
        settings.trading.mode = env_mode

    return settings
