"""Two-way Telegram control: a background thread long-polls for incoming
messages and responds to a small fixed set of commands with live data
pulled straight from the running bot — no free-form AI chat, just
/status, /positions, /pnl, /pause, /resume.

Security: the bot's Telegram username is publicly searchable, so anyone
could message it. Every incoming message is checked against the configured
chat_id; anything else is logged and silently ignored rather than acted on.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

import httpx
import structlog

from memebot.core.trade_analysis import analyze
from memebot.core.xlsx_export import build_workbook
from memebot.utils.telegram_notifier import BASE_URL, TelegramNotifier

log = structlog.get_logger(__name__)

POLL_TIMEOUT_SECONDS = 25

BOT_COMMANDS = [
    {"command": "status", "description": "Mode, capital, open positions, daily PnL"},
    {"command": "positions", "description": "Details on each open position"},
    {"command": "pnl", "description": "All-time realized PnL summary"},
    {"command": "analyze", "description": "Plain-English patterns and suggestions from the trade log"},
    {"command": "export", "description": "Get the trade log as a formatted Excel file"},
    {"command": "pause", "description": "Stop opening new positions"},
    {"command": "resume", "description": "Re-enable opening new positions"},
    {"command": "closeall", "description": "EMERGENCY: sell every open position right now"},
    {"command": "help", "description": "List commands"},
]


class TelegramCommandListener:
    def __init__(
        self,
        bot_token: str | None,
        chat_id: str | None,
        notifier: TelegramNotifier,
        portfolio,
        risk_manager,
        settings,
        dexscreener,
        trade_log,
        state_store=None,
        close_all_callback=None,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = str(chat_id) if chat_id else None
        self._notifier = notifier
        self._portfolio = portfolio
        self._risk_manager = risk_manager
        self._settings = settings
        self._close_all_callback = close_all_callback
        self._dexscreener = dexscreener
        self._trade_log = trade_log
        self._state_store = state_store
        self._client = httpx.Client(timeout=POLL_TIMEOUT_SECONDS + 10)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset = 0

    @property
    def configured(self) -> bool:
        return bool(self._bot_token and self._chat_id)

    def start(self) -> None:
        if not self.configured:
            return
        self._register_command_menu()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="telegram-commands")
        self._thread.start()
        log.info("telegram.command_listener_started")

    def _register_command_menu(self) -> None:
        # Makes the commands appear as a tappable list behind Telegram's "/"
        # menu button, instead of the user having to type them out.
        try:
            resp = self._client.post(
                f"{BASE_URL}/bot{self._bot_token}/setMyCommands",
                json={"commands": BOT_COMMANDS},
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - purely cosmetic, must never block startup
            log.warning("telegram.set_commands_failed", error=str(exc))

    def stop(self) -> None:
        self._stop_event.set()
        self._client.close()

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:  # noqa: BLE001 - a failed poll must never kill the listener thread
                log.warning("telegram.poll_failed", error=str(exc))
                time.sleep(5)

    def _poll_once(self) -> None:
        resp = self._client.get(
            f"{BASE_URL}/bot{self._bot_token}/getUpdates",
            params={"offset": self._offset, "timeout": POLL_TIMEOUT_SECONDS},
        )
        resp.raise_for_status()
        for update in resp.json().get("result", []):
            self._offset = update["update_id"] + 1

            callback_query = update.get("callback_query")
            if callback_query:
                self._handle_callback_query(callback_query)
                continue

            message = update.get("message") or {}
            chat = message.get("chat") or {}
            text = (message.get("text") or "").strip()

            if str(chat.get("id")) != self._chat_id:
                log.warning("telegram.ignored_unauthorized_chat", chat_id=chat.get("id"))
                continue
            if text.startswith("/"):
                self._handle_command(text)

    def _handle_callback_query(self, callback_query: dict) -> None:
        chat_id = ((callback_query.get("message") or {}).get("chat") or {}).get("id")
        data = callback_query.get("data") or ""

        # Always acknowledge the tap so Telegram clears the button's loading
        # spinner, even for a chat we're about to ignore.
        try:
            self._client.post(
                f"{BASE_URL}/bot{self._bot_token}/answerCallbackQuery",
                json={"callback_query_id": callback_query.get("id")},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("telegram.answer_callback_failed", error=str(exc))

        if str(chat_id) != self._chat_id:
            log.warning("telegram.ignored_unauthorized_chat", chat_id=chat_id)
            return

        if data == "export":
            try:
                self._cmd_export()
            except Exception as exc:  # noqa: BLE001 - a broken handler must not kill the listener
                log.warning("telegram.command_failed", command="export", error=str(exc))
                self._notifier.send("⚠️ Something went wrong generating the Excel export. Check the terminal logs.")

    def _handle_command(self, text: str) -> None:
        command = text.split()[0].lower().lstrip("/").split("@")[0]
        handlers = {
            "start": self._cmd_help,
            "help": self._cmd_help,
            "status": self._cmd_status,
            "positions": self._cmd_positions,
            "pnl": self._cmd_pnl,
            "analyze": self._cmd_analyze,
            "export": self._cmd_export,
            "pause": self._cmd_pause,
            "resume": self._cmd_resume,
            "closeall": self._cmd_closeall,
        }
        handler = handlers.get(command)
        if handler is None:
            self._notifier.send(f"Unknown command: /{command}\nSend /help to see available commands.")
            return
        try:
            handler()
        except Exception as exc:  # noqa: BLE001 - a broken command handler must not kill the listener
            log.warning("telegram.command_failed", command=command, error=str(exc))
            self._notifier.send(f"⚠️ Something went wrong running /{command}. Check the terminal logs.")

    def _cmd_help(self) -> None:
        self._notifier.send(
            "<b>Available commands</b>\n"
            "/status — mode, capital, open positions, daily PnL\n"
            "/positions — details on each open position\n"
            "/pnl — all-time realized PnL (survives restarts)\n"
            "/analyze — plain-English patterns and suggestions from the trade log\n"
            "/export — get the trade log as a formatted Excel file\n"
            "/pause — stop opening new positions (open ones still monitored)\n"
            "/resume — re-enable opening new positions\n"
            "/closeall — EMERGENCY: sell every open position right now\n"
            "/help — this message"
        )

    def _cmd_status(self) -> None:
        rm = self._risk_manager
        paused_reason = None
        if rm.state.manual_pause:
            paused_reason = "manually paused"
        elif rm.state.paused_until and datetime.utcnow() < rm.state.paused_until:
            paused_reason = f"loss-streak cooldown until {rm.state.paused_until.strftime('%H:%M UTC')}"

        self._notifier.send(
            f"<b>Status</b> ({'⚠️ LIVE' if self._settings.is_live else 'paper'})\n"
            f"Capital: {self._settings.trading.capital_sol} SOL\n"
            f"Open positions: {self._portfolio.open_count}/{self._settings.trading.max_concurrent_positions}\n"
            f"Committed: {self._portfolio.open_capital_sol:.5f} SOL\n"
            f"Daily PnL: {rm.state.daily_pnl_sol:+.5f} SOL\n"
            f"Consecutive losses: {rm.state.consecutive_losses}\n"
            f"Trading: {'⏸ PAUSED (' + paused_reason + ')' if paused_reason else '▶️ active'}"
        )

    def _cmd_positions(self) -> None:
        positions = list(self._portfolio.open_positions.values())
        if not positions:
            self._notifier.send("No open positions.")
            return

        lines = ["<b>Open positions</b>"]
        for p in positions:
            current_price = None
            try:
                pairs = self._dexscreener.get_token_pairs(self._settings.trading.chain, p.token_address)
                if pairs:
                    current_price = pairs[0].price_usd
            except Exception:  # noqa: BLE001 - show the position without a live price rather than fail the reply
                pass

            pnl_str = "unknown"
            price_str = "unknown"
            if current_price is not None:
                pnl_str = f"{(current_price - p.entry_price) / p.entry_price * 100:+.1f}%"
                price_str = f"${current_price:.8f}"

            lines.append(
                f"\n<b>{p.symbol}</b>\n"
                f"Entry: ${p.entry_price:.8f}  Now: {price_str}\n"
                f"PnL: {pnl_str}\n"
                f"Stop: ${p.stop_loss:.8f}  Target: ${p.take_profit:.8f}\n"
                f"Opened: {p.opened_at.strftime('%Y-%m-%d %H:%M UTC')}"
            )
        self._notifier.send("\n".join(lines))

    def _cmd_pnl(self) -> None:
        # All-time, from the persistent trade log — not just this session's
        # in-memory state, which resets every time the process restarts.
        s = self._trade_log.summary()
        win_rate = f"{s['win_rate'] * 100:.0f}%" if s["win_rate"] is not None else "n/a"
        best = f"{s['best_trade_sol']:+.5f} SOL" if s["best_trade_sol"] is not None else "n/a"
        worst = f"{s['worst_trade_sol']:+.5f} SOL" if s["worst_trade_sol"] is not None else "n/a"
        self._notifier.send(
            "<b>All-time PnL</b> (survives restarts)\n"
            f"Closed trades: {s['total_trades']} ({s['wins']}W / {s['losses']}L, {win_rate} win rate)\n"
            f"Total realized PnL: {s['total_pnl_sol']:+.5f} SOL\n"
            f"Best trade: {best}\n"
            f"Worst trade: {worst}\n"
            f"Currently open: {self._portfolio.open_count}",
            reply_markup={"inline_keyboard": [[{"text": "📊 Export to Excel", "callback_data": "export"}]]},
        )

    def _cmd_analyze(self) -> None:
        rows = self._trade_log.load_all()
        result = analyze(rows)
        o = result["overall"]

        lines = ["<b>Trade log analysis</b>", f"Total trades: {o['total_trades']}"]
        if o["win_rate"] is not None:
            lines.append(f"Win rate: {o['win_rate'] * 100:.0f}% ({o['wins']}W / {o['losses']}L)")
        lines.append(f"Total PnL: {o['total_pnl_sol']:+.5f} SOL")

        if result["by_reason"]:
            lines.append("\n<b>By exit reason</b>")
            for reason, stats in sorted(result["by_reason"].items(), key=lambda kv: -kv[1]["count"]):
                lines.append(f"{reason}: {stats['count']} trades, {stats['total_pnl_sol']:+.5f} SOL")

        lines.append("\n<b>Suggestions</b>")
        for s in result["suggestions"]:
            lines.append(f"• {s}")

        self._notifier.send("\n".join(lines))

    def _cmd_export(self) -> None:
        rows = self._trade_log.load_all()
        wb = build_workbook(rows)
        output_path = self._trade_log.path.with_suffix(".xlsx")
        wb.save(output_path)
        self._notifier.send_document(output_path, caption=f"Trade log export — {len(rows)} closed trade(s)")

    def _save_state(self) -> None:
        if self._state_store is None:
            return
        try:
            self._state_store.save(list(self._portfolio.open_positions.values()), self._risk_manager.state)
        except Exception as exc:  # noqa: BLE001 - a failed state save must never break a command reply
            log.warning("telegram.state_save_failed", error=str(exc))

    def _cmd_pause(self) -> None:
        self._risk_manager.pause_manually()
        self._save_state()
        self._notifier.send(
            "⏸ Trading paused. Open positions are still monitored and can still "
            "hit their stop/target. Send /resume to re-enable new entries."
        )

    def _cmd_resume(self) -> None:
        self._risk_manager.resume_manually()
        self._save_state()
        self._notifier.send("▶️ Trading resumed. New candidates can be entered again.")

    def _cmd_closeall(self) -> None:
        if self._close_all_callback is None:
            self._notifier.send("⚠️ /closeall isn't wired up in this bot instance.")
            return

        open_count = self._portfolio.open_count
        if open_count == 0:
            self._notifier.send("No open positions to close.")
            return

        self._notifier.send(f"🚨 Closing all {open_count} open position(s) now...")
        closed_count = self._close_all_callback()
        self._notifier.send(
            f"🚨 <b>Emergency close complete</b>: {closed_count}/{open_count} position(s) closed. "
            f"Trading remains active for new entries — send /pause if you want to stop that too."
        )
