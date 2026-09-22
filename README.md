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
| RugCheck | On-chain safety reports | Yes (basic) | https://rugcheck.xyz → sign up → API key |
| GoPlus Security | Second opinion on safety | Yes | https://gopluslabs.io |
| Jupiter | Swap quotes/execution | Yes (`lite-api.jup.ag`, low rate limit) | https://portal.jup.ag for a paid key later |
| X (Twitter) API | Social due-diligence | **No** — pay-per-use since Feb 2026 (~$0.005/read) | https://developer.x.com |
| Solana RPC | Reading prices/sending transactions | Yes (public RPC is slow/rate-limited) | https://helius.dev or https://quicknode.com |

DexScreener and GeckoTerminal (market data + 4h candles) need **no API key**.

X's API has no free tier anymore. The bot caches aggressively
(`social.cache_ttl_minutes`) and caps reads per token scan
(`social.max_reads_per_token_scan: 25` by default) to control spend — with
that cap, a scan costs roughly $0.125 (25 × $0.005) in the worst case.
If you'd rather not pay for it yet, set `social.enabled: false` in
`config/config.yaml` and the bot will skip the X check and rely on the
on-chain checks alone (not recommended long-term, but fine to get started).

### 4. Run in paper mode

```bash
python main.py --once      # single pass: good first test
python main.py              # runs continuously
```

Watch the logs. Every candidate token, every rejection reason, every
(simulated) trade is logged. **This is the mode you should run for weeks**
before ever considering live capital — you're validating both the strategy
and that the safety checks are actually catching what you think they are.

> **A note on this repository's dev environment**: the sandbox this bot was
> built in has restricted outbound network access and can't reach the live
> DexScreener/GeckoTerminal/RugCheck/GoPlus/Jupiter/X APIs, so the HTTP
> integration code hasn't been exercised against live traffic here — only
> unit-tested against the documented API shapes. Run `python main.py --once`
> yourself first, on a machine with normal internet access, and read the
> logs closely before leaving it running unattended.

### 5. (Much later) Going live

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
  core/                  bot loop + portfolio tracking
tests/                   unit tests for every pure-logic module (no network calls)
main.py                  entry point
```

## Testing

```bash
pytest tests/ -v
```

All 37 tests run offline against mock data — they validate the safety
scoring, position sizing, risk circuit breakers, and indicator math, not
live API behavior.

## Known limitations / what to improve before trusting this with real money

- **Discovery is search-based**, not a true "new pool" listener — DexScreener's
  free API has no dedicated new-pairs feed. For serious use, replace
  `DexScreenerClient.get_new_pairs` with a Helius webhook or a direct
  pump.fun/Raydium program-log listener for real-time new-pool detection.
- **No persistence**: portfolio/risk state resets if the process restarts.
  Fine for paper testing; add a database or JSON snapshot before running
  live unattended for long periods.
- **X sentiment is keyword-based**, not a real NLP model — it catches
  obvious cases ("rug", "scam", "honeypot") but will miss subtler signals.
- **RugCheck's raw risk-score threshold** (`safety.max_rugcheck_risk_score`)
  is a rough starting point — tune it after looking at real report output
  for tokens you already know are safe vs. scams.
- Not audited by a security professional. Read every file in `memebot/safety/`
  and `memebot/risk/` yourself before trusting it with money.
