"""Entry point.

    python main.py                      # run continuously
    python main.py --once                # single discovery + monitor pass, then exit (good for testing)

Mode (paper/live) is controlled by MODE in your .env — see .env.example.
"""

from __future__ import annotations

import argparse

from memebot.config import load_settings
from memebot.core.bot import MemeBot
from memebot.utils.logging_setup import configure_logging

# Search terms used for candidate discovery via DexScreener's search endpoint.
# Tune this list to the narratives you want exposure to; it is intentionally
# generic rather than chasing a single trend.
DEFAULT_QUERY_TERMS = ["solana", "pump", "sol meme"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Memebot: cautious Solana memecoin trading bot")
    parser.add_argument("--once", action="store_true", help="Run a single discovery + monitor pass and exit")
    parser.add_argument("--query", action="append", help="Discovery search term (repeatable)")
    args = parser.parse_args()

    configure_logging()
    settings = load_settings()
    bot = MemeBot(settings)

    try:
        query_terms = args.query or DEFAULT_QUERY_TERMS
        if args.once:
            for market in bot.discover_candidates(query_terms):
                bot.evaluate_candidate(market)
            bot.monitor_positions()
        else:
            bot.run_forever(query_terms)
    finally:
        bot.close()


if __name__ == "__main__":
    main()
