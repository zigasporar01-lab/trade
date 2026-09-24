"""Push notifications to your phone via a Telegram bot.

Not required for the bot to work — if TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
aren't set, every call here is a silent no-op. When configured, this is the
recommended way to "watch" the bot without staring at a terminal: it messages
you on position open/close, risk-manager circuit breakers, and startup/shutdown.

A failed notification must never crash or interrupt trading — sending an
alert is strictly best-effort.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import structlog

log = structlog.get_logger(__name__)

BASE_URL = "https://api.telegram.org"


class TelegramNotifier:
    def __init__(self, bot_token: str | None, chat_id: str | None, client: httpx.Client | None = None) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._client = client or httpx.Client(timeout=10.0)

    @property
    def configured(self) -> bool:
        return bool(self._bot_token and self._chat_id)

    def send(self, message: str, reply_markup: dict | None = None) -> None:
        if not self.configured:
            return
        payload = {"chat_id": self._chat_id, "text": message, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            resp = self._client.post(f"{BASE_URL}/bot{self._bot_token}/sendMessage", json=payload)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - a failed notification must never break the bot
            log.warning("telegram.send_failed", error=str(exc))

    def send_document(self, file_path: Path, caption: str | None = None) -> None:
        if not self.configured:
            return
        try:
            with open(file_path, "rb") as f:
                resp = self._client.post(
                    f"{BASE_URL}/bot{self._bot_token}/sendDocument",
                    data={"chat_id": self._chat_id, **({"caption": caption} if caption else {})},
                    files={"document": (file_path.name, f)},
                    timeout=30.0,
                )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - a failed send must never break the bot
            log.warning("telegram.send_document_failed", error=str(exc))

    def close(self) -> None:
        self._client.close()
