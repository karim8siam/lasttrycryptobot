"""
bot.py - Dual-Engine Algorithmic Trading Bot for Binance Futures.
Coordinates Bull Engine (Upward) and Bear Engine (Downward) with 1% risk & 5x leverage.
"""

import sys
import time
from datetime import datetime
from typing import Optional, Dict, Any
import config
from indicators import compute_ema, compute_supertrend
from bull_engine import BullEngine
from bear_engine import BearEngine
from risk_manager import RiskManager
from binance_client import BinanceFuturesClient


class DualEngineTradingBot:
    def __init__(
        self,
        symbol: Optional[str] = None,
        dry_run: Optional[bool] = None,
        testnet: Optional[bool] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        risk_pct: Optional[float] = None,
        leverage: Optional[int] = None,
        trade_mode: Optional[str] = None,
    ):
        self.symbol = symbol if symbol is not None else config.SYMBOL
        self.timeframe = config.TIMEFRAME
        self.trade_mode = (trade_mode or getattr(config, "TRADE_MODE", "LONG_ONLY")).upper()
        self.leverage = leverage if leverage is not None else config.LEVERAGE
        self.risk_pct = risk_pct if risk_pct is not None else config.ACCOUNT_RISK_PER_TRADE

        self.dry_run = dry_run if dry_run is not None else config.DRY_RUN
        self.testnet = testnet if testnet is not None else config.TESTNET
        api_key = api_key if api_key is not None else config.BINANCE_API_KEY
        api_secret = api_secret if api_secret is not None else config.BINANCE_API_SECRET

        # Initialize Engines
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

        # Active trade state tracker
        self.active_position = None
        self.prev_bull_confirmed = False
        self.prev_bear_confirmed = False

    def initialize(self):
        print("=" * 65)
        print("  BINANCE FUTURES DUAL-ENGINE ALGORITHMIC TRADING SYSTEM  ")
        print("=" * 65)
        print(f"Trading Pair:      {self.symbol}")
        print(f"Timeframe:         {self.timeframe}")
        print(f"Leverage:          {self.leverage}x (Isolated)")
        print(f"Risk Per Trade:    {self.risk_pct * 100:.1f}% of total account equity")
        print(f"Engine 1 (Bull):   Threshold >= {config.MIN_CONFIDENCE_SCORE}% (Upward Confirmation)")
        print(f"Engine 2 (Bear):   Threshold >= {config.MIN_CONFIDENCE_SCORE}% (Downward Confirmation)")
        mode_str = "DRY-RUN / PAPER TRADING" if self.dry_run else ("TESTNET" if self.testnet else "LIVE REAL MONEY")
        print(f"Execution Mode:    {mode_str}")
        print(f"Account Balance:   ${self.client.fetch_balance():,.2f} USDT")
        print("=" * 65)

        self.client.configure_margin_and_leverage(self.symbol)

    def run_cycle(self):
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"\n[{timestamp}] --- Fetching Binance Futures Market Data ---")

        # 1. Fetch live candles
        try:
            df = self.client.fetch_ohlcv(self.symbol, timeframe=self.timeframe, limit=config.CANDLE_LIMIT)
        except Exception as e:
            print(f"Failed to fetch market data: {e}")
            return

        if len(df) < 50:
            print("Insufficient candle data fetched. Standing down.")
            return

        # Separate completed candles from active forming candle
        df_closed = df.iloc[:-1]
        current_price = df['close'].iloc[-1]
        c_high = df['high'].iloc[-1]
        c_low = df['low'].iloc[-1]
        print(f"Current Price ({self.symbol}): ${current_price:,.4f}")

        # Check Active Position for Exit (Take Profit / Stop Loss)
        if self.active_position is not None:
            side = self.active_position['side']
            entry = self.active_position['entry']
            sl = self.active_position['stop_loss']
            tp = self.active_position['take_profit']
            notional = self.active_position.get('notional', 0.0)

            closed = False
            exit_reason = None
            pnl_pct = 0.0

            if side == "BUY":
                if c_high >= tp:
                    closed = True
                    exit_reason = "TAKE_PROFIT"
                    pnl_pct = (tp - entry) / entry
                elif c_low <= sl:
                    closed = True
                    exit_reason = "STOP_LOSS"
                    pnl_pct = (sl - entry) / entry
            elif side == "SELL":
                if c_low <= tp:
                    closed = True
                    exit_reason = "TAKE_PROFIT"
                    pnl_pct = (entry - tp) / entry
                elif c_high >= sl:
                    closed = True
                    exit_reason = "STOP_LOSS"
                    pnl_pct = (entry - sl) / entry

            if closed:
                fee_pct = (config.TAKER_FEE_RATE * 2 + config.SLIPPAGE_RATE * 2)
                net_pnl_usd = notional * (pnl_pct - fee_pct) if notional > 0 else 0.0
                if self.dry_run:
                    self.client.update_paper_balance(net_pnl_usd)

                print(f"\n>>> [POSITION EXITED: {exit_reason}] {self.symbol} ({side}):")
                print(f"    Entry: ${entry:,.4f} | Target: ${tp:,.4f} | Stop: ${sl:,.4f}")
                print(f"    Net Realized PnL: {'+' if net_pnl_usd > 0 else ''}${net_pnl_usd:,.2f} | Current Equity: ${self.client.fetch_balance():,.2f} USDT\n")
                self.active_position = None
            else:
                print(f">>> POSITION ACTIVE ({side} @ ${entry:,.4f}). Monitoring exits: SL ${sl:,.4f} | TP ${tp:,.4f}.")
                return

        # 2. Run Engine 1: Bull Confirmation Engine (Upward) on completed candles
        if self.trade_mode in ["LONG_ONLY", "DUAL"]:
            bull_signal = self.bull_engine.analyze(df_closed, prev_confirmed=self.prev_bull_confirmed)
            self.prev_bull_confirmed = bull_signal.confirmed
        else:
            from bull_engine import BullSignal
            bull_signal = BullSignal(confirmed=False, score=0.0, entry_price=current_price, stop_loss=0.0, take_profit=0.0, risk_reward_ratio=1.5, reasons=["Engine disabled by TRADE_MODE"])
            self.prev_bull_confirmed = False

        # 3. Run Engine 2: Bear Confirmation Engine (Downward) on completed candles
        if self.trade_mode in ["SHORT_ONLY", "DUAL"]:
            bear_signal = self.bear_engine.analyze(df_closed, prev_confirmed=self.prev_bear_confirmed)
            self.prev_bear_confirmed = bear_signal.confirmed
        else:
            from bear_engine import BearSignal
            bear_signal = BearSignal(confirmed=False, score=0.0, entry_price=current_price, stop_loss=0.0, take_profit=0.0, risk_reward_ratio=1.5, reasons=["Engine disabled by TRADE_MODE"])
            self.prev_bear_confirmed = False

        print("-" * 55)
        print(f"ENGINE 1 (UPWARD CONFIRMATION):   Score: {bull_signal.score:5.1f}% | Confirmed: {bull_signal.confirmed} | Fresh: {bull_signal.is_fresh_trigger}")
        for r in bull_signal.reasons:
            print(f"   [+] {r}")

        print("-" * 55)
        print(f"ENGINE 2 (DOWNWARD CONFIRMATION): Score: {bear_signal.score:5.1f}% | Confirmed: {bear_signal.confirmed} | Fresh: {bear_signal.is_fresh_trigger}")
        for r in bear_signal.reasons:
            print(f"   [-] {r}")
        print("-" * 55)

        # 4. Arbitration & Decision Gate
        if self.active_position is not None:
            print(f">>> POSITION ACTIVE ({self.active_position['side']} @ ${self.active_position['entry']:,.2f}). Monitoring exits.")
            return

        action = None
        chosen_signal = None
        order_side = None

        if bull_signal.confirmed and not bear_signal.confirmed:
            if not bull_signal.is_fresh_trigger:
                print(">>> BULL SIGNAL ACTIVE, BUT NOT A FRESH TRIGGER (Already in progress). Standing down.")
                return
            action = "GO_LONG"
            chosen_signal = bull_signal
            order_side = "BUY"
            print(">>> VERDICT: FRESH UPWARD CONFLUENCE DETECTED -> PROCEED TO LONG")
        elif bear_signal.confirmed and not bull_signal.confirmed:
            if not bear_signal.is_fresh_trigger:
                print(">>> BEAR SIGNAL ACTIVE, BUT NOT A FRESH TRIGGER (Already in progress). Standing down.")
                return
            action = "GO_SHORT"
            chosen_signal = bear_signal
            order_side = "SELL"
            print(">>> VERDICT: FRESH DOWNWARD CONFLUENCE DETECTED -> PROCEED TO SHORT")
        elif bull_signal.confirmed and bear_signal.confirmed:
            print(">>> VERDICT: CONFLICT - Both engines triggered. Stand down to preserve capital.")
            return
        else:
            print(">>> VERDICT: NO EDGE / MARKET IN CHOP. Both engines say NO. Preserving capital.")
            return

        # 4.5. Multi-Timeframe (4H) Trend Confluence Gate (evaluated strictly on completed 4H candle)
        if getattr(config, "ENABLE_MTF_4H", False):
            try:
                df_4h = self.client.fetch_ohlcv(self.symbol, timeframe=config.MTF_TIMEFRAME, limit=100)
                df_4h_closed = df_4h.iloc[:-1]
                ema50_4h = compute_ema(df_4h_closed['close'], 50).iloc[-1]
                st_dir_4h, _ = compute_supertrend(df_4h_closed, 10, 3.0)
                supertrend_4h = st_dir_4h.iloc[-1]
                price_4h = df_4h_closed['close'].iloc[-1]

                if action == "GO_LONG":
                    if price_4h < ema50_4h or supertrend_4h != 1:
                        print(f">>> [MTF 4H VETO]: 1H Long Signal REJECTED. Completed 4H Macro Trend is not aligned (Price: ${price_4h:,.2f}, 4H EMA50: ${ema50_4h:,.2f}, 4H Supertrend: {supertrend_4h}).")
                        return
                    else:
                        print(f">>> [MTF 4H CONFLUENCE CONFIRMED]: 4H Macro Trend is BULLISH (Price > EMA50 and Supertrend Green).")
                elif action == "GO_SHORT":
                    if price_4h > ema50_4h or supertrend_4h != -1:
                        print(f">>> [MTF 4H VETO]: 1H Short Signal REJECTED. Completed 4H Macro Trend is not aligned (Price: ${price_4h:,.2f}, 4H EMA50: ${ema50_4h:,.2f}, 4H Supertrend: {supertrend_4h}).")
                        return
                    else:
                        print(f">>> [MTF 4H CONFLUENCE CONFIRMED]: 4H Macro Trend is BEARISH (Price < EMA50 and Supertrend Red).")
            except Exception as e:
                print(f"[MTF Warning]: Could not fetch 4H data for confluence verification: {e}. Proceeding with caution.")

        # 5. Position Sizing & Strict 1% Risk Allocation
        account_equity = self.client.fetch_balance()
        precisions = self.client.get_market_precision(self.symbol)

        position_calc = self.risk_manager.calculate_position(
            account_equity=account_equity,
            side=order_side,
            entry_price=current_price,
            stop_loss=chosen_signal.stop_loss,
            take_profit=chosen_signal.take_profit,
            min_qty=precisions['min_qty'],
            step_size=precisions['step_size'],
            min_notional=precisions['min_notional'],
        )

        print("\n--- RISK MANAGEMENT AUDIT ---")
        print(f"Account Balance:        ${account_equity:,.2f} USDT")
        print(f"Target Max Risk (1%):   ${account_equity * self.risk_pct:,.2f} USDT")
        print(f"Order Side:             {order_side}")
        print(f"Entry Price:            ${position_calc.entry_price:,.2f}")
        print(f"Stop Loss:              ${position_calc.stop_loss:,.2f}")
        print(f"Take Profit:            ${position_calc.take_profit:,.2f}")
        print(f"Calculated Contracts:   {position_calc.quantity} {self.symbol.split('/')[0]}")
        print(f"Notional Position:      ${position_calc.notional_usd:,.2f} USDT")
        print(f"Margin Allocated (5x):  ${position_calc.margin_required:,.2f} USDT")
        print(f"Risk at Stop Loss:      ${position_calc.risk_usd:,.2f} USDT ({position_calc.risk_pct_actual:.2f}% of Equity)")
        print(f"Est. Liquidation Price: ${position_calc.estimated_liquidation_price:,.2f}")

        if not position_calc.is_valid:
            print(f"[REJECTED BY RISK ENGINE]: {position_calc.error_message}")
            return

        # 6. Execution via Binance Client
        execution_res = self.client.execute_bracket_order(
            symbol=self.symbol,
            side=order_side,
            quantity=position_calc.quantity,
            stop_loss_price=position_calc.stop_loss,
            take_profit_price=position_calc.take_profit,
        )

        self.active_position = {
            'side': order_side,
            'quantity': position_calc.quantity,
            'entry': position_calc.entry_price,
            'stop_loss': position_calc.stop_loss,
            'take_profit': position_calc.take_profit,
            'notional': position_calc.notional_usd,
            'timestamp': timestamp,
        }

    def start(self, once: bool = False):
        self.initialize()
        if once:
            self.run_cycle()
            return

        print(f"Bot started. Polling every {config.POLL_INTERVAL_SECONDS} seconds. Press Ctrl+C to terminate.")
        try:
            while True:
                self.run_cycle()
                time.sleep(config.POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("\nBot terminated safely by user.")


if __name__ == "__main__":
    once_mode = "--once" in sys.argv
    bot = DualEngineTradingBot()
    bot.start(once=once_mode)
