"""Turns the persistent trade log into plain-English, actionable
suggestions — semi-automating the "review the log and notice patterns"
workflow, short of any real learning/adaptation (the bot never applies
these itself; a human reads them and decides whether to edit config.yaml).

Pure function over already-loaded CSV rows (list[dict], same shape
TradeLog.load_all() returns) — no I/O here, so it's fully unit-testable.
"""

from __future__ import annotations

from collections import defaultdict

MIN_TRADES_FOR_REASON_SUGGESTION = 3
MIN_TRADES_FOR_SYMBOL_FLAG = 2
MIN_TRADES_FOR_OVERALL_SUGGESTION = 5
LOW_WIN_RATE_THRESHOLD = 0.3
HIGH_STOP_LOSS_SHARE_THRESHOLD = 0.6


def _to_float(value: str | float | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def analyze(rows: list[dict]) -> dict:
    total_trades = len(rows)
    pnls = [_to_float(r.get("pnl_sol")) for r in rows]
    pnls = [p for p in pnls if p is not None]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p <= 0)

    by_reason: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_pnl_sol": 0.0})
    by_symbol: dict[str, dict] = defaultdict(lambda: {"count": 0, "wins": 0, "losses": 0, "total_pnl_sol": 0.0})

    for row in rows:
        pnl = _to_float(row.get("pnl_sol")) or 0.0
        reason = row.get("close_reason") or "unknown"
        by_reason[reason]["count"] += 1
        by_reason[reason]["total_pnl_sol"] += pnl

        symbol = row.get("symbol") or "unknown"
        by_symbol[symbol]["count"] += 1
        by_symbol[symbol]["total_pnl_sol"] += pnl
        if pnl > 0:
            by_symbol[symbol]["wins"] += 1
        else:
            by_symbol[symbol]["losses"] += 1

    for reason_stats in by_reason.values():
        reason_stats["avg_pnl_sol"] = reason_stats["total_pnl_sol"] / reason_stats["count"]

    overall = {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / len(pnls)) if pnls else None,
        "total_pnl_sol": sum(pnls),
    }

    suggestions = _build_suggestions(overall, dict(by_reason), dict(by_symbol))

    return {
        "overall": overall,
        "by_reason": dict(by_reason),
        "by_symbol": dict(by_symbol),
        "suggestions": suggestions,
    }


def _build_suggestions(overall: dict, by_reason: dict, by_symbol: dict) -> list[str]:
    suggestions: list[str] = []
    total_trades = overall["total_trades"]

    if total_trades == 0:
        return ["No closed trades yet — nothing to analyze."]

    max_hold = by_reason.get("max_hold_time")
    if max_hold and max_hold["count"] >= MIN_TRADES_FOR_REASON_SUGGESTION and max_hold["total_pnl_sol"] < 0:
        suggestions.append(
            f"{max_hold['count']} trades closed via max_hold_time with a combined "
            f"{max_hold['total_pnl_sol']:+.5f} SOL — consider lowering exits.max_hold_hours "
            "in config.yaml, since these positions are being held too long without the "
            "move materializing."
        )

    take_profit = by_reason.get("take_profit")
    if take_profit and take_profit["count"] >= MIN_TRADES_FOR_REASON_SUGGESTION and take_profit["total_pnl_sol"] > 0:
        suggestions.append(
            f"{take_profit['count']} trades hit take_profit for a combined "
            f"{take_profit['total_pnl_sol']:+.5f} SOL — the exit target is working well when the "
            "entry signal is right."
        )

    stop_loss = by_reason.get("stop_loss")
    if (
        stop_loss
        and total_trades >= MIN_TRADES_FOR_OVERALL_SUGGESTION
        and (stop_loss["count"] / total_trades) > HIGH_STOP_LOSS_SHARE_THRESHOLD
    ):
        suggestions.append(
            f"{stop_loss['count']}/{total_trades} trades ({stop_loss['count'] / total_trades * 100:.0f}%) "
            "hit stop_loss — the entry signal may be too loose. Consider tightening "
            "strategy.rsi_overbought, strategy.min_breakout_volume_multiplier, or "
            "strategy.require_higher_tf_confirmation in config.yaml."
        )

    if overall["win_rate"] is not None and total_trades >= MIN_TRADES_FOR_OVERALL_SUGGESTION:
        if overall["win_rate"] < LOW_WIN_RATE_THRESHOLD:
            suggestions.append(
                f"Overall win rate is {overall['win_rate'] * 100:.0f}% over {total_trades} trades — "
                "on the low side. Worth reviewing whether the R:R target (exits.take_profit_risk_reward) "
                "is realistic for how far these tokens actually tend to move."
            )

    repeat_losers = [
        symbol
        for symbol, stats in by_symbol.items()
        if stats["count"] >= MIN_TRADES_FOR_SYMBOL_FLAG and stats["wins"] == 0
    ]
    if repeat_losers:
        suggestions.append(
            f"These symbols lost every trade taken on them: {', '.join(sorted(repeat_losers))}. "
            "If any of these reappear, consider whether they're slipping past the safety checks "
            "for a reason worth investigating."
        )

    if total_trades < MIN_TRADES_FOR_OVERALL_SUGGESTION:
        suggestions.append(
            f"Only {total_trades} closed trade(s) so far — too small a sample to draw real "
            "conclusions from yet. Keep letting it run."
        )

    if not suggestions:
        suggestions.append("Nothing stands out yet — performance looks broadly in line across exit reasons.")

    return suggestions
