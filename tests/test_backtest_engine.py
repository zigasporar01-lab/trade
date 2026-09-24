from datetime import datetime, timedelta

from memebot.backtest import engine as engine_module
from memebot.backtest.engine import BacktestResult, BacktestTrade, _simulate_exit, run_backtest
from memebot.config import ExitsConfig, StrategyConfig, TradingConfig
from memebot.models import Candle, Signal

NOW = datetime(2026, 1, 1, 0, 0)


def make_candles(closes, highs=None, lows=None, volumes=None, start=NOW, step_hours=4):
    n = len(closes)
    highs = highs or [c * 1.01 for c in closes]
    lows = lows or [c * 0.99 for c in closes]
    volumes = volumes or [1000.0] * n
    return [
        Candle(
            timestamp=start + timedelta(hours=step_hours * i),
            open=closes[i],
            high=highs[i],
            low=lows[i],
            close=closes[i],
            volume=volumes[i],
        )
        for i in range(n)
    ]


def default_exits_cfg(**overrides):
    defaults = dict(stop_loss_atr_multiplier=1.75, take_profit_risk_reward=2.5, max_hold_hours=8, trailing_stop_activate_rr=1.5)
    defaults.update(overrides)
    return ExitsConfig(**defaults)


# ---------------------------------------------------------------------------
# _simulate_exit: pure function, easy to pin down exactly
# ---------------------------------------------------------------------------


def test_simulate_exit_hits_stop_loss():
    candles = make_candles(closes=[100, 100, 100], highs=[101, 101, 101], lows=[99, 94, 90])
    # entry at candle 0, stop at 95 -> candle 1's low of 94 breaches it
    exit_price, exit_index, reason = _simulate_exit(
        candles, entry_index=0, entry_price=100, stop_loss=95, take_profit=110, risk_unit=5, exits_cfg=default_exits_cfg()
    )
    assert reason == "stop_loss"
    assert exit_price == 95
    assert exit_index == 1


def test_simulate_exit_hits_take_profit():
    candles = make_candles(closes=[100, 100, 100], highs=[101, 111, 101], lows=[99, 99, 99])
    exit_price, exit_index, reason = _simulate_exit(
        candles, entry_index=0, entry_price=100, stop_loss=95, take_profit=110, risk_unit=5, exits_cfg=default_exits_cfg()
    )
    assert reason == "take_profit"
    assert exit_price == 110
    assert exit_index == 1


def test_simulate_exit_stop_checked_before_target_on_same_candle():
    # A single wide-range candle whose low breaches the stop AND whose high
    # clears the target -> the conservative assumption is the stop first.
    candles = make_candles(closes=[100, 100], highs=[101, 120], lows=[99, 80])
    exit_price, _exit_index, reason = _simulate_exit(
        candles, entry_index=0, entry_price=100, stop_loss=95, take_profit=110, risk_unit=5, exits_cfg=default_exits_cfg()
    )
    assert reason == "stop_loss"
    assert exit_price == 95


def test_simulate_exit_hits_max_hold_time():
    cfg = default_exits_cfg(max_hold_hours=8)
    # 4h candles: entry at index 0, max_hold_until = entry_time + 8h = index 2's timestamp
    candles = make_candles(closes=[100, 101, 102, 103], highs=[101, 102, 103, 104], lows=[99, 100, 101, 102])
    exit_price, exit_index, reason = _simulate_exit(
        candles, entry_index=0, entry_price=100, stop_loss=90, take_profit=200, risk_unit=10, exits_cfg=cfg
    )
    assert reason == "max_hold_time"
    assert exit_index == 2
    assert exit_price == candles[2].close


def test_simulate_exit_trailing_stop_locks_in_profit():
    cfg = default_exits_cfg(trailing_stop_activate_rr=1.5, max_hold_hours=1000)
    # entry 100, stop 90 -> risk_unit = 10. Trailing activates once price is
    # 1.5R above entry = 115. High-water-mark tracks candle HIGHS, peaking at
    # 130, so the trailing stop locks in at 130 - 10 = 120 once price pulls
    # back, instead of exiting at the original 90 stop.
    candles = make_candles(
        closes=[100, 120, 130, 121],
        highs=[101, 121, 130, 121],
        lows=[99, 119, 129, 119],
    )
    exit_price, _exit_index, reason = _simulate_exit(
        candles, entry_index=0, entry_price=100, stop_loss=90, take_profit=1000, risk_unit=10, exits_cfg=cfg
    )
    assert reason == "stop_loss"
    assert exit_price == 120  # trailed stop, not the original 90


def test_simulate_exit_runs_out_of_data():
    # max_hold_hours set far beyond the available candles so the time exit
    # can't fire first — isolates the genuine "ran out of history" path.
    candles = make_candles(closes=[100, 101, 102])
    exit_price, exit_index, reason = _simulate_exit(
        candles,
        entry_index=0,
        entry_price=100,
        stop_loss=50,
        take_profit=500,
        risk_unit=50,
        exits_cfg=default_exits_cfg(max_hold_hours=1000),
    )
    assert reason == "end_of_data"
    assert exit_index == 2
    assert exit_price == candles[-1].close


# ---------------------------------------------------------------------------
# run_backtest: engine wiring (sizing, compounding, resuming after exit),
# tested against a stubbed signal function so it doesn't depend on the
# strategy's exact real-world trigger conditions.
# ---------------------------------------------------------------------------


def make_trading_cfg(**overrides):
    defaults = dict(capital_sol=1.0, risk_per_trade_pct=0.01, max_position_size_pct=0.5)
    defaults.update(overrides)
    return TradingConfig(**defaults)


def test_no_trades_on_flat_data_with_real_signal_function():
    # Flat, low-volume, non-trending data should never satisfy the real
    # strategy's breakout/volume/RSI conditions.
    candles = make_candles(closes=[10.0] * 40, volumes=[100.0] * 40)
    result = run_backtest(candles, "FLAT", StrategyConfig(), default_exits_cfg(), make_trading_cfg())
    assert result.trades == []
    assert result.ending_capital_sol == result.starting_capital_sol


def test_engine_opens_and_closes_one_trade_via_stubbed_signal(monkeypatch):
    candles = make_candles(closes=[100] * 30, highs=[101] * 30, lows=[94] * 30)  # every candle's low breaches a 95 stop

    call_count = {"n": 0}

    def fake_signal(window, strategy_cfg, exits_cfg):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return Signal(should_enter=True, reasons=["stub"], entry_price=100, stop_loss=95, take_profit=110, atr=5)
        return Signal(should_enter=False, reasons=["already traded"])

    monkeypatch.setattr(engine_module, "generate_entry_signal", fake_signal)
    result = run_backtest(candles, "STUB", StrategyConfig(), default_exits_cfg(), make_trading_cfg())

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.pnl_sol < 0
    assert trade.r_multiple == -1.0  # exited exactly at the original stop, one full risk unit lost


def test_engine_never_shows_future_candles_to_signal_function(monkeypatch):
    seen_window_lengths = []

    def fake_signal(window, strategy_cfg, exits_cfg):
        seen_window_lengths.append(len(window))
        return Signal(should_enter=False, reasons=["never enter"])

    candles = make_candles(closes=[100] * 10)
    monkeypatch.setattr(engine_module, "generate_entry_signal", fake_signal)
    run_backtest(candles, "NOLOOKAHEAD", StrategyConfig(), default_exits_cfg(), make_trading_cfg())

    assert seen_window_lengths == list(range(1, 11))  # window grows by exactly one candle at a time, never more


def test_engine_compounds_capital_across_trades(monkeypatch):
    candles = make_candles(closes=[100] * 60, highs=[130] * 60, lows=[99] * 60)  # every candle's high clears a 110 target

    call_count = {"n": 0}

    def fake_signal(window, strategy_cfg, exits_cfg):
        call_count["n"] += 1
        if call_count["n"] in (1, 21):
            return Signal(should_enter=True, reasons=["stub"], entry_price=100, stop_loss=95, take_profit=110, atr=5)
        return Signal(should_enter=False, reasons=["no signal"])

    monkeypatch.setattr(engine_module, "generate_entry_signal", fake_signal)
    result = run_backtest(candles, "COMPOUND", StrategyConfig(), default_exits_cfg(), make_trading_cfg(), compounding=True)

    assert len(result.trades) == 2
    assert result.ending_capital_sol > result.starting_capital_sol
    # second trade's size should reflect the grown capital, not the original
    assert result.trades[1].size_sol > result.trades[0].size_sol


def test_summary_computes_win_rate_and_drawdown():
    result = BacktestResult(
        symbol="X",
        starting_capital_sol=1.0,
        ending_capital_sol=1.02,
        trades=[
            BacktestTrade("X", NOW, 100, NOW, 110, 95, 110, 0.1, 0.01, 0.1, 2.0, "take_profit"),
            BacktestTrade("X", NOW, 100, NOW, 95, 95, 110, 0.1, -0.005, -0.05, -1.0, "stop_loss"),
            BacktestTrade("X", NOW, 100, NOW, 105, 95, 110, 0.1, 0.005, 0.05, 1.0, "max_hold_time"),
        ],
    )
    s = result.summary
    assert s["total_trades"] == 3
    assert s["wins"] == 2
    assert s["losses"] == 1
    assert abs(s["win_rate"] - 2 / 3) < 1e-9
    assert abs(s["total_pnl_sol"] - 0.01) < 1e-9
    assert s["max_drawdown_pct"] > 0
