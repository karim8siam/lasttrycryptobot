"""
indicators.py - Technical indicator calculation engine for Binance Futures.
Uses numpy and pandas for vectorised, high-performance calculations.
"""

import numpy as np
import pandas as pd


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Compute Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average True Range (ATR)."""
    high = df['high']
    low = df['low']
    close = df['close']
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(window=period).mean()
    # Fill initial NaNs with wilder smoothing
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return atr


def compute_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    """
    Compute Supertrend indicator.
    Returns:
        direction: Series of 1 (Bullish/Up) or -1 (Bearish/Down)
        supertrend: Series of supertrend line values
    """
    atr = compute_atr(df, period)
    hl2 = (df['high'] + df['low']) / 2.0
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)

    supertrend = pd.Series(index=df.index, dtype='float64')
    direction = pd.Series(index=df.index, dtype='int64')

    close = df['close'].values
    upper = upperband.values
    lower = lowerband.values

    in_uptrend = True
    st_val = lower[0] if len(lower) > 0 else 0.0

    st_arr = np.zeros(len(df))
    dir_arr = np.zeros(len(df), dtype=int)

    for i in range(len(df)):
        if i == 0:
            st_arr[i] = lower[i]
            dir_arr[i] = 1
            continue

        c = close[i]
        curr_upper = upper[i]
        curr_lower = lower[i]
        prev_st = st_arr[i - 1]
        prev_dir = dir_arr[i - 1]

        if prev_dir == 1:
            # Uptrend
            curr_lower = max(curr_lower, prev_st)
            if c < curr_lower:
                in_uptrend = False
                st_val = curr_upper
                dir_val = -1
            else:
                st_val = curr_lower
                dir_val = 1
        else:
            # Downtrend
            curr_upper = min(curr_upper, prev_st)
            if c > curr_upper:
                in_uptrend = True
                st_val = curr_lower
                dir_val = 1
            else:
                st_val = curr_upper
                dir_val = -1

        st_arr[i] = st_val
        dir_arr[i] = dir_val

    df_out = pd.DataFrame(index=df.index)
    df_out['supertrend'] = st_arr
    df_out['direction'] = dir_arr
    return df_out['direction'], df_out['supertrend']


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute Relative Strength Index (RSI)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """
    Compute MACD line, Signal line, and Histogram.
    """
    ema_fast = compute_ema(series, fast)
    ema_slow = compute_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_adx(df: pd.DataFrame, period: int = 14):
    """
    Compute Average Directional Index (ADX), +DI, and -DI.
    """
    high = df['high']
    low = df['low']
    close = df['close']

    tr = compute_atr(df, period)

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)

    plus_dm = pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean()
    minus_dm = pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean()

    plus_di = 100 * (plus_dm / (tr + 1e-10))
    minus_di = 100 * (minus_dm / (tr + 1e-10))

    dx = 100 * ((plus_di - minus_di).abs() / ((plus_di + minus_di) + 1e-10))
    adx = dx.ewm(alpha=1.0 / period, adjust=False).mean()

    return adx, plus_di, minus_di


def compute_vwap(df: pd.DataFrame, window: int = 24) -> pd.Series:
    """
    Compute Rolling 24-period Volume Weighted Average Price (VWAP).
    Accurately represents the daily institutional volume benchmark on hourly/intraday charts.
    """
    typical_price = (df['high'] + df['low'] + df['close']) / 3.0
    vol = df['volume']
    pv = typical_price * vol
    rolling_pv = pv.rolling(window=window, min_periods=1).sum()
    rolling_vol = vol.rolling(window=window, min_periods=1).sum()
    return rolling_pv / (rolling_vol + 1e-10)


def compute_obv(df: pd.DataFrame, ema_period: int = 20):
    """
    Compute On-Balance Volume (OBV) and its smoothing EMA.
    """
    close = df['close']
    vol = df['volume']
    direction = np.where(close > close.shift(1), 1, np.where(close < close.shift(1), -1, 0))
    obv = (vol * direction).cumsum()
    obv_ema = compute_ema(obv, ema_period)
    return obv, obv_ema


def compute_confirmed_swings(df: pd.DataFrame):
    """
    Candidate Rule R017: Structural 5-bar Fractal Swings.
    A swing high at bar k is confirmed at bar k+2 if:
      high[k] > high[k-1] and high[k] > high[k-2] and high[k] > high[k+1] and high[k] > high[k+2]
    A swing low at bar k is confirmed at bar k+2 if:
      low[k] < low[k-1] and low[k] < low[k-2] and low[k] < low[k+1] and low[k] < low[k+2]
    Strict zero lookahead: for any candle t, returns the latest confirmed swing pivot established at or before t.
    """
    n = len(df)
    highs = df['high'].values
    lows = df['low'].values

    latest_sh = np.full(n, np.nan)
    latest_sl = np.full(n, np.nan)

    curr_sh = np.nan
    curr_sl = np.nan

    for t in range(4, n):
        k = t - 2
        if (highs[k] > highs[k-1] and highs[k] > highs[k-2] and
            highs[k] > highs[k+1] and highs[k] > highs[k+2]):
            curr_sh = highs[k]

        if (lows[k] < lows[k-1] and lows[k] < lows[k-2] and
            lows[k] < lows[k+1] and lows[k] < lows[k+2]):
            curr_sl = lows[k]

        latest_sh[t] = curr_sh
        latest_sl[t] = curr_sl

    return pd.Series(latest_sh, index=df.index), pd.Series(latest_sl, index=df.index)


def compute_rejection_candles(df: pd.DataFrame):
    """
    Hammer / Shooting-Star Rejection Candles:
    - Hammer: After 3 declining closes (close[t-3] > close[t-2] > close[t-1]), candle t has:
        lower_wick >= 2.0 * body AND close >= high - (high - low)/3.0
    - Shooting-Star: After 3 rising closes (close[t-3] < close[t-2] < close[t-1]), candle t has:
        upper_wick >= 2.0 * body AND close <= low + (high - low)/3.0
    Returns:
        (is_hammer_series, is_shooting_star_series) of booleans.
    """
    n = len(df)
    c_vals = df['close'].values
    o_vals = df['open'].values
    h_vals = df['high'].values
    l_vals = df['low'].values

    is_hammer = np.zeros(n, dtype=bool)
    is_shooting_star = np.zeros(n, dtype=bool)

    for i in range(3, n):
        three_declining = (c_vals[i-3] > c_vals[i-2]) and (c_vals[i-2] > c_vals[i-1])
        three_rising = (c_vals[i-3] < c_vals[i-2]) and (c_vals[i-2] < c_vals[i-1])

        rng = h_vals[i] - l_vals[i]
        if rng <= 0:
            continue

        body = abs(c_vals[i] - o_vals[i])
        body_safe = max(body, rng * 0.05)

        lower_wick = min(c_vals[i], o_vals[i]) - l_vals[i]
        upper_wick = h_vals[i] - max(c_vals[i], o_vals[i])

        if three_declining and (lower_wick >= 2.0 * body_safe) and (c_vals[i] >= h_vals[i] - (rng / 3.0)):
            is_hammer[i] = True

        if three_rising and (upper_wick >= 2.0 * body_safe) and (c_vals[i] <= l_vals[i] + (rng / 3.0)):
            is_shooting_star[i] = True

    return pd.Series(is_hammer, index=df.index), pd.Series(is_shooting_star, index=df.index)

