"""Main orchestration loop:

  discover -> on-chain+social safety gate (2-scan reconfirmation) ->
  4h technical signal -> risk-managed position sizing -> execute ->
  monitor open positions for stop/target/time exits.

Every stage can say no. The bot only ever acts on a token that survives
every single stage.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import structlog

from memebot.backtest.engine import run_backtest
from memebot.config import REPO_ROOT, Settings
from memebot.data.dexscreener import DexScreenerClient
from memebot.data.geckoterminal import GeckoTerminalClient
from memebot.execution.broker import Broker
from memebot.execution.jupiter_client import JupiterClient
from memebot.execution.live_broker import LiveBroker
from memebot.execution.paper_broker import PaperBroker
from memebot.models import Position
from memebot.risk.position_sizing import size_position
from memebot.risk.risk_manager import RiskManager
from memebot.safety.screener import SafetyScreener
from memebot.strategy.signals import generate_entry_signal
from memebot.core.portfolio import Portfolio
from memebot.core.state_store import StateStore
from memebot.core.trade_log import TradeLog
from memebot.utils.telegram_commands import TelegramCommandListener
from memebot.utils.telegram_notifier import TelegramNotifier

log = structlog.get_logger(__name__)

GECKOTERMINAL_NETWORK = {"solana": "solana"}


def _format_self_backtest(summary: dict | None) -> str:
    if summary is None:
        return "not enough history on this token yet to self-backtest"
    if summary["total_trades"] == 0:
        return "0 prior occurrences of this setup in its recent history (first time firing)"
    win_rate = f"{summary['win_rate'] * 100:.0f}%" if summary["win_rate"] is not None else "n/a"
    return f"{summary['total_trades']} prior trade(s), {win_rate} win rate, {summary['total_pnl_sol']:+.5f} SOL"


class MemeBot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.dexscreener = DexScreenerClient()
        self.geckoterminal = GeckoTerminalClient()
        self.screener = SafetyScreener(settings)
        self.jupiter = JupiterClient(base_url=settings.jupiter_base_url, api_key=settings.jupiter_api_key)
        self.broker: Broker = LiveBroker(settings, self.jupiter) if settings.is_live else PaperBroker(self.jupiter)
        self.portfolio = Portfolio()
        self.risk_manager = RiskManager(settings.trading, settings.trading.capital_sol)
        # Separate log/state per mode so paper-testing history never mixes with real trades.
        self.trade_log = TradeLog(REPO_ROOT / "data" / f"trade_log_{settings.mode_normalized}.csv")
        self.state_store = StateStore(REPO_ROOT / "data" / f"state_{settings.mode_normalized}.json")

        restored_positions, restored_risk_state = self.state_store.load()
        for p in restored_positions:
            self.portfolio.open_positions[p.token_address] = p
        if restored_risk_state:
            self.risk_manager.state = restored_risk_state
        self.restored_position_count = len(restored_positions)
        if restored_positions:
            log.warning(
                "bot.state_restored",
                open_positions=len(restored_positions),
                symbols=[p.symbol for p in restored_positions],
            )
        self.notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
        self.command_listener = TelegramCommandListener(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            notifier=self.notifier,
            portfolio=self.portfolio,
            risk_manager=self.risk_manager,
            settings=self.settings,
            dexscreener=self.dexscreener,
            trade_log=self.trade_log,
            state_store=self.state_store,
            close_all_callback=self.close_all_positions,
        )

        log.info(
            "bot.initialized",
            mode=settings.trading.mode,
            chain=settings.trading.chain,
            capital_sol=settings.trading.capital_sol,
        )

    def _save_state(self) -> None:
        try:
            self.state_store.save(list(self.portfolio.open_positions.values()), self.risk_manager.state)
        except Exception as exc:  # noqa: BLE001 - a failed state save must never block trading
            log.warning("bot.state_save_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Discovery + safety + signal + entry
    # ------------------------------------------------------------------
    def discover_candidates(self, query_terms: list[str]):
        cfg = self.settings.discovery
        try:
            markets = self.dexscreener.get_new_pairs(chain_id=self.settings.trading.chain, query_terms=query_terms)
        except Exception as exc:  # noqa: BLE001 - a failed discovery pass must not crash the bot
            log.warning("bot.discovery_failed", error=str(exc))
            return []
        candidates = []
        for m in markets:
            if m.liquidity_usd < cfg.min_liquidity_usd:
                continue
            if m.volume_24h_usd < cfg.min_24h_volume_usd:
                continue
            age = m.age_minutes
            if age is None or age < cfg.min_token_age_minutes:
                continue
            if age > cfg.max_token_age_hours * 60:
                continue
            candidates.append(m)
        log.info("bot.discovery", found=len(markets), passed_filters=len(candidates))
        return candidates

    def evaluate_candidate(self, market) -> None:
        if self.portfolio.has_open_position(market.token_address):
            return

        record = self.screener.scan(market.token_address, market.symbol)
        if not record.passed:
            log.info(
                "bot.candidate_rejected",
                token=market.token_address,
                symbol=market.symbol,
                onchain_verdict=record.onchain.verdict,
                onchain_reasons=record.onchain.reasons,
                social_verdict=record.social.verdict,
                social_reasons=record.social.reasons,
            )
            return

        if not self.screener.is_tradable(market.token_address):
            log.info(
                "bot.candidate_awaiting_reconfirmation",
                token=market.token_address,
                symbol=market.symbol,
                scans_so_far=self.screener.scan_count(market.token_address),
                required=self.settings.discovery.reconfirm_scans_required,
                gap_minutes=self.settings.discovery.reconfirm_gap_minutes,
            )
            return

        network = GECKOTERMINAL_NETWORK.get(self.settings.trading.chain, self.settings.trading.chain)
        try:
            candles = self.geckoterminal.get_ohlcv(
                network=network,
                pool_address=market.pair_address,
                aggregate_hours=self.settings.strategy.ohlcv_aggregate_hours,
                limit=self.settings.strategy.candles_lookback,
            )
        except Exception as exc:  # noqa: BLE001 - a candle-fetch failure skips this candidate, never crashes the bot
            log.warning("bot.candle_fetch_failed", token=market.token_address, error=str(exc))
            return

        # Higher-timeframe confirmation (e.g. daily): don't buy a 4h breakout
        # that's fighting the broader trend. A fetch failure here is treated
        # as "couldn't confirm" (empty list), not "skip the check" (None) —
        # missing data blocks the entry, it never defaults to favorable.
        higher_tf_candles = None
        if self.settings.strategy.require_higher_tf_confirmation:
            try:
                higher_tf_candles = self.geckoterminal.get_ohlcv(
                    network=network,
                    pool_address=market.pair_address,
                    aggregate_hours=self.settings.strategy.higher_tf_aggregate_hours,
                    limit=self.settings.strategy.higher_tf_ema_slow + 10,
                )
            except Exception as exc:  # noqa: BLE001 - treated as "not enough history", handled below
                log.warning("bot.higher_tf_candle_fetch_failed", token=market.token_address, error=str(exc))
                higher_tf_candles = []

        signal = generate_entry_signal(candles, self.settings.strategy, self.settings.exits, higher_tf_candles)
        if not signal.should_enter:
            log.info("bot.no_signal", token=market.token_address, symbol=market.symbol, reasons=signal.reasons)
            return

        # Self-backtest: how has this exact strategy performed on this exact
        # token's own recent history? Reuses the candles already fetched for
        # the live signal — zero extra API calls. Excludes the current
        # (still-open, no exit yet) signal candle so it only counts genuinely
        # completed historical trades, not the entry we're about to make.
        # Same caveats as any backtest apply: this reflects the technical
        # strategy only, not the safety gate, and a short window often
        # legitimately shows zero prior occurrences — that's informative on
        # its own, not a failure.
        self_backtest_summary = None
        history_candles = candles[:-1]
        if len(history_candles) >= 30:
            try:
                bt_result = run_backtest(
                    history_candles, market.symbol, self.settings.strategy, self.settings.exits, self.settings.trading
                )
                self_backtest_summary = bt_result.summary
            except Exception as exc:  # noqa: BLE001 - context only, must never block a live entry
                log.warning("bot.self_backtest_failed", token=market.token_address, error=str(exc))

        log.info(
            "bot.signal_context",
            token=market.token_address,
            symbol=market.symbol,
            self_backtest=self_backtest_summary,
        )

        can_open, reason = self.risk_manager.can_open_new_position(self.portfolio.open_count)
        if not can_open:
            log.info("bot.entry_blocked_by_risk_manager", token=market.token_address, reason=reason)
            return

        sizing = size_position(
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            capital_sol=self.settings.trading.capital_sol,
            open_positions_sol=self.portfolio.open_capital_sol,
            cfg=self.settings.trading,
        )
        if sizing.rejected:
            log.info("bot.sizing_rejected", token=market.token_address, reasons=sizing.reasons)
            return

        fill = self.broker.buy(market.token_address, sizing.size_sol, self.settings.trading.slippage_bps)
        if not fill.success:
            log.warning("bot.buy_failed", token=market.token_address, error=fill.error)
            return

        entry_price = fill.filled_price or signal.entry_price
        risk_unit = entry_price - signal.stop_loss
        position = Position(
            token_address=market.token_address,
            symbol=market.symbol,
            entry_price=entry_price,
            size_sol=sizing.size_sol,
            size_tokens=fill.filled_size or 0.0,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            risk_unit=risk_unit,
            opened_at=datetime.utcnow(),
            max_hold_until=datetime.utcnow() + timedelta(hours=self.settings.exits.max_hold_hours),
            high_water_mark=entry_price,
        )
        self.portfolio.open_position(position)
        self._save_state()
        self.notifier.send(
            f"🟢 <b>Opened {position.symbol}</b> ({'LIVE' if self.settings.is_live else 'paper'})\n"
            f"Entry: ${entry_price:.8f}\n"
            f"Size: {sizing.size_sol:.5f} SOL\n"
            f"Stop: ${signal.stop_loss:.8f}  Target: ${signal.take_profit:.8f}\n"
            f"Token: <code>{market.token_address}</code>\n"
            f"📈 Self-backtest (this token's own history): {_format_self_backtest(self_backtest_summary)}"
        )

    # ------------------------------------------------------------------
    # Exit monitoring
    # ------------------------------------------------------------------
    def _close_position(self, token_address: str, position, close_price: float, reason: str) -> bool:
        """Shared by monitor_positions (stop/target/time exits) and
        close_all_positions (the /closeall emergency command) so there's
        one place that handles selling, logging, and notifying — not two
        copies that could drift apart.
        """
        fill = self.broker.sell(token_address, position.size_tokens, self.settings.trading.slippage_bps)
        if not fill.success:
            log.error("bot.sell_failed", token=token_address, error=fill.error)
            return False

        final_price = fill.filled_price or close_price
        closed = self.portfolio.close_position(token_address, final_price, reason)
        if not closed:
            return False

        try:
            self.trade_log.record(closed, mode=self.settings.mode_normalized)
        except Exception as exc:  # noqa: BLE001 - a failed log write must never block trading
            log.warning("bot.trade_log_write_failed", error=str(exc))

        was_paused_before = self.risk_manager.state.paused_until
        self.risk_manager.record_trade_closed(closed.pnl_sol or 0.0)
        self._save_state()

        pnl_sol = closed.pnl_sol or 0.0
        emoji = "✅" if pnl_sol >= 0 else "🔻"
        self.notifier.send(
            f"{emoji} <b>Closed {closed.symbol}</b> ({reason})\n"
            f"PnL: {pnl_sol:+.5f} SOL ({(closed.pnl_pct or 0) * 100:+.1f}%)\n"
            f"Daily PnL: {self.risk_manager.state.daily_pnl_sol:+.5f} SOL"
        )

        now_paused = self.risk_manager.state.paused_until
        if now_paused and now_paused != was_paused_before:
            self.notifier.send(
                f"⏸ <b>Trading paused</b> until {now_paused.strftime('%Y-%m-%d %H:%M UTC')} "
                f"after {self.risk_manager.state.consecutive_losses} losses in a row."
            )
        return True

    def monitor_positions(self) -> None:
        cfg = self.settings.exits
        for token_address, position in list(self.portfolio.open_positions.items()):
            try:
                pairs = self.dexscreener.get_token_pairs(self.settings.trading.chain, token_address)
            except Exception as exc:  # noqa: BLE001 - a stale price read must never crash position monitoring
                log.warning("bot.price_lookup_error", token=token_address, error=str(exc))
                continue
            if not pairs:
                log.warning("bot.price_lookup_failed", token=token_address)
                continue
            current_price = pairs[0].price_usd

            reason = None
            if current_price <= position.stop_loss:
                reason = "stop_loss"
            elif current_price >= position.take_profit:
                reason = "take_profit"
            elif datetime.utcnow() >= position.max_hold_until:
                reason = "max_hold_time"
            else:
                if current_price > position.high_water_mark:
                    position.high_water_mark = current_price

                if not position.trailing_active and position.risk_unit > 0:
                    gained_r = (position.high_water_mark - position.entry_price) / position.risk_unit
                    if gained_r >= cfg.trailing_stop_activate_rr:
                        position.trailing_active = True
                        log.info("bot.trailing_stop_activated", token=token_address, gained_r=gained_r)

                if position.trailing_active:
                    new_stop = position.high_water_mark - position.risk_unit
                    if new_stop > position.stop_loss:
                        position.stop_loss = new_stop

            if reason:
                self._close_position(token_address, position, current_price, reason)

    def close_all_positions(self, reason: str = "manual_closeall") -> int:
        """The /closeall emergency stop: sell every open position right
        now, at whatever price is available. Used from the Telegram
        command listener via a bound callback.
        """
        closed_count = 0
        for token_address, position in list(self.portfolio.open_positions.items()):
            try:
                pairs = self.dexscreener.get_token_pairs(self.settings.trading.chain, token_address)
                current_price = pairs[0].price_usd if pairs else position.entry_price
            except Exception as exc:  # noqa: BLE001 - fall back to entry price rather than skip closing it
                log.warning("bot.closeall_price_lookup_failed", token=token_address, error=str(exc))
                current_price = position.entry_price

            if self._close_position(token_address, position, current_price, reason):
                closed_count += 1

        log.warning("bot.closeall_executed", closed_count=closed_count)
        return closed_count

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------
    def run_forever(self, query_terms: list[str]) -> None:
        loop_cfg = self.settings.loop
        last_discovery = datetime.min

        log.warning(
            "bot.starting",
            mode=self.settings.trading.mode,
            warning="LIVE TRADING" if self.settings.is_live else "paper trading (no funds at risk)",
        )
        restored_line = (
            f"\n🔄 Restored {self.restored_position_count} open position(s) from a previous session."
            if self.restored_position_count
            else ""
        )
        self.notifier.send(
            f"🤖 Memebot started — {'⚠️ LIVE TRADING' if self.settings.is_live else 'paper mode (no funds at risk)'}\n"
            f"Capital: {self.settings.trading.capital_sol} SOL"
            f"{restored_line}\n"
            f"Send /help to see available commands."
        )
        self.command_listener.start()

        while True:
            try:
                now = datetime.utcnow()

                if (now - last_discovery).total_seconds() >= loop_cfg.discovery_interval_minutes * 60:
                    for market in self.discover_candidates(query_terms):
                        self.evaluate_candidate(market)
                    last_discovery = now

                self.monitor_positions()

                log.info("bot.heartbeat", **self.portfolio.summary())
            except Exception as exc:  # noqa: BLE001
                # Last-resort safety net: an open position with a live stop-loss
                # must keep being watched even if something unanticipated breaks
                # discovery. Log it loudly and keep looping rather than exit.
                log.error("bot.loop_iteration_failed", error=str(exc))

            time.sleep(loop_cfg.position_monitor_interval_minutes * 60)

    def close(self) -> None:
        self.command_listener.stop()
        self.dexscreener.close()
        self.geckoterminal.close()
        self.screener.close()
        self.jupiter.close()
        self.notifier.close()
        if isinstance(self.broker, LiveBroker):
            self.broker.close()
