"""Tracks *estimated* X API spend so paid social checks can auto-pause once
a configured daily budget is hit, instead of draining a balance with no
warning.

X's search response doesn't include actual billed cost, so this estimates
from the documented per-item rates (memebot/data/twitter.py) applied to the
real tweet/profile counts returned by each call. It's a safety margin, not
an exact match to your X invoice — real cost can differ slightly depending
on X's own billing rules, so leave some headroom in the budget you set.

Persisted per UTC calendar day (atomic write, same temp-file + rename
pattern as state_store.py) so the count survives a bot restart within the
same day and resets cleanly at the next one.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

POST_READ_COST_USD = 0.005
PROFILE_READ_COST_USD = 0.010


@dataclass
class _DaySpend:
    day: str
    spend_usd: float


class SpendTracker:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def _load(self) -> _DaySpend:
        today = date.today().isoformat()
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text())
                if raw.get("day") == today:
                    return _DaySpend(day=today, spend_usd=float(raw.get("spend_usd", 0.0)))
            except (json.JSONDecodeError, OSError, ValueError):
                pass
        return _DaySpend(day=today, spend_usd=0.0)

    def _save(self) -> None:
        fd, tmp_path = tempfile.mkstemp(dir=str(self._path.parent), prefix=".spend_tmp_")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"day": self._state.day, "spend_usd": self._state.spend_usd}, f)
            os.replace(tmp_path, self._path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def _roll_day_if_needed(self) -> None:
        today = date.today().isoformat()
        if self._state.day != today:
            self._state = _DaySpend(day=today, spend_usd=0.0)

    def spent_today(self) -> float:
        self._roll_day_if_needed()
        return self._state.spend_usd

    def budget_exceeded(self, daily_budget_usd: float | None) -> bool:
        if daily_budget_usd is None:
            return False
        return self.spent_today() >= daily_budget_usd

    def record_reads(self, post_count: int, profile_count: int) -> None:
        self._roll_day_if_needed()
        self._state.spend_usd += post_count * POST_READ_COST_USD + profile_count * PROFILE_READ_COST_USD
        self._save()
