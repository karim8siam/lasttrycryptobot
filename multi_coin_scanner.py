"""
multi_coin_scanner.py - Multi-Coin Portfolio Runner for Binance Futures.
Scans all 24 curated high-accuracy pairs every cycle:
- Evaluates Engine 1 (Bull) and Engine 2 (Bear) with 4H MTF Confluence Gate
- Enforces max 5 concurrent positions
- Sizes positions strictly to 1.0% equity risk with 5x isolated leverage
- Sets 1:1.5 Take Profit (3.0x ATR) and 2.0x ATR Stop Loss
"""

import time
import sys
from datetime import datetime
from typing import Optional, Dict, List, Any
import config
from indicators import compute_ema, compute_supertrend
from bull_engine import BullEngine
from bear_engine import BearEngine
from risk_manager import RiskManager
from binance_client import BinanceFuturesClient

class MultiCoinTradingBot:
    def __init__(
        self,
        dry_run: Optional[bool] = None,
        testnet: Optional[bool] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        risk_pct: Optional[float] = None,
        leverage: Optional[int] = None,
        trade_mode: Optional[str] = None,
    ):
        self.active_pairs = config.ACTIVE_PAIRS
        self.timeframe = config.TIMEFRAME
        self.trade_mode = (trade_mode or getattr(config, "TRADE_MODE", "LONG_ONLY")).upper()
        self.leverage = leverage if leverage is not None else config.LEVERAGE
        self.risk_pct = risk_pct if risk_pct is not None else config.ACCOUNT_RISK_PER_TRADE
        self.max_concurrent = config.MAX_CONCURRENT_POSITIONS

        self.dry_run = dry_run if dry_run is not None else config.DRY_RUN
        self.testnet = testnet if testnet is not None else config.TESTNET
        api_key = api_key if api_key is not None else config.BINANCE_API_KEY
        api_secret = api_secret if api_secret is not None else config.BINANCE_API_SECRET

        self.bull_engine = BullEngine(
            min_confidence=config.MIN_CONFIDENCE_SCORE,
            rr_ratio=config.RISK_REWARD_RATIO,
            atr_sl_mult=config.ATR_SL_MULTIPLIER,
        )
        self.bear_engine = BearEngine(
            min_confidence=config.MIN_CONFIDENCE_SCORE,
            rr_ratio=config.RISK_REWARD_RATIO,
            atr_sl_mult=config.ATR_SL_MULTIPLIER,
        )
        self.risk_manager = RiskManager(
            risk_per_trade_pct=self.risk_pct,
            leverage=self.leverage,
        )
        self.client = BinanceFuturesClient(
            api_key=api_key,
            api_secret=api_secret,
            testnet=self.testnet,
            dry_run=self.dry_run,
            leverage=self.leverage,
        )

        self.active_positions = {}
        self.prev_signals = {name: {"bull": False, "bear": False} for name, _ in self.active_pairs}
        self.closed_trades_history = []

    def initialize(self):
        print("=" * 88)
        print("     MULTI-COIN PORTFOLIO SCANNER: 24 CURATED HIGH-ACCURACY PAIRS     ")
        print("=" * 88)
        print(f"Active Universe:       {len(self.active_pairs)} Pairs (All with >= 40% historical accuracy)")
        print(f"Excluded Toxic Coins:  {', '.join(config.EXCLUDED_COINS)} (< 40% accuracy)")
        print(f"Risk Per Trade:        {self.risk_pct * 100:.1f}% Equity Risk")
        print(f"Max Concurrent Trades: {self.max_concurrent} Positions")
        print(f"Leverage:              {self.leverage}x Isolated")
        print(f"Take Profit / SL:      1:1.5 R:R (3.0x ATR TP) | 2.0x ATR Stop Loss (0.8% - 3.5%)")
        print(f"Macro Gate:            4H Multi-Timeframe Alignment (EMA50 & Supertrend)")
        print(f"Trade Architecture:    {self.trade_mode}")
        mode_str = "DRY-RUN / PAPER TRADING" if self.dry_run else ("BINANCE TESTNET" if self.testnet else "LIVE REAL MONEY")
        print(f"Execution Mode:        {mode_str}")
        print(f"Starting Balance:      ${self.client.fetch_balance():,.2f} USDT")
        print("=" * 88)

    def update_open_positions(self):
        """Monitors open positions, checking if Stop Loss or Take Profit was triggered."""
        if not self.active_positions:
            return

        to_remove = []
        for name, pos in list(self.active_positions.items()):
            sym = pos["symbol"]
            try:
                df_curr = self.client.fetch_ohlcv(sym, timeframe="1h", limit=3)
                current_price = df_curr["close"].iloc[-1]
                candle_high = df_curr["high"].iloc[-1]
                candle_low = df_curr["low"].iloc[-1]
            except Exception:
                continue

            side = pos["side"]
            entry = pos["entry"]
            sl = pos["stop_loss"]
            tp = pos["take_profit"]
            notional = pos["notional"]

            closed = False
            exit_reason = None
            pnl_pct = 0.0

            if side == "BUY":  # LONG
                if candle_high >= tp:
                    closed = True
                    exit_reason = "TAKE_PROFIT"
                    pnl_pct = (tp - entry) / entry
                elif candle_low <= sl:
                    closed = True
                    exit_reason = "STOP_LOSS"
                    pnl_pct = (sl - entry) / entry
            elif side == "SELL":  # SHORT
                if candle_low <= tp:
                    closed = True
                    exit_reason = "TAKE_PROFIT"
                    pnl_pct = (entry - tp) / entry
                elif candle_high >= sl:
                    closed = True
                    exit_reason = "STOP_LOSS"
                    pnl_pct = (entry - sl) / entry

            if closed:
                fee_pct = (config.TAKER_FEE_RATE * 2 + config.SLIPPAGE_RATE * 2)
                net_pnl_usd = notional * (pnl_pct - fee_pct)
                if self.dry_run:
                    self.client.update_paper_balance(net_pnl_usd)

                self.closed_trades_history.append({
                    "name": name,
                    "side": side,
                    "entry": entry,
                    "exit_reason": exit_reason,
                    "pnl_usd": net_pnl_usd,
                })

                color_prefix = "[+]" if net_pnl_usd > 0 else "[-]"
                print(f"\n{color_prefix} [POSITION EXITED: {exit_reason}] {name} ({side}):")
                print(f"    Entry: ${entry:,.4f} | Target: ${tp:,.4f} | Stop: ${sl:,.4f}")
                print(f"    Net Realized PnL: {'+' if net_pnl_usd > 0 else ''}${net_pnl_usd:,.2f} | Current Equity: ${self.client.fetch_balance():,.2f} USDT\n")
                to_remove.append(name)

        for name in to_remove:
            del self.active_positions[name]

    def scan_cycle(self):
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"\n[{timestamp}] --- Starting Multi-Coin Scan Cycle ({len(self.active_pairs)} pairs) ---")
        
        # 1. Update existing open positions
        self.update_open_positions()

        equity = self.client.fetch_balance()
        print(f"Portfolio Equity: ${equity:,.2f} USDT | Open Positions: {len(self.active_positions)} / {self.max_concurrent}")

        for name, sym in self.active_pairs:
            if len(self.active_positions) >= self.max_concurrent:
                print(f"[Portfolio Guard] Max concurrent positions ({self.max_concurrent}) reached. Pausing new entries.")
                break

            if name in self.active_positions:
                continue

            try:
                df_1h = self.client.fetch_ohlcv(sym, timeframe=self.timeframe, limit=config.CANDLE_LIMIT)
            except Exception:
                continue

            if len(df_1h) < 50:
                continue

            # Strict completed-candle evaluation: signals must only trigger on CLOSED candles
            df_1h_closed = df_1h.iloc[:-1]
            current_market_price = df_1h["close"].iloc[-1]

            prev_b = self.prev_signals[name]["bull"]
            prev_s = self.prev_signals[name]["bear"]

            bull_sig = None
            bear_sig = None

            if self.trade_mode in ["LONG_ONLY", "DUAL"]:
                bull_sig = self.bull_engine.analyze(df_1h_closed, prev_confirmed=prev_b)
                self.prev_signals[name]["bull"] = bull_sig.confirmed
            else:
                self.prev_signals[name]["bull"] = False

            if self.trade_mode in ["SHORT_ONLY", "DUAL"]:
                bear_sig = self.bear_engine.analyze(df_1h_closed, prev_confirmed=prev_s)
                self.prev_signals[name]["bear"] = bear_sig.confirmed
            else:
                self.prev_signals[name]["bear"] = False

            action = None
            order_side = None
            chosen_sig = None

            if bull_sig and bull_sig.confirmed and (bear_sig is None or not bear_sig.confirmed) and bull_sig.is_fresh_trigger:
                action = "GO_LONG"
                order_side = "BUY"
                chosen_sig = bull_sig
            elif bear_sig and bear_sig.confirmed and (bull_sig is None or not bull_sig.confirmed) and bear_sig.is_fresh_trigger:
                action = "GO_SHORT"
                order_side = "SELL"
                chosen_sig = bear_sig

            if action is not None:
                # 4H MTF Confluence Gate (evaluated strictly on completed 4H candles)
                if config.ENABLE_MTF_4H:
                    try:
                        df_4h = self.client.fetch_ohlcv(sym, timeframe=config.MTF_TIMEFRAME, limit=100)
                        df_4h_closed = df_4h.iloc[:-1]
                        ema50_4h = compute_ema(df_4h_closed["close"], 50).iloc[-1]
                        st_dir_4h, _ = compute_supertrend(df_4h_closed, 10, 3.0)
                        supertrend_4h = st_dir_4h.iloc[-1]
                        price_4h = df_4h_closed["close"].iloc[-1]

                        if action == "GO_LONG" and (price_4h < ema50_4h or supertrend_4h != 1):
                            print(f"[-] {name}: 1H Long Signal vetoed by 4H MTF Gate (Completed 4H Price ${price_4h:.2f} < EMA50 ${ema50_4h:.2f} or ST != 1)")
                            continue
                        elif action == "GO_SHORT" and (price_4h > ema50_4h or supertrend_4h != -1):
                            print(f"[-] {name}: 1H Short Signal vetoed by 4H MTF Gate (Completed 4H Price ${price_4h:.2f} > EMA50 ${ema50_4h:.2f} or ST != -1)")
                            continue
                    except Exception:
                        continue

                # Position Sizing: Use real-time current market price for actual execution
                prec = self.client.get_market_precision(sym)
                pos = self.risk_manager.calculate_position(
                    account_equity=equity,
                    side=order_side,
                    entry_price=current_market_price,
                    stop_loss=chosen_sig.stop_loss,
                    take_profit=chosen_sig.take_profit,
                    min_qty=prec["min_qty"],
                    step_size=prec["step_size"],
                    min_notional=prec["min_notional"],
                )

                if pos.is_valid:
                    print(f"\n>>> [SIGNAL EXECUTED] {name} ({order_side}): Entry ${pos.entry_price:,.4f} | SL ${pos.stop_loss:,.4f} | TP ${pos.take_profit:,.4f}")
                    print(f"    Allocated Notional: ${pos.notional_usd:,.2f} | Risk at Stop: ${pos.risk_usd:,.2f} ({pos.risk_pct_actual:.2f}%)")
                    self.client.execute_bracket_order(sym, order_side, pos.quantity, pos.stop_loss, pos.take_profit)
                    self.active_positions[name] = {
                        "symbol": sym,
                        "side": order_side,
                        "entry": pos.entry_price,
                        "stop_loss": pos.stop_loss,
                        "take_profit": pos.take_profit,
                        "quantity": pos.quantity,
                        "notional": pos.notional_usd,
                        "risk_usd": pos.risk_usd,
                        "timestamp": timestamp,
                    }

        print(f"[{timestamp}] Scan complete across all {len(self.active_pairs)} pairs.")

    def scan_once(self):
        """Scans all 24 curated pairs once, printing a comprehensive signal and market status matrix."""
        self.initialize()
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"\n[{timestamp}] --- Single Scan Pass: Multi-Coin Confluence Matrix ---")
        print(f"{'Asset':<8} {'Price ($)':<12} {'Bull Score':<12} {'Bear Score':<12} {'4H Macro':<12} {'Trigger':<16} {'Action'}")
        print("-" * 88)

        opportunities = []

        for name, sym in self.active_pairs:
            try:
                df_1h = self.client.fetch_ohlcv(sym, timeframe=self.timeframe, limit=config.CANDLE_LIMIT)
                df_4h = self.client.fetch_ohlcv(sym, timeframe=config.MTF_TIMEFRAME, limit=100)
            except Exception as e:
                print(f"{name:<8} [Data Error: {e}]")
                continue

            df_1h_closed = df_1h.iloc[:-1]
            df_4h_closed = df_4h.iloc[:-1]
            curr_price = df_1h["close"].iloc[-1]
            ema50_4h = compute_ema(df_4h_closed["close"], 50).iloc[-1]
            st_dir_4h, _ = compute_supertrend(df_4h_closed, 10, 3.0)
            st_4h = st_dir_4h.iloc[-1]
            p_4h = df_4h_closed["close"].iloc[-1]

            mtf_status = "NEUTRAL"
            if p_4h > ema50_4h and st_4h == 1:
                mtf_status = "BULLISH"
            elif p_4h < ema50_4h and st_4h == -1:
                mtf_status = "BEARISH"

            bull_sig = self.bull_engine.analyze(df_1h_closed)
            bear_sig = self.bear_engine.analyze(df_1h_closed)

            trigger_str = "None"
            action_str = "STAND_BY"

            if bull_sig.confirmed and not bear_sig.confirmed:
                if mtf_status == "BULLISH":
                    action_str = "READY (LONG)"
                    trigger_str = "Bull Confluence"
                    opportunities.append((name, "LONG", curr_price, bull_sig.stop_loss, bull_sig.take_profit, bull_sig.score))
                else:
                    action_str = "MTF VETO"
                    trigger_str = "Bull / 4H Bear"
            elif bear_sig.confirmed and not bull_sig.confirmed:
                if mtf_status == "BEARISH":
                    action_str = "READY (SHORT)"
                    trigger_str = "Bear Confluence"
                    opportunities.append((name, "SHORT", curr_price, bear_sig.stop_loss, bear_sig.take_profit, bear_sig.score))
                else:
                    action_str = "MTF VETO"
                    trigger_str = "Bear / 4H Bull"
            elif bull_sig.confirmed and bear_sig.confirmed:
                action_str = "CONFLICT"
                trigger_str = "Both Engines"

            price_fmt = f"${curr_price:,.4f}" if curr_price < 10 else f"${curr_price:,.2f}"
            print(f"{name:<8} {price_fmt:<12} {bull_sig.score:>5.1f}%{' [CONF]' if bull_sig.confirmed else '      '} {bear_sig.score:>5.1f}%{' [CONF]' if bear_sig.confirmed else '      '} {mtf_status:<12} {trigger_str:<16} {action_str}")

        print("=" * 88)
        if opportunities:
            print(f">>> Found {len(opportunities)} Valid Confluence Setup(s):")
            for opp in opportunities:
                print(f"    * {opp[0]} ({opp[1]}): Current ${opp[2]:,.4f} | SL ${opp[3]:,.4f} | TP ${opp[4]:,.4f} (Confidence: {opp[5]:.1f}%)")
        else:
            print(">>> No pairs currently satisfy >= 75% confluence + 4H MTF gate. Capital fully protected in cash.")
        print("=" * 88)

    def start(self, once: bool = False):
        if once:
            self.scan_once()
            return

        self.initialize()
        print(f"\nMulti-coin scanner active. Polling every {config.POLL_INTERVAL_SECONDS}s. Press Ctrl+C to terminate.")
        try:
            while True:
                self.scan_cycle()
                time.sleep(config.POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("\nScanner safely stopped.")

if __name__ == "__main__":
    once_mode = "--once" in sys.argv
    bot = MultiCoinTradingBot()
    bot.start(once=once_mode)
