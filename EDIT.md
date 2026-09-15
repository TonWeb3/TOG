# Changelog & Port Documentation: Code 2 Modifications

This document details all modifications made to the codebase to port requested features from Code 3 while preserving the unique architecture, WebSocket stream design, and settlement engine of Code 2.

---

## Touched Files Summary

1. [`bot/config.py`](file:///c:/Users/abc/Downloads/15mins-polymarket-ws-audit-fix-3532565499328241598/bot/config.py)
   - Configured `CONFIG_PATH` directly to root `config.json`.
   - Added Capital Extractor settings (`AUTO_WITHDRAW_ENABLED`, `WITHDRAW_TRIGGER_BALANCE`, `WITHDRAW_AMOUNT`, `WITHDRAW_ADDRESS`, `WITHDRAW_AUTO_RESUME`, `WITHDRAW_RESUME_AFTER`).
   - Added Telegram settings (`TELEGRAM_ENABLED`, `TELEGRAM_BOT_TOKEN`).
   - Added Live order execution settings (`EXIT_MAX_RETRIES`, `CLOB_ALLOW_PARTIAL_FILL`, `MAX_BOOK_AGE_S`).
   - Updated `load_settings()` to parse nested config sections with legacy flat key fallbacks.

2. [`bot/clob_trader.py`](file:///c:/Users/abc/Downloads/15mins-polymarket-ws-audit-fix-3532565499328241598/bot/clob_trader.py)
   - Added `_PARTIAL_FILL_HINTS` class attribute to detect liquidity exhaustion / killed FOK orders.
   - Enhanced `_market_order()` to support explicit `OrderType` parameter.
   - Updated `place_market_buy()` with automatic **FOK $\rightarrow$ FAK fallback** when thin books reject complete fills.
   - Added `get_funder()` helper to retrieve the active funded wallet address.
   - Added `withdraw_pusd(recipient, amount)` for gasless automated profit skimming / capital extraction.
   - Added `is_tx_confirmed(tx_hash)` to verify on-chain polygon transaction finality.

3. [`bot/data.py`](file:///c:/Users/abc/Downloads/15mins-polymarket-ws-audit-fix-3532565499328241598/bot/data.py)
   - Updated `fetch_klines()` with a 3-attempt retry loop and strict length/field validation to guarantee full historical datasets for Heiken-Ashi and RSI calculations.
   - Added `sweep_sell(bids, size)` to compute effective VWAP sell price across order book levels.
   - Added `fetch_redeemable_positions(funder_address)` to query resolved conditional token positions from Polymarket Data API.

4. [`bot/ws_data.py`](file:///c:/Users/abc/Downloads/15mins-polymarket-ws-audit-fix-3532565499328241598/bot/ws_data.py)
   - Added `get_summary(asset_id, max_age_s)` method to `PolymarketClobMarketStream` for instant book evaluation with freshness check.
   - Made stream update callbacks coroutine-safe.

5. [`main.py`](file:///c:/Users/abc/Downloads/15mins-polymarket-ws-audit-fix-3532565499328241598/main.py)
   - **Real-Time Live PnL & WebSocket Stream**: Added `/ws` WebSocket endpoint and `broadcast_state()` to push live equity, position marks, and logs instantly to connected clients without polling lag.
   - **Independent Window Entries**: Replaced global `active_trades` lock with per-market ID slot checks. The bot enters new 15m windows immediately upon open without waiting for prior window trades to finish resolving.
   - **Capital Extractor State Machine**: Added `maybe_auto_withdraw()` background flow to skim profits above trigger thresholds and auto-resume.
   - **Telegram Integration**: Added `telegram_poller()`, command handling (`/start`, `/stop`, `/status`, `/balance`, `/help`), and automated notification dispatches for trade entries, wins, losses, and capital withdrawals.
   - **Manual & Auto Redemption**: Added `refresh_redeemable()`, `_redeem_all_run()`, `redeem_watcher()`, and endpoints `GET /api/redeemable`, `POST /api/redeem-all`, `POST /api/redeem`.
   - **Feed Freshness Guard**: Updated `mark_window_open()` to verify `price_is_fresh` before latching strike.
   - **Thread-safe Trades Snapshot**: Updated `update_trades()` to use snapshots to prevent race conditions during concurrent entries.

6. [`templates/index.html`](file:///c:/Users/abc/Downloads/15mins-polymarket-ws-audit-fix-3532565499328241598/templates/index.html)
   - Added WebSocket client (`/ws`) with automatic reconnect for real-time live PnL and UI state synchronization.
   - Added Manual Redeem button in the header bar showing redeemable position counts and live execution status.

7. [`templates/settings.html`](file:///c:/Users/abc/Downloads/15mins-polymarket-ws-audit-fix-3532565499328241598/templates/settings.html)
   - Added Capital Extractor configuration card (Trigger Balance, Withdraw Amount, Recipient Address, Auto-Resume, Resume Mode).
   - Added Telegram Bot configuration card (Enabled toggle, Bot Token).
   - Added Order Execution settings (FOK with FAK Fallback toggle, Max Book Age).

8. [`config.json`](file:///c:/Users/abc/Downloads/15mins-polymarket-ws-audit-fix-3532565499328241598/config.json)
   - Located in the root project folder.
   - Added default `capital_extractor` and `telegram` blocks.
   - Updated `live` with `exit_max_retries` and `allow_partial_fill`.
   - Updated `ev` with `max_book_age_s`.

9. **Deleted Unused Files & Folders**:
   - Removed `data/` and `tests/` directories.
   - Removed legacy unused modules: `bot/allowances.py`, `bot/risk.py`, and `bot/rpc_ws.py`.

---

## Detailed Feature Implementation

### 1. Capital Extractor & Telegram
- **Capital Extractor**: Automatically tracks total equity (cash balance + open mark value). When equity $\ge$ `WITHDRAW_TRIGGER_BALANCE`, it initiates a gasless transfer of `WITHDRAW_AMOUNT` pUSD to `WITHDRAW_ADDRESS` and enters a cooldown state until confirmed, after which it resumes automatically.
- **Telegram Bot**: Users subscribe by sending `/start` to the bot. Real-time markdown alerts are delivered on every trade entry (paper/live), win/loss settlement with profit details, and auto-withdrawals.

### 2. Real-Time Live PnL
- Replaced 1-second REST polling UI bottleneck with a bidirectional WebSocket stream at `/ws`.
- Position mark prices and unrealized PnL update immediately when order book ticks arrive, eliminating dashboard freezing.

### 3. FOK with FAK Fallback
- Buy orders first attempt Fill-Or-Kill (FOK) at the marketable limit price.
- If rejected due to partial fill or thin liquidity, the engine immediately retries with Fill-And-Kill (FAK) to capture available shares rather than dropping the trade.

### 4. Historical Data Completeness
- `fetch_klines()` validates that at least 15 valid candle rows with valid close prices are received, with automatic 3x retries if Binance returns an incomplete dataset.

### 5. Manual & Background Redemption
- Periodic background checker scans for resolved CTF conditional tokens.
- UI features a **"🎁 Redeem"** button to claim all resolved winnings into spendable pUSD with one click.
- Dedicated endpoints `/api/redeemable` and `/api/redeem-all` support automated and manual execution.

### 6. Early Entries in New Windows
- Trade eligibility is scoped per `market_id`.
- If an older trade from the previous window is still waiting for Polymarket's authoritative resolution (e.g., during the 90s grace period), the bot does NOT block entries for the new window.
- As soon as the new market opens and an EV edge appears, the bot enters immediately.
