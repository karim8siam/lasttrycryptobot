"""
binance_client.py - Binance USDT-M Futures Execution Interface via CCXT.
Supports Live Trading, Testnet Sandbox, and Dry-Run (Paper Trading) Mode.
"""

import time
import ccxt
from typing import Dict, Any, List, Optional
import pandas as pd


class BinanceFuturesClient:
    """
    Robust Binance Futures Client using CCXT.
    Enforces 5x leverage, isolated margin mode, and bracket order placement.
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = True,
        dry_run: bool = True,
        leverage: int = 5,
    ):
        self.testnet = testnet
        self.dry_run = dry_run
        self.leverage = leverage
        self.exchange = None
        self.paper_balance = 1000.0  # $1,000 USDT virtual starting capital

        if not self.dry_run and api_key and api_secret:
            self.exchange = ccxt.binance({
                'apiKey': api_key,
                'secret': api_secret,
                'options': {
                    'defaultType': 'future',
                    'adjustForTimeDifference': True,
                },
            })
            if self.testnet:
                self.exchange.set_sandbox_mode(True)
        else:
            # Public market data client (no auth needed for dry-run/paper trading)
            self.exchange = ccxt.binance({
                'options': {'defaultType': 'future'},
            })

    def fetch_ohlcv(self, symbol: str, timeframe: str = '15m', limit: int = 200) -> pd.DataFrame:
        """Fetch historical candlestick data from Binance Futures."""
        formatted_symbol = symbol.replace("/", "").upper() if "/" not in symbol else symbol
        raw = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('datetime', inplace=True)
        return df

    def get_market_precision(self, symbol: str) -> Dict[str, float]:
        """Fetch minimum quantity, stepSize, and tickSize for the symbol."""
        try:
            self.exchange.load_markets()
            market = self.exchange.market(symbol)
            min_qty = market['limits']['amount']['min'] or 0.001
            step_size = market['precision']['amount'] or 0.001
            # In ccxt, precision can be an integer number of decimal places or float
            if isinstance(step_size, int):
                step_size = 10 ** (-step_size)
            return {
                'min_qty': float(min_qty),
                'step_size': float(step_size),
                'min_notional': 5.0,
            }
        except Exception:
            return {'min_qty': 0.001, 'step_size': 0.001, 'min_notional': 5.0}

    def configure_margin_and_leverage(self, symbol: str):
        """Configure Isolated Margin and 5x Leverage on Binance Futures."""
        if self.dry_run or not self.exchange.apiKey:
            print(f"[Paper/DryRun] Configured {symbol}: Isolated Margin, {self.leverage}x Leverage.")
            return

        try:
            # Set Margin Mode to ISOLATED
            try:
                self.exchange.set_margin_mode('ISOLATED', symbol)
                print(f"Margin mode set to ISOLATED for {symbol}")
            except Exception as e:
                # Often already isolated or exchange-specific warning
                pass

            # Set Leverage
            self.exchange.set_leverage(self.leverage, symbol)
            print(f"Leverage set to {self.leverage}x for {symbol}")
        except Exception as e:
            print(f"Notice setting leverage/margin: {e}")

    def fetch_balance(self) -> float:
        """Fetch available USDT Futures balance."""
        if self.dry_run or not self.exchange.apiKey:
            return self.paper_balance

        try:
            balance = self.exchange.fetch_balance(params={'type': 'future'})
            return float(balance['total'].get('USDT', 0.0))
        except Exception as e:
            print(f"Error fetching balance: {e}")
            return 0.0

    def update_paper_balance(self, delta_usd: float):
        """Update simulated paper wallet balance with realized PnL."""
        self.paper_balance += delta_usd

    def execute_bracket_order(
        self,
        symbol: str,
        side: str,  # 'BUY' or 'SELL'
        quantity: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> Dict[str, Any]:
        """
        Executes a primary entry order along with Stop Loss and Take Profit orders.
        """
        if self.dry_run:
            print("\n================= [SIMULATED EXECUTION] =================")
            print(f"Symbol:        {symbol}")
            print(f"Direction:     {'LONG' if side == 'BUY' else 'SHORT'}")
            print(f"Order Size:    {quantity}")
            print(f"Stop Loss:     ${stop_loss_price:.4f}")
            print(f"Take Profit:   ${take_profit_price:.4f}")
            print("Status:        Simulated Fill (Dry Run)")
            print("========================================================\n")
            return {
                'status': 'SIMULATED_FILLED',
                'orderId': f"dry_run_{int(time.time())}",
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'stop_loss': stop_loss_price,
                'take_profit': take_profit_price,
            }

        try:
            # 1. Market Entry Order
            entry_order = self.exchange.create_order(
                symbol=symbol,
                type='market',
                side=side.lower(),
                amount=quantity,
            )
            print(f"Entry order filled: ID {entry_order['id']}")

            # Opposite side for exit orders
            exit_side = 'sell' if side.upper() == 'BUY' else 'buy'

            # 2. Stop Loss Order (STOP_MARKET)
            sl_order = self.exchange.create_order(
                symbol=symbol,
                type='STOP_MARKET',
                side=exit_side,
                amount=quantity,
                params={
                    'stopPrice': stop_loss_price,
                    'reduceOnly': True,
                },
            )
            print(f"Stop-Loss order placed at ${stop_loss_price:.4f}: ID {sl_order['id']}")

            # 3. Take Profit Order (TAKE_PROFIT_MARKET)
            tp_order = self.exchange.create_order(
                symbol=symbol,
                type='TAKE_PROFIT_MARKET',
                side=exit_side,
                amount=quantity,
                params={
                    'stopPrice': take_profit_price,
                    'reduceOnly': True,
                },
            )
            print(f"Take-Profit order placed at ${take_profit_price:.4f}: ID {tp_order['id']}")

            return {
                'status': 'FILLED',
                'entry': entry_order,
                'stop_loss': sl_order,
                'take_profit': tp_order,
            }
        except Exception as e:
            print(f"Error executing bracket order on Binance Futures: {e}")
            return {'status': 'ERROR', 'error': str(e)}
