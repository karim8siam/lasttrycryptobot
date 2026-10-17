"""
risk_manager.py - Precision Risk and Position Sizing Engine for Binance Futures.
Strictly enforces 1% total account risk per trade and 5x leverage.
"""

from dataclasses import dataclass
import math
from typing import Dict, Any, Optional


@dataclass
class PositionSizeResult:
    is_valid: bool
    side: str  # 'BUY' (Long) or 'SELL' (Short)
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: float  # In base asset (e.g. BTC)
    notional_usd: float  # Total position value in USDT
    margin_required: float  # Collateral allocated (at 5x leverage)
    risk_usd: float  # Actual dollar amount risked at stop loss (1% of equity)
    risk_pct_actual: float  # Percentage of account risked
    estimated_liquidation_price: float
    error_message: Optional[str] = None


class RiskManager:
    """
    Precision Risk Management Engine for Binance USDT-M Futures.
    Enforces:
    - 1% total account equity risk on Stop Loss hit
    - 5x Isolated Leverage
    - Lot size and Tick size precision constraints
    - Liquidation safety buffer verification
    """

    def __init__(
        self,
        risk_per_trade_pct: float = 0.01,  # 1% of total account balance
        leverage: int = 5,                  # 5x leverage
        max_margin_ratio: float = 0.80,    # Max 80% account margin in use per position
    ):
        self.risk_per_trade_pct = risk_per_trade_pct
        self.leverage = leverage
        self.max_margin_ratio = max_margin_ratio

    def calculate_position(
        self,
        account_equity: float,
        side: str,  # 'BUY' or 'SELL'
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        min_qty: float = 0.001,
        step_size: float = 0.001,
        min_notional: float = 5.0,  # Binance min notional order ($5 USDT)
    ) -> PositionSizeResult:
        if account_equity <= 0:
            return PositionSizeResult(
                is_valid=False,
                side=side,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                quantity=0.0,
                notional_usd=0.0,
                margin_required=0.0,
                risk_usd=0.0,
                risk_pct_actual=0.0,
                estimated_liquidation_price=0.0,
                error_message="Account equity is zero or negative.",
            )

        # 1. Dollar risk allowed for 1% of total equity
        target_risk_usd = account_equity * self.risk_per_trade_pct

        # 2. Stop distance calculation
        stop_distance = abs(entry_price - stop_loss)
        if stop_distance <= 0:
            return PositionSizeResult(
                is_valid=False,
                side=side,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                quantity=0.0,
                notional_usd=0.0,
                margin_required=0.0,
                risk_usd=0.0,
                risk_pct_actual=0.0,
                estimated_liquidation_price=0.0,
                error_message="Stop loss cannot be identical to entry price.",
            )

        stop_loss_pct = stop_distance / entry_price

        # 3. Position Size Formula:
        # Risk = Quantity * |Entry - StopLoss|
        # Quantity = TargetRisk / |Entry - StopLoss|
        raw_quantity = target_risk_usd / stop_distance
        notional_usd = raw_quantity * entry_price

        # 4. Leverage & Margin verification
        # At 5x leverage: Margin = Notional / 5
        margin_required = notional_usd / self.leverage

        # Check if margin required exceeds account limits
        max_allowed_margin = account_equity * self.max_margin_ratio
        if margin_required > max_allowed_margin:
            # Scale down position to fit available margin
            margin_required = max_allowed_margin
            notional_usd = margin_required * self.leverage
            raw_quantity = notional_usd / entry_price

        # 5. Round quantity down to Binance stepSize
        if step_size > 0:
            precision = int(round(-math.log10(step_size))) if step_size < 1 else 0
            quantity = math.floor(raw_quantity / step_size) * step_size
            quantity = round(quantity, precision)
        else:
            quantity = raw_quantity

        actual_notional = quantity * entry_price
        actual_margin = actual_notional / self.leverage
        actual_risk_usd = quantity * stop_distance
        actual_risk_pct = (actual_risk_usd / account_equity) * 100

        # Minimum checks
        if quantity < min_qty:
            return PositionSizeResult(
                is_valid=False,
                side=side,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                quantity=quantity,
                notional_usd=actual_notional,
                margin_required=actual_margin,
                risk_usd=actual_risk_usd,
                risk_pct_actual=actual_risk_pct,
                estimated_liquidation_price=0.0,
                error_message=f"Calculated quantity {quantity} is below Binance minQty ({min_qty}). Account balance may be too small for 1% risk at this stop loss.",
            )

        if actual_notional < min_notional:
            return PositionSizeResult(
                is_valid=False,
                side=side,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                quantity=quantity,
                notional_usd=actual_notional,
                margin_required=actual_margin,
                risk_usd=actual_risk_usd,
                risk_pct_actual=actual_risk_pct,
                estimated_liquidation_price=0.0,
                error_message=f"Calculated notional ${actual_notional:.2f} is below Binance minimum order size (${min_notional:.2f}).",
            )

        # 6. Estimated Liquidation Price Calculation (Isolated 5x Margin)
        # Maintenance margin rate for tier 1 is typically ~0.4% - 0.5% (Binance MMR)
        mmr = 0.005  # 0.5%
        if side.upper() == 'BUY':
            # Long Liq Price = Entry * (1 - (1/Leverage) + MMR)
            liq_price = entry_price * (1.0 - (1.0 / self.leverage) + mmr)
            # Stop loss must be safely ABOVE liquidation price
            if stop_loss <= liq_price:
                return PositionSizeResult(
                    is_valid=False,
                    side=side,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    quantity=quantity,
                    notional_usd=actual_notional,
                    margin_required=actual_margin,
                    risk_usd=actual_risk_usd,
                    risk_pct_actual=actual_risk_pct,
                    estimated_liquidation_price=liq_price,
                    error_message=f"DANGER: Long Stop Loss ({stop_loss:.2f}) is below liquidation price ({liq_price:.2f})! Liquidation occurs first.",
                )
        else:
            # Short Liq Price = Entry * (1 + (1/Leverage) - MMR)
            liq_price = entry_price * (1.0 + (1.0 / self.leverage) - mmr)
            # Stop loss must be safely BELOW liquidation price
            if stop_loss >= liq_price:
                return PositionSizeResult(
                    is_valid=False,
                    side=side,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    quantity=quantity,
                    notional_usd=actual_notional,
                    margin_required=actual_margin,
                    risk_usd=actual_risk_usd,
                    risk_pct_actual=actual_risk_pct,
                    estimated_liquidation_price=liq_price,
                    error_message=f"DANGER: Short Stop Loss ({stop_loss:.2f}) is above liquidation price ({liq_price:.2f})! Liquidation occurs first.",
                )

        return PositionSizeResult(
            is_valid=True,
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            quantity=quantity,
            notional_usd=round(actual_notional, 2),
            margin_required=round(actual_margin, 2),
            risk_usd=round(actual_risk_usd, 2),
            risk_pct_actual=round(actual_risk_pct, 2),
            estimated_liquidation_price=round(liq_price, 2),
            error_message=None,
        )
