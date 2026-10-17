"""
config.py - Production Configuration for Binance Futures Dual-Engine Trading Bot.
Strict Base Engine Rules:
- 1:1.5 Risk-to-Reward Ratio (Take Profit)
- 2.0x ATR Stop Loss
- 4H Multi-Timeframe Confluence Gate
- 1.0% Capital Risk Per Trade (Compounding)
- 5x Isolated Leverage
- Curated High-Accuracy Universe (Removed coins with < 40% accuracy)
"""

# Binance API Credentials (Leave empty for Paper Trading / Dry-Run Mode)
BINANCE_API_KEY = ""
BINANCE_API_SECRET = ""

# Mode settings
TESTNET = True     # Use Binance Futures Sandbox/Testnet if True
DRY_RUN = True     # Paper trading mode (no real money risked, real market data used)

# Active Curated Coin Universe (Top 24 verified high-accuracy pairs >= 40%)
ACTIVE_PAIRS = [
    ("SOL", "SOL/USDT"),
    ("SHIB", "1000SHIB/USDT:USDT"),
    ("DOGE", "DOGE/USDT"),
    ("TAO", "TAO/USDT"),
    ("ADA", "ADA/USDT"),
    ("FET", "FET/USDT"),
    ("UNI", "UNI/USDT"),
    ("RENDER", "RENDER/USDT"),
    ("AVAX", "AVAX/USDT"),
    ("SUI", "SUI/USDT"),
    ("ENA", "ENA/USDT"),
    ("BTC", "BTC/USDT"),
    ("XRP", "XRP/USDT"),
    ("NEAR", "NEAR/USDT"),
    ("INJ", "INJ/USDT"),
    ("LTC", "LTC/USDT"),
    ("WLD", "WLD/USDT"),
    ("APT", "APT/USDT"),
    ("BNB", "BNB/USDT"),
    ("SEI", "SEI/USDT"),
    ("ATOM", "ATOM/USDT"),
    ("LINK", "LINK/USDT"),
    ("OP", "OP/USDT"),
    ("ETH", "ETH/USDT"),
]

# Blacklisted Coins (Removed due to < 40% historical accuracy / chop drag)
EXCLUDED_COINS = ["ARB", "DOT", "PEPE", "FIL", "AAVE", "TIA"]

# Primary / Default Pair for single-pair runners
SYMBOL = "SOL/USDT"     # Default top-performing asset (65.0% historical win rate)
TIMEFRAME = "1h"        # 1-hour primary execution timeframe
CANDLE_LIMIT = 250      # Historical candles to fetch for indicator stability

# Risk & Leverage Management
ACCOUNT_RISK_PER_TRADE = 0.01  # 1.0% of total account balance per trade
LEVERAGE = 5                   # 5x Leverage
MARGIN_MODE = "ISOLATED"       # Isolated margin to protect account from cross-liquidation
MAX_CONCURRENT_POSITIONS = 5   # Max simultaneous open positions for portfolio safety

# Base Engine Confirmation Thresholds
MIN_CONFIDENCE_SCORE = 75.0    # 75% minimum multi-factor confirmation required
RISK_REWARD_RATIO = 1.5        # Strict 1:1.5 Risk-to-Reward Ratio (3.0x ATR TP)
ATR_SL_MULTIPLIER = 2.0        # Strict 2.0x ATR Stop Loss
ENABLE_MTF_4H = True           # 4H Macro Trend Confluence Gate (4H Close vs EMA50 & Supertrend)
MTF_TIMEFRAME = "4h"           # Higher timeframe for trend alignment

# Execution Friction & Realism Parameters
TAKER_FEE_RATE = 0.0005        # 0.05% Binance VIP 0 taker fee
SLIPPAGE_RATE = 0.0002         # 0.02% realistic slippage
COOLDOWN_BARS = 2              # Minimum bars to wait after trade exit before re-entering

# Bot Polling Interval
POLL_INTERVAL_SECONDS = 60     # Polling interval in seconds
