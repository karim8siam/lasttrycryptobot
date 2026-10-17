"""
bull_engine.py - Engine 1: Dedicated Upward Confirmation Engine (Bull Engine)
Filters and confirms high-probability LONG setups with multi-factor confluence.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
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


@dataclass
class BullSignal:
    confirmed: bool
    score: float  # 0.0 to 100.0%
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward_ratio: float
    is_fresh_trigger: bool = False
    reasons: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)


class BullEngine:
    """
    Dedicated Upward Confirmation Engine.
    Requires at least 75% weighted confluence score across:
    1. Trend & Regime (EMA 50/200, Supertrend)
    2. Trend Strength (ADX, +DI > -DI)
    3. Volume & Flow (VWAP, OBV accumulation, Volume expansion)
    4. Momentum Health (RSI sweet spot 48-68, MACD positive acceleration)
    """

    def __init__(self, min_confidence: float = 75.0, rr_ratio: float = 1.5, atr_sl_mult: float = 2.0):
        self.min_confidence = min_confidence
        self.rr_ratio = rr_ratio
        self.atr_sl_mult = atr_sl_mult

    def analyze(self, df: pd.DataFrame, df_4h: Optional[pd.DataFrame] = None, prev_confirmed: bool = False) -> BullSignal:
        if len(df) < 50:
            return BullSignal(
                confirmed=False,
                score=0.0,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                risk_reward_ratio=self.rr_ratio,
                is_fresh_trigger=False,
                reasons=["Insufficient candle history"],
            )

        # 1. Compute Indicators
        close = df['close']
        high = df['high']
        low = df['low']
        vol = df['volume']

        current_price = close.iloc[-1]
        atr_series = compute_atr(df, 14)
        current_atr = atr_series.iloc[-1]

        # 4H Multi-Timeframe Confluence Gate (if provided)
        if df_4h is not None and len(df_4h) >= 50:
            ema50_4h = compute_ema(df_4h['close'], 50).iloc[-1]
            st_dir_4h, _ = compute_supertrend(df_4h, 10, 3.0)
            st_val_4h = st_dir_4h.iloc[-1]
            p_4h = df_4h['close'].iloc[-1]
            if p_4h < ema50_4h or st_val_4h != 1:
                return BullSignal(
                    confirmed=False,
                    score=0.0,
                    entry_price=round(current_price, 4),
                    stop_loss=0.0,
                    take_profit=0.0,
                    risk_reward_ratio=self.rr_ratio,
                    is_fresh_trigger=False,
                    reasons=[f"4H MTF Gate: 4H Close (${p_4h:.2f}) < 4H EMA50 (${ema50_4h:.2f}) or 4H Supertrend != 1. Bull Engine locked."],
                    metrics={"price_4h": p_4h, "ema50_4h": ema50_4h, "st_4h": st_val_4h},
                )

        # Trend indicators
        ema_20 = compute_ema(close, 20).iloc[-1]
        ema_50 = compute_ema(close, 50).iloc[-1]
        ema_200 = compute_ema(close, min(200, len(df))).iloc[-1]
        
        # Strict Macro Trend Gate: In Bull Engine, price must be ABOVE EMA 200 (No counter-trend longs in bear regimes)
        if current_price < ema_200:
            return BullSignal(
                confirmed=False,
                score=0.0,
                entry_price=round(current_price, 4),
                stop_loss=0.0,
                take_profit=0.0,
                risk_reward_ratio=self.rr_ratio,
                reasons=[f"Macro Regime Filter: Price (${current_price:.2f}) < EMA200 (${ema_200:.2f}). Bull Engine locked."],
                metrics={"price": current_price, "ema200": ema_200},
            )

        st_dir, st_line = compute_supertrend(df, 10, 3.0)
        current_st_dir = st_dir.iloc[-1]

        # Strength indicators
        adx, p_di, m_di = compute_adx(df, 14)
        curr_adx = adx.iloc[-1]
        curr_p_di = p_di.iloc[-1]
        curr_m_di = m_di.iloc[-1]

        # Strict Chop Gate: Trend strength must be strong (ADX >= 25.0) to prevent chop whipsaws
        if curr_adx < 25.0:
            return BullSignal(
                confirmed=False,
                score=0.0,
                entry_price=round(current_price, 4),
                stop_loss=0.0,
                take_profit=0.0,
                risk_reward_ratio=self.rr_ratio,
                is_fresh_trigger=False,
                reasons=[f"Chop Regime Gate: ADX ({curr_adx:.1f}) < 25.0 (Market in consolidation). Bull Engine locked."],
                metrics={"price": current_price, "adx": curr_adx},
            )

        # Volume indicators
        vwap = compute_vwap(df).iloc[-1]
        obv, obv_ema = compute_obv(df, 20)
        curr_obv = obv.iloc[-1]
        curr_obv_ema = obv_ema.iloc[-1]
        vol_ma = vol.rolling(20).mean().iloc[-1]
        curr_vol = vol.iloc[-1]

        # Momentum indicators
        rsi = compute_rsi(close, 14).iloc[-1]
        macd, macd_sig, macd_hist = compute_macd(close, 12, 26, 9)
        curr_macd_hist = macd_hist.iloc[-1]
        prev_macd_hist = macd_hist.iloc[-2]

        score = 0.0
        max_score = 100.0
        reasons = []

        # --- Criterion 1: Trend Alignment (Weight: 25 pts) ---
        if current_price > ema_50 and ema_50 >= ema_200:
            score += 15.0
            reasons.append("Bullish Trend Structure: Price > EMA50 >= EMA200")
        elif current_price > ema_50:
            score += 8.0
            reasons.append("Moderate Bullish Trend: Price > EMA50")

        if current_st_dir == 1:
            score += 10.0
            reasons.append("Supertrend Bullish (Green)")

        # --- Criterion 2: Directional Strength (Weight: 20 pts) ---
        if curr_p_di > curr_m_di:
            score += 10.0
            reasons.append(f"Bullish Directional Dominance: +DI ({curr_p_di:.1f}) > -DI ({curr_m_di:.1f})")
            if curr_adx >= 20.0:
                score += 10.0
                reasons.append(f"Strong Trend Strength: ADX = {curr_adx:.1f} (>= 20)")
            else:
                score += 5.0
                reasons.append(f"Mild Trend Strength: ADX = {curr_adx:.1f}")

        # --- Criterion 3: Volume & Order Flow (Weight: 25 pts) ---
        if current_price > vwap:
            score += 10.0
            reasons.append(f"Price above VWAP ({vwap:.2f}) - Institutional Buy Support")

        if curr_obv > curr_obv_ema:
            score += 10.0
            reasons.append("OBV Accumulation: On-Balance Volume > OBV EMA")

        if curr_vol >= 1.0 * vol_ma:
            score += 5.0
            reasons.append(f"Volume Surge: Volume ({curr_vol:.1f}) >= 20-MA ({vol_ma:.1f})")

        # --- Criterion 4: Momentum & Timing (Weight: 20 pts) ---
        # Strict Sweet Spot: Never buy into overbought exhaustion (RSI > 62.0)
        if 46.0 <= rsi <= 62.0:
            score += 15.0
            reasons.append(f"Super-Composed Bull Momentum Sweet Spot: RSI = {rsi:.1f} (46-62)")
        elif 40.0 <= rsi < 46.0:
            score += 8.0
            reasons.append(f"Emerging Bull Momentum: RSI = {rsi:.1f}")
        else:
            reasons.append(f"RSI Warning: RSI = {rsi:.1f} (Outside safe sweet spot 46-62)")

        if curr_macd_hist > 0 and curr_macd_hist > prev_macd_hist:
            score += 10.0
            reasons.append("MACD Bullish Expansion: Histogram > 0 and accelerating upward")
        elif curr_macd_hist > prev_macd_hist:
            score += 5.0
            reasons.append("MACD Bullish Turning: Histogram hooking upward")

        # --- Criterion 5: Structure & Breakout Confirmation (Weight: 15 pts) ---
        # Upgraded with R017 (Structural Fractal Swings), Engulfing Candlesticks & Hammer Rejection
        latest_sh_series, _ = compute_confirmed_swings(df)
        confirmed_swing_high = latest_sh_series.iloc[-1]
        swing_ref = confirmed_swing_high if not np.isnan(confirmed_swing_high) else (high.iloc[-16:-1].max() if len(high) >= 16 else high.iloc[-1])
        candle_body = close.iloc[-1] - df['open'].iloc[-1]

        prev_c = close.iloc[-2] if len(close) >= 2 else close.iloc[-1]
        prev_o = df['open'].iloc[-2] if len(df) >= 2 else df['open'].iloc[-1]
        curr_c = close.iloc[-1]
        curr_o = df['open'].iloc[-1]
        is_bull_engulf = (prev_c < prev_o) and (curr_c > curr_o) and (curr_c >= prev_o) and (curr_o <= prev_c * 1.0005)

        is_hammer_series, _ = compute_rejection_candles(df)
        is_hammer = bool(is_hammer_series.iloc[-1])

        if current_price >= swing_ref and curr_vol >= 1.1 * vol_ma:
            score += 15.0
            reasons.append(f"R017 Structural Fractal Breakout: Broke Confirmed Swing High (${swing_ref:.2f}) with Volume >= 1.1x MA")
        elif current_price >= swing_ref:
            score += 10.0
            reasons.append(f"R017 Structural Fractal Breakout: Broke Confirmed Swing High (${swing_ref:.2f})")
        elif is_bull_engulf:
            score += 10.0
            reasons.append("Bullish Engulfing Candlestick Confirmation (+10 pts)")
        elif is_hammer:
            score += 10.0
            reasons.append("Hammer Rejection Candlestick Confirmation (+10 pts)")
        elif candle_body > 0:
            score += 5.0
            reasons.append("Bullish Candle Close")

        # --- Calculate Dynamic ATR Stop Loss & Target (1:2 R:R) ---
        recent_low = low.tail(10).min()
        atr_sl = current_price - (self.atr_sl_mult * current_atr)
        swing_sl = recent_low - (0.2 * current_atr)
        stop_loss = max(atr_sl, swing_sl)
        
        # Enforce minimum stop loss distance of 0.8% and maximum of 3.5% for 5x leverage safety
        min_sl_dist = current_price * 0.008
        max_sl_dist = current_price * 0.035
        raw_dist = current_price - stop_loss
        if raw_dist < min_sl_dist:
            stop_loss = current_price - min_sl_dist
        elif raw_dist > max_sl_dist:
            stop_loss = current_price - max_sl_dist

        risk_distance = current_price - stop_loss
        take_profit = current_price + (risk_distance * self.rr_ratio)

        confirmed = score >= self.min_confidence
        is_fresh_trigger = bool(confirmed and not prev_confirmed)

        metrics = {
            "price": current_price,
            "ema50": ema_50,
            "ema200": ema_200,
            "supertrend": current_st_dir,
            "rsi": rsi,
            "adx": curr_adx,
            "vwap": vwap,
            "atr": current_atr,
            "risk_distance_pct": (risk_distance / current_price) * 100,
        }

        return BullSignal(
            confirmed=confirmed,
            score=round(score, 1),
            entry_price=round(current_price, 4),
            stop_loss=round(stop_loss, 4),
            take_profit=round(take_profit, 4),
            risk_reward_ratio=self.rr_ratio,
            is_fresh_trigger=is_fresh_trigger,
            reasons=reasons,
            metrics=metrics,
        )
