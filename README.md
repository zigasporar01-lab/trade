# Memebot — a cautious Solana memecoin trading bot

A safety-first bot for trading Solana memecoins with small capital on a
**4-hour** timeframe. It refuses to touch a token unless it independently
passes an on-chain rug-pull check, a social/X due-diligence check, *and* a
technical entry signal — and even then, only after confirming the token
still looks safe on a second scan, minutes later.

> **This is not financial advice, and there is no such thing as a safe
> memecoin bot.** Memecoins are extremely high-risk, largely unregulated,
> and most of them go to zero. This bot reduces — it does not eliminate —
> the risk of buying an outright scam. Only ever risk money you can afford
> to lose completely. Start in paper mode and stay there for weeks before
> considering live capital.

---

## How it decides to trade

```
Discover candidates (DexScreener)
        │
        ▼
On-chain safety check (RugCheck + GoPlus)     ─┐
  mint/freeze authority renounced?              │  BOTH must pass,
  LP locked/burned?                              │  on TWO scans,
  holder concentration OK?                       │  15+ minutes apart,
  honeypot / buy-sell tax OK?                    │  before a token is
                                                 │  even eligible to
Social check (X / Twitter)                       │  trade. A single
  organic mention volume?                        │  DANGER at any point
  not a cluster of new/bot accounts?             │  resets the clock.
  not already full of "rug"/"scam" warnings?    ─┘
        │
        ▼
4h technical signal (GeckoTerminal OHLCV)
  uptrend (EMA9 > EMA21)
  confirmed breakout above upper Bollinger Band
  breakout volume >= 1.5x the 20-candle average
  RSI healthy (50–75), not already overbought
        │
        ▼
Risk-managed position size (1% account risk rule, capped at 15% of capital)
  blocked by: max concurrent positions / daily loss limit / loss-streak cooldown
        │
        ▼
Execute via Jupiter (paper: simulated fill / live: real swap)
        │
        ▼
Monitor: ATR stop-loss, 2.5R take-profit, trailing stop after 1.5R,
         and a hard time-based exit if neither hits within 8 hours
         (roughly double the 4h signal timeframe, per your "fast market" note).
```

Every rejection is logged with the exact reason, so you can see *why* the
bot passed on a token, not just that it did.

## Why these specific choices

- **Solana**: this is where the overwhelming majority of current memecoin
  volume and new launches happen (pump.fun, Raydium), and it has the best
  free tooling for rug detection (RugCheck, GoPlus).
- **"Don't make quick decisions"**: enforced structurally via the two-scan
  reconfirmation rule (`discovery.reconfirm_scans_required` /
  `reconfirm_gap_minutes` in `config/config.yaml`) — a token has to still
  look safe 15+ minutes after it first looked safe. A lot of rugs happen
  in exactly that window.
- **Missing data is never treated as safe.** If RugCheck or GoPlus can't
  tell us whether mint authority is renounced, that's a WARN, not a pass.
- **4-hour trades**: the signal is built on 4h candles (via GeckoTerminal's
  free OHLCV API), and every open position has a hard time-based exit after
  8 hours even if price never hits the stop or target — so the bot never
  ends up holding a stale bag indefinitely.
- **Two independent safety sources** (RugCheck + GoPlus): wherever they
  disagree on a yes/no safety flag, the more cautious answer always wins.

## What "rug pull" red flags this bot checks for

Based on how memecoin scams actually work:

| Red flag | What it means | How the bot checks |
|---|---|---|
| Mint authority not renounced | Creator can print unlimited new supply | RugCheck + GoPlus token metadata |
| Freeze authority not renounced | Creator can freeze your wallet's tokens | RugCheck + GoPlus token metadata |
| Liquidity not locked/burned | Creator can pull all liquidity instantly (the classic "rug") | RugCheck LP lock % |
| High holder concentration | A few wallets can dump and crash the price | Top-10 / largest-holder % |
| Honeypot | You can buy but can't sell | RugCheck + GoPlus honeypot simulation |
| High/adjustable sell tax | "Soft honeypot" — sells become unprofitable or impossible | Buy/sell tax % |
| Botted social hype | Coordinated pump preceding a coordinated dump | New-account ratio + duplicate-text clustering on X |
| Community already warning "rug"/"scam" | Read the room | Keyword-based negative sentiment ratio on X |

None of these tools are perfect, and none of this is a guarantee — see
[RugCheck's docs](https://api.rugcheck.xyz/swagger/index.html),
[GoPlus Security](https://docs.gopluslabs.io/), and
[DexScreener's rug-pull checklist](https://www.dextools.io/tutorials/how-to-spot-a-rug-pull-2026-checklist)
for more background on what these checks can and can't catch.

---

## Setup

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Copy the env file and fill in what you have

```bash
cp .env.example .env
```

Leave `MODE=paper` — do not touch live-mode settings yet.

### 3. Get API keys (all have free tiers except X)

| Service | Used for | Free tier? | Get it at |
|---|---|---|---|
| RugCheck | On-chain safety reports | Yes, **no key needed** — leave `RUGCHECK_API_KEY` blank | n/a |
| GoPlus Security | Second opinion on safety | Yes | https://console.gopluslabs.io |
| Jupiter | Swap quotes/execution | Yes (`lite-api.jup.ag`, low rate limit) | https://portal.jup.ag for a paid key later |
| X (Twitter) API | Social due-diligence | **No** — pay-per-use since Feb 2026 (~$0.005/read) | https://developer.x.com |
| Solana RPC | Reading prices/sending transactions | Yes (public RPC is slow/rate-limited) | https://helius.dev or https://quicknode.com |

DexScreener, GeckoTerminal (market data + 4h candles), and RugCheck's public
report endpoint all need **no API key**. RugCheck's authenticated tier uses a
Solana-wallet-signed login rather than a simple dashboard key, which this bot
doesn't implement — the free unauthenticated endpoint already provides
everything the safety screen needs.

X's API has no free tier anymore. The bot caches aggressively
(`social.cache_ttl_minutes`) and caps reads per token scan
(`social.max_reads_per_token_scan: 25` by default) to control spend — with
that cap, a scan costs roughly $0.125 (25 × $0.005) in the worst case.
If you'd rather not pay for it yet, set `social.enabled: false` in
`config/config.yaml` and the bot will skip the X check and rely on the
on-chain checks alone (not recommended long-term, but fine to get started).

### 4. (Recommended) Set up phone notifications and control via Telegram

Without this, the only way to see what the bot is doing is watching the
terminal. With it, you get a Telegram message whenever a position opens,
closes, or trading gets paused — and you can message a small set of
commands back to check on or control the bot from your phone.

1. In Telegram, message **@BotFather** and send `/newbot`. Follow the
   prompts (pick a name and a username ending in `bot`). It replies with a
   token like `123456789:AAExampleTokenGoesHere` — put that in `.env` as
   `TELEGRAM_BOT_TOKEN`.
2. Send your new bot any message first (e.g. "hi") — Telegram bots can't
   message you until you've messaged them.
3. Find your numeric chat ID: message **@userinfobot** and it replies with
   your ID (a number like `123456789`). Put that in `.env` as
   `TELEGRAM_CHAT_ID`.
4. That's it — no code changes needed, the bot picks this up automatically
   next time it starts.

Once running, tap the **menu button** next to Telegram's message box (or
type `/`) to see all commands as a tappable list:

| Command | What it does |
|---|---|
| `/status` | Mode, capital, open positions, daily PnL, whether trading is paused |
| `/positions` | Live details on every open position (entry, current price, PnL, stop, target) |
| `/pnl` | **All-time** realized PnL, win rate, best/worst trade — survives restarts. Includes a one-tap **"📊 Export to Excel"** button |
| `/export` | Sends the trade log straight to this chat as a formatted, color-coded `.xlsx` file |
| `/pause` | Stop opening new positions (anything already open keeps being monitored and can still hit its stop/target) |
| `/resume` | Re-enable opening new positions |
| `/help` | List commands |

This is a fixed set of commands, not free-form AI chat — the bot answers
with real numbers pulled from its own state, it doesn't reason or improvise
replies. Only messages from your configured `TELEGRAM_CHAT_ID` are acted on;
everything else is silently ignored, since the bot's username is publicly
searchable on Telegram.

### 5. Run in paper mode

```bash
python main.py --once      # single pass: good first test
python main.py              # runs continuously
```

Watch the logs. Every candidate token, every rejection reason, every
(simulated) trade is logged. **This is the mode you should run for weeks**
before ever considering live capital — you're validating both the strategy
and that the safety checks are actually catching what you think they are.

### 6. (Much later) Going live

Only after you've watched paper mode make sensible decisions for a while:

1. Create a **new, dedicated** Solana wallet — never reuse a wallet holding
   other funds. Export its private key (base58).
2. Fund it with only the small amount you're willing to lose entirely
   (matches `trading.capital_sol` in `config/config.yaml`).
3. In `.env`, set:
   ```
   MODE=live
   SOLANA_WALLET_PRIVATE_KEY=<your dedicated wallet's key>
   SOLANA_RPC_URL=<your Helius/QuickNode RPC URL>
   CONFIRM_LIVE_TRADING=YES_I_UNDERSTAND_THE_RISK
   ```
   Both `MODE=live` *and* `CONFIRM_LIVE_TRADING` are required — this is a
   deliberate second opt-in so live trading can never turn on by accident.
4. Start with `python main.py --once` again first, to watch one live pass
   before letting it run unattended.

Live orders are hard-capped at `max_position_size_pct` of your configured
capital regardless of what the sizing logic computes, as a last-resort
guard in `memebot/execution/live_broker.py`.

---

## Configuration

All strategy/risk knobs live in `config/config.yaml`, fully commented.
Secrets live in `.env`, never in the yaml file. Key ones to understand
before changing:

- `trading.capital_sol` — total bankroll the bot is allowed to touch.
- `trading.risk_per_trade_pct` — max % of capital lost if a single trade's
  stop-loss is hit (classic 1% rule).
- `trading.max_daily_loss_pct` / `max_consecutive_losses` — circuit
  breakers that pause trading after a bad run.
- `discovery.reconfirm_scans_required` / `reconfirm_gap_minutes` — the
  "don't make quick decisions" rule.
- `safety.*` — every on-chain rug-pull threshold.
- `social.*` — X due-diligence thresholds and spend controls.
- `strategy.*` / `exits.*` — the 4h technical signal and exit rules.

## Project layout

```
memebot/
  config.py            settings loader (config.yaml + .env)
  models.py             shared data types
  data/                 API clients: DexScreener, GeckoTerminal, RugCheck, GoPlus, X
  safety/                on-chain + social rug screening, two-scan reconfirmation
  strategy/              indicators (EMA/RSI/Bollinger/ATR) + 4h entry signal
  risk/                  position sizing (1% rule) + circuit breakers
  execution/             paper broker, Jupiter client, live broker
  core/                  bot loop, portfolio tracking, persistent trade log
tests/                   unit tests for every pure-logic module (no network calls)
main.py                  entry point
data/                    generated at runtime: trade_log_paper.csv / trade_log_live.csv (not tracked in git)
scripts/format_trade_log.py   turns the CSV into a formatted, color-coded .xlsx
```

## Viewing the trade log in Excel

Opening `data/trade_log_paper.csv` directly sometimes renders as one messy
column with no formatting — a regional-settings quirk (Excel expecting `;`
instead of `,` as the list separator on some Windows locales), not a
problem with the file itself.

**Easiest way**: send `/export` to the bot on Telegram (or tap the
"📊 Export to Excel" button on `/pnl`) and it delivers the formatted file
straight to the chat — no terminal needed.

Or generate it locally the same way the bot does internally:

```bash
python scripts/format_trade_log.py
```

This creates `data/trade_log_paper.xlsx` with a color-coded **Trades**
sheet (green rows for wins, red for losses, proper number/date formatting,
frozen header) and a **Summary** sheet with live formulas (total trades,
win rate, total/best/worst PnL) that recalculate automatically. Safe to
re-run anytime — it always rebuilds fresh from the current CSV. Double-click
the `.xlsx` to open it; it isn't a plain-text format, so it doesn't hit the
delimiter issue that affects the raw CSV.

## Testing

```bash
pytest tests/ -v
```

All 45 tests run offline against mock data — they validate the safety
scoring, position sizing, risk circuit breakers, and indicator math, not
live API behavior.

## Known limitations / what to improve before trusting this with real money

- **Discovery is search-based**, not a true "new pool" listener — DexScreener's
  free API has no dedicated new-pairs feed. For serious use, replace
  `DexScreenerClient.get_new_pairs` with a Helius webhook or a direct
  pump.fun/Raydium program-log listener for real-time new-pool detection.
- **Partial persistence**: closed-trade history is saved permanently to
  `data/trade_log_<mode>.csv` (readable in Excel/Sheets, and what `/pnl`
  reports from). *Open* positions and the risk manager's daily-loss/
  loss-streak counters are still in-memory only and reset if the process
  restarts — add a database or JSON snapshot for those before running live
  unattended for long periods.
- **X sentiment is keyword-based**, not a real NLP model — it catches
  obvious cases ("rug", "scam", "honeypot") but will miss subtler signals.
- **RugCheck's raw risk-score threshold** (`safety.max_rugcheck_risk_score`)
  is a rough starting point — tune it after looking at real report output
  for tokens you already know are safe vs. scams.
- Not audited by a security professional. Read every file in `memebot/safety/`
  and `memebot/risk/` yourself before trusting it with money.
