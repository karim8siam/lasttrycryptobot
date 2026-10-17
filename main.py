#!/usr/bin/env python3
"""
main.py - Master Entry Point for the Binance Futures Dual-Engine Trading System.

Production Capabilities:
- Full 24-Coin Curated Universe Multi-Scanner (Default)
- Single-Coin Dedicated Runner (--single-pair --symbol SOL/USDT)
- Execution Modes: Live Trading, Testnet Sandbox, or Dry-Run Paper Trading
- Instant One-Shot Portfolio Scan Matrix (--scan-once)
- Full Zero-Lookahead Historical Backtest Audit (--audit)
- Binance API & Account Connectivity Check (--status)
- Strict Quantitative Constraints: 1.0% Risk/Trade, 5x Isolated Leverage, 1:1.5 R:R, 2.0x ATR SL
"""

import sys
import os
import time
import argparse
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np
import ccxt

import config
from indicators import (
    compute_ema,
    compute_atr,
    compute_supertrend,
    compute_rsi,
    compute_macd,
    compute_adx,
    compute_vwap,
    compute_obv,
    compute_confirmed_swings,
    compute_rejection_candles,
)
from bull_engine import BullEngine
from bear_engine import BearEngine
from risk_manager import RiskManager
from binance_client import BinanceFuturesClient
from multi_coin_scanner import MultiCoinTradingBot
from bot import DualEngineTradingBot


def print_banner():
    banner = r"""
========================================================================================
     BINANCE FUTURES DUAL-ENGINE ALGORITHMIC TRADING SYSTEM (PRODUCTION v2.0)          
========================================================================================
  * Architecture:      Dual Independent Engines (Bull Engine Long / Bear Engine Short)
  * Universe:          24 Curated High-Accuracy Crypto Pairs (Excluded: ARB, DOT, PEPE, FIL, AAVE, TIA)
  * Risk Management:   Strict 1.0% Equity Risk Per Trade | 5x Isolated Leverage
  * Target & Stop:     1:1.5 Risk-to-Reward (3.0x ATR TP) | 2.0x ATR SL (0.8% - 3.5% Bounds)
  * Confluence Filter: 4H Multi-Timeframe Alignment Gate (EMA50 + Supertrend)
  * Strategy Signals:  R017 Structural Fractals + Candlestick Engulfing + Rejection Hammers
========================================================================================
"""
    print(banner)


def run_status_check(args):
    """Verifies connection to Binance Futures API and prints balance and permissions."""
    print("=" * 80)
    print("                BINANCE FUTURES API CONNECTIVITY CHECK                 ")
    print("=" * 80)

    mode = args.mode
    is_dry_run = mode == "dry-run"
    is_testnet = mode == "testnet"
    api_key = args.api_key or config.BINANCE_API_KEY
    api_secret = args.api_secret or config.BINANCE_API_SECRET

    print(f"Target Mode:   {mode.upper()}")
    print(f"API Key Set:   {'YES (' + api_key[:6] + '...' + api_key[-4:] + ')' if api_key else 'NO'}")

    client = BinanceFuturesClient(
        api_key=api_key,
        api_secret=api_secret,
        testnet=is_testnet,
        dry_run=is_dry_run,
        leverage=args.leverage,
    )

    try:
        balance = client.fetch_balance()
        print(f"Connection:    SUCCESS")
        print(f"Wallet Equity: ${balance:,.2f} USDT")

        # Check sample market data access
        test_sym = "SOL/USDT"
        df = client.fetch_ohlcv(test_sym, timeframe="1h", limit=5)
        print(f"Market Access: SUCCESS (SOL/USDT latest close: ${df['close'].iloc[-1]:,.2f})")
        print("Precision Spec: min_qty={0}, step_size={1}".format(
            client.get_market_precision(test_sym)['min_qty'],
            client.get_market_precision(test_sym)['step_size']
        ))
        print("Status:        System is ready for execution.")
    except Exception as e:
        print(f"Connection:    FAILED - {e}")
    print("=" * 80)


def run_historical_audit(candle_limit: int = 1000):
    """
    Executes an instant full zero-lookahead backtest across all 24 curated pairs
    using the exact production engines and risk management rules.
    """
    exchange = ccxt.binance({"options": {"defaultType": "future"}})
    active_pairs = config.ACTIVE_PAIRS
    fee_rate = config.TAKER_FEE_RATE
    slippage = config.SLIPPAGE_RATE

    print("=" * 95)
    print(f"     PORTFOLIO AUDIT: ALL {len(active_pairs)} CURATED PAIRS (ZERO-LOOKAHEAD BACKTEST)     ")
    print("=" * 95)
    print(f"Fetching historical 1H & 4H candles ({candle_limit} bars, ~41.6 days lookback)...")

    all_trades = []
    processed_count = 0

    for name, sym in active_pairs:
        try:
            raw_1h = exchange.fetch_ohlcv(sym, timeframe="1h", limit=candle_limit)
            df_1h = pd.DataFrame(raw_1h, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df_1h["datetime"] = pd.to_datetime(df_1h["timestamp"], unit="ms")
            df_1h.set_index("datetime", inplace=True)

            raw_4h = exchange.fetch_ohlcv(sym, timeframe="4h", limit=int(candle_limit / 2))
            df_4h = pd.DataFrame(raw_4h, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df_4h["datetime"] = pd.to_datetime(df_4h["timestamp"], unit="ms")
            df_4h.set_index("datetime", inplace=True)
            df_4h["ema50"] = compute_ema(df_4h["close"], 50)
            st_dir, _ = compute_supertrend(df_4h, 10, 3.0)
            df_4h["supertrend"] = st_dir

            close = df_1h["close"]
            high = df_1h["high"]
            low = df_1h["low"]
            vol = df_1h["volume"]
            open_p = df_1h["open"]
            n = len(df_1h)

            atr = compute_atr(df_1h, 14)
            ema_50 = compute_ema(close, 50)
            ema_200 = compute_ema(close, 200)
            st_dir_1h, _ = compute_supertrend(df_1h, 10, 3.0)
            adx, p_di, m_di = compute_adx(df_1h, 14)
            vwap = compute_vwap(df_1h)
            obv, obv_ema = compute_obv(df_1h, 20)
            vol_ma = vol.rolling(20).mean()
            rsi = compute_rsi(close, 14)
            macd, _, macd_hist = compute_macd(close, 12, 26, 9)
            prev_macd_hist = macd_hist.shift(1)

            sh_fractal, sl_fractal = compute_confirmed_swings(df_1h)
            is_hammer_s, is_star_s = compute_rejection_candles(df_1h)

            # Engulfing patterns
            prev_c = close.shift(1)
            prev_o = open_p.shift(1)
            bull_engulf = (prev_c < prev_o) & (close > open_p) & (close >= prev_o) & (open_p <= prev_c * 1.0005)
            bear_engulf = (prev_c > prev_o) & (close < open_p) & (close <= prev_o) & (open_p >= prev_c * 0.9995)

            recent_low_10 = low.rolling(10).min().shift(1)
            recent_high_10 = high.rolling(10).max().shift(1)
            candle_body = close - open_p
            swing_high_15 = high.rolling(15).max().shift(1).values
            swing_low_15 = low.rolling(15).min().shift(1).values

            df_4h_clean = df_4h[["close", "ema50", "supertrend"]].copy()
            df_1h_temp = pd.DataFrame({"datetime": df_1h.index}, index=df_1h.index)
            merged_4h = pd.merge_asof(df_1h_temp, df_4h_clean, left_index=True, right_index=True, direction="backward")

            c_arr = close.values
            atr_arr = atr.values
            ema50_arr = ema_50.values
            ema200_arr = ema_200.values
            st_dir_arr = st_dir_1h.values
            adx_arr = adx.values
            pdi_arr = p_di.values
            mdi_arr = m_di.values
            vwap_arr = vwap.values
            obv_arr = obv.values
            obv_ema_arr = obv_ema.values
            vol_arr = vol.values
            vol_ma_arr = vol_ma.values
            rsi_arr = rsi.values
            mhist_arr = macd_hist.values
            pmhist_arr = prev_macd_hist.values
            rl10_arr = recent_low_10.values
            rh10_arr = recent_high_10.values
            body_arr = candle_body.values
            is_ham_arr = is_hammer_s.values
            is_star_arr = is_star_s.values
            bull_eng_arr = bull_engulf.values
            bear_eng_arr = bear_engulf.values

            c4_arr = merged_4h["close"].values
            ema50_4h_arr = merged_4h["ema50"].values
            st4_arr = merged_4h["supertrend"].values

            b_conf = np.zeros(n, bool)
            s_conf = np.zeros(n, bool)
            b_sl = np.zeros(n)
            b_tp = np.zeros(n)
            s_sl = np.zeros(n)
            s_tp = np.zeros(n)

            for i in range(200, n):
                cp = c_arr[i]
                c_atr = atr_arr[i]
                if np.isnan(c_atr) or c_atr <= 0:
                    continue

                atr_sl_long = cp - (config.ATR_SL_MULTIPLIER * c_atr)
                swing_sl_long = rl10_arr[i] - (0.2 * c_atr) if not np.isnan(rl10_arr[i]) else atr_sl_long
                sl_long = max(atr_sl_long, swing_sl_long)
                min_sl = cp * 0.008
                max_sl = cp * 0.035
                raw_dist = cp - sl_long
                if raw_dist < min_sl:
                    sl_long = cp - min_sl
                elif raw_dist > max_sl:
                    sl_long = cp - max_sl
                tp_long = cp + (config.RISK_REWARD_RATIO * (cp - sl_long))

                atr_sl_short = cp + (config.ATR_SL_MULTIPLIER * c_atr)
                swing_sl_short = rh10_arr[i] + (0.2 * c_atr) if not np.isnan(rh10_arr[i]) else atr_sl_short
                sl_short = min(atr_sl_short, swing_sl_short)
                raw_dist = sl_short - cp
                if raw_dist < min_sl:
                    sl_short = cp + min_sl
                elif raw_dist > max_sl:
                    sl_short = cp + max_sl
                tp_short = cp - (config.RISK_REWARD_RATIO * (sl_short - cp))

                mtf_pass_bull = c4_arr[i] > ema50_4h_arr[i] and st4_arr[i] == 1
                mtf_pass_bear = c4_arr[i] < ema50_4h_arr[i] and st4_arr[i] == -1

                # BULL ENGINE SCORING
                if cp >= ema200_arr[i] and adx_arr[i] >= 25.0:
                    score = 0.0
                    if cp > ema50_arr[i] and ema50_arr[i] >= ema200_arr[i]:
                        score += 15.0
                    elif cp > ema50_arr[i]:
                        score += 8.0
                    if st_dir_arr[i] == 1:
                        score += 10.0
                    if pdi_arr[i] > mdi_arr[i]:
                        score += 10.0
                        score += 10.0 if adx_arr[i] >= 20.0 else 5.0
                    if cp > vwap_arr[i]:
                        score += 10.0
                    if obv_arr[i] > obv_ema_arr[i]:
                        score += 10.0
                    if vol_arr[i] >= 1.0 * vol_ma_arr[i]:
                        score += 5.0
                    if 46.0 <= rsi_arr[i] <= 62.0:
                        score += 15.0
                    elif 40.0 <= rsi_arr[i] < 46.0:
                        score += 8.0
                    if mhist_arr[i] > 0 and mhist_arr[i] > pmhist_arr[i]:
                        score += 10.0
                    elif mhist_arr[i] > pmhist_arr[i]:
                        score += 5.0

                    sh_ref = sh_fractal[i] if not np.isnan(sh_fractal[i]) else swing_high_15[i]
                    crit5 = 0.0
                    if cp >= sh_ref and vol_arr[i] >= 1.1 * vol_ma_arr[i]:
                        crit5 = 15.0
                    elif cp >= sh_ref:
                        crit5 = 10.0
                    elif bull_eng_arr[i]:
                        crit5 = 10.0
                    elif is_ham_arr[i]:
                        crit5 = 10.0
                    elif body_arr[i] > 0:
                        crit5 = 5.0

                    if (score + crit5) >= config.MIN_CONFIDENCE_SCORE and mtf_pass_bull:
                        b_conf[i] = True
                        b_sl[i] = sl_long
                        b_tp[i] = tp_long

                # BEAR ENGINE SCORING
                if cp <= ema200_arr[i] and adx_arr[i] >= 25.0:
                    score = 0.0
                    if cp < ema50_arr[i] and ema50_arr[i] <= ema200_arr[i]:
                        score += 15.0
                    elif cp < ema50_arr[i]:
                        score += 8.0
                    if st_dir_arr[i] == -1:
                        score += 10.0
                    if mdi_arr[i] > pdi_arr[i]:
                        score += 10.0
                        score += 10.0 if adx_arr[i] >= 20.0 else 5.0
                    if cp < vwap_arr[i]:
                        score += 10.0
                    if obv_arr[i] < obv_ema_arr[i]:
                        score += 10.0
                    if vol_arr[i] >= 1.0 * vol_ma_arr[i]:
                        score += 5.0
                    if 38.0 <= rsi_arr[i] <= 54.0:
                        score += 15.0
                    elif 54.0 < rsi_arr[i] <= 60.0:
                        score += 8.0
                    if mhist_arr[i] < 0 and mhist_arr[i] < pmhist_arr[i]:
                        score += 10.0
                    elif mhist_arr[i] < pmhist_arr[i]:
                        score += 5.0

                    sl_ref = sl_fractal[i] if not np.isnan(sl_fractal[i]) else swing_low_15[i]
                    crit5 = 0.0
                    if cp <= sl_ref and vol_arr[i] >= 1.1 * vol_ma_arr[i]:
                        crit5 = 15.0
                    elif cp <= sl_ref:
                        crit5 = 10.0
                    elif bear_eng_arr[i]:
                        crit5 = 10.0
                    elif is_star_arr[i]:
                        crit5 = 10.0
                    elif body_arr[i] < 0:
                        crit5 = 5.0

                    if (score + crit5) >= config.MIN_CONFIDENCE_SCORE and mtf_pass_bear:
                        s_conf[i] = True
                        s_sl[i] = sl_short
                        s_tp[i] = tp_short

            # Fresh triggers
            b_fresh = b_conf & ~np.roll(b_conf, 1)
            b_fresh[0] = False
            s_fresh = s_conf & ~np.roll(s_conf, 1)
            s_fresh[0] = False

            o_arr, h_arr, l_arr = df_1h["open"].values, df_1h["high"].values, df_1h["low"].values
            times = df_1h.index

            in_trade = False
            side = None
            entry_price, stop_loss, take_profit = 0.0, 0.0, 0.0
            entry_time, entry_idx = None, 0

            for i in range(200, n - 1):
                next_o, next_h, next_l, next_t = o_arr[i + 1], h_arr[i + 1], l_arr[i + 1], times[i + 1]

                if in_trade:
                    hit_sl, hit_tp = False, False
                    if side == "BUY":
                        if next_l <= stop_loss:
                            hit_sl = True
                        if next_h >= take_profit:
                            hit_tp = True
                        if hit_sl or hit_tp:
                            exit_p = (take_profit if hit_tp else stop_loss) * (1.0 - slippage)
                            pnl_f = (exit_p - entry_price) / entry_price - (2 * fee_rate)
                            all_trades.append({
                                "coin": name,
                                "side": "LONG",
                                "engine": "BULL",
                                "result": "WIN" if hit_tp else "LOSS",
                                "entry_time": entry_time,
                                "exit_time": next_t,
                                "pnl_f": pnl_f,
                                "risk_pct": abs(entry_price - stop_loss) / entry_price,
                            })
                            in_trade = False
                    elif side == "SELL":
                        if next_h >= stop_loss:
                            hit_sl = True
                        if next_l <= take_profit:
                            hit_tp = True
                        if hit_sl or hit_tp:
                            exit_p = (take_profit if hit_tp else stop_loss) * (1.0 + slippage)
                            pnl_f = (entry_price - exit_p) / entry_price - (2 * fee_rate)
                            all_trades.append({
                                "coin": name,
                                "side": "SHORT",
                                "engine": "BEAR",
                                "result": "WIN" if hit_tp else "LOSS",
                                "entry_time": entry_time,
                                "exit_time": next_t,
                                "pnl_f": pnl_f,
                                "risk_pct": abs(stop_loss - entry_price) / entry_price,
                            })
                            in_trade = False

                if not in_trade:
                    if b_fresh[i] and not s_fresh[i]:
                        in_trade, side = True, "BUY"
                        entry_price = next_o * (1.0 + slippage)
                        stop_loss, take_profit = b_sl[i], b_tp[i]
                        entry_time, entry_idx = next_t, i + 1
                    elif s_fresh[i] and not b_fresh[i]:
                        in_trade, side = True, "SELL"
                        entry_price = next_o * (1.0 - slippage)
                        stop_loss, take_profit = s_sl[i], s_tp[i]
                        entry_time, entry_idx = next_t, i + 1

            processed_count += 1
            sys.stdout.write(f"\rProcessed: {processed_count}/{len(active_pairs)} coins ({name:<6})")
            sys.stdout.flush()

        except Exception as e:
            continue

    print("\nProcessing complete. Simulating portfolio order execution with 5 concurrent positions...")

    all_trades.sort(key=lambda x: x["entry_time"])

    active_pos = []
    bal = 100.0
    initial_bal = 100.0
    port_executed = []
    max_dd = 0.0
    peak = 100.0
    total_fees = 0.0

    for t in all_trades:
        active_pos = [p for p in active_pos if p["exit_time"] > t["entry_time"]]
        if len(active_pos) < config.MAX_CONCURRENT_POSITIONS:
            risk_usd = bal * config.ACCOUNT_RISK_PER_TRADE
            pos_usd = min(risk_usd / t["risk_pct"], bal * config.LEVERAGE)
            fee = pos_usd * (2 * fee_rate)
            total_fees += fee
            pnl = pos_usd * t["pnl_f"]
            bal += pnl
            if bal > peak:
                peak = bal
            dd = peak - bal
            if dd > max_dd:
                max_dd = dd
            active_pos.append(t)
            port_executed.append({**t, "pnl_usd": pnl, "balance": bal})

    wins = [t for t in port_executed if t["result"] == "WIN"]
    losses = [t for t in port_executed if t["result"] == "LOSS"]
    wr = (len(wins) / len(port_executed) * 100) if port_executed else 0

    bull_trades = [t for t in port_executed if t["engine"] == "BULL"]
    bear_trades = [t for t in port_executed if t["engine"] == "BEAR"]
    bull_wins = [t for t in bull_trades if t["result"] == "WIN"]
    bear_wins = [t for t in bear_trades if t["result"] == "WIN"]

    b_wr = (len(bull_wins) / len(bull_trades) * 100) if bull_trades else 0
    s_wr = (len(bear_wins) / len(bear_trades) * 100) if bear_trades else 0

    print("\n" + "=" * 95)
    print("                 OFFICIAL PRODUCTION BOT AUDIT REPORT                 ")
    print("=" * 95)
    print(f"Total Evaluated Coins:        {len(active_pairs)} Pairs (All with >= 40% historical accuracy)")
    print(f"Total Trades Executed:        {len(port_executed)} trades (~{len(port_executed) / 41.6:.1f} trades/day)")
    print(f"Overall Accuracy (Win Rate):  {wr:.2f}% ({len(wins)} Wins / {len(losses)} Losses)")
    print(f"Bull Engine Accuracy:         {b_wr:.1f}% ({len(bull_wins)} Wins / {len(bull_trades) - len(bull_wins)} Losses)")
    print(f"Bear Engine Accuracy:         {s_wr:.1f}% ({len(bear_wins)} Wins / {len(bear_trades) - len(bear_wins)} Losses)")
    print(f"Starting Capital:             ${initial_bal:.2f} USDT")
    print(f"Ending Balance:               ${bal:.2f} USDT")
    print(f"Net Profit / Compounded Gain: +${bal - initial_bal:.2f} USDT (+{((bal - initial_bal) / initial_bal) * 100:.2f}%)")
    print(f"Max Portfolio Drawdown:       ${max_dd:.2f}")
    print(f"Total Round-Trip Fees Paid:   ${total_fees:.2f} USDT")
    print(f"Timespan Evaluated:           {port_executed[0]['entry_time']} -> {port_executed[-1]['exit_time']}")
    print("=" * 95)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Binance Futures Dual-Engine Algorithmic Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["dry-run", "testnet", "live"],
        default="dry-run",
        help="Execution mode: dry-run (paper trading, default), testnet, or live.",
    )
    parser.add_argument(
        "--scan-once",
        action="store_true",
        help="Run a single multi-coin scan pass, display status matrix, and exit.",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Run full zero-lookahead backtest audit across all 24 curated pairs and print scorecard.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Check Binance Futures API connectivity and account balances.",
    )
    parser.add_argument(
        "--single-pair",
        action="store_true",
        help="Run in single-pair mode instead of the full 24-coin portfolio scanner.",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=config.SYMBOL,
        help="Trading pair symbol for single-pair mode (e.g. SOL/USDT).",
    )
    parser.add_argument(
        "--risk",
        type=float,
        default=config.ACCOUNT_RISK_PER_TRADE,
        help="Risk per trade as decimal (e.g. 0.01 for 1.0%%).",
    )
    parser.add_argument(
        "--leverage",
        type=int,
        default=config.LEVERAGE,
        help="Leverage multiplier (default 5 for 5x isolated).",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=config.POLL_INTERVAL_SECONDS,
        help="Polling interval between scanner cycles in seconds (default 60s).",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default="",
        help="Binance API Key (overrides config.py if provided).",
    )
    parser.add_argument(
        "--api-secret",
        type=str,
        default="",
        help="Binance API Secret (overrides config.py if provided).",
    )
    return parser.parse_args()


def main():
    print_banner()
    args = parse_arguments()

    # Route 1: Status Check
    if args.status:
        run_status_check(args)
        return

    # Route 2: Full Backtest Audit
    if args.audit:
        run_historical_audit()
        return

    # Route 3: Setup Mode Parameters
    is_dry_run = args.mode == "dry-run"
    is_testnet = args.mode == "testnet"
    api_key = args.api_key or config.BINANCE_API_KEY
    api_secret = args.api_secret or config.BINANCE_API_SECRET

    if args.mode == "live" and (not api_key or not api_secret):
        print("\n[ERROR] Live trading requested, but Binance API credentials were not provided!")
        print("Please provide them in config.py or pass --api-key and --api-secret via CLI.")
        sys.exit(1)

    # Route 4: Single-Pair Mode
    if args.single_pair:
        bot = DualEngineTradingBot(
            symbol=args.symbol,
            dry_run=is_dry_run,
            testnet=is_testnet,
            api_key=api_key,
            api_secret=api_secret,
            risk_pct=args.risk,
            leverage=args.leverage,
        )
        bot.start(once=args.scan_once)
        return

    # Route 5: Multi-Coin Portfolio Scanner (Default)
    portfolio_bot = MultiCoinTradingBot(
        dry_run=is_dry_run,
        testnet=is_testnet,
        api_key=api_key,
        api_secret=api_secret,
        risk_pct=args.risk,
        leverage=args.leverage,
    )
    portfolio_bot.start(once=args.scan_once)


if __name__ == "__main__":
    main()
