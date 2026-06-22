import numpy as np
import pandas as pd


class RiskManager:
    """
    Hard rules applied to every trade signal.

    Rules enforced:
    1. Max risk per trade     — never lose more than `max_risk_pct` of capital
    2. ATR-based stop loss    — exit at entry - (atr_multiplier × ATR)
    3. Risk/reward filter     — skip trades with R:R < min_rr
    4. VIX regime gate        — reduce size in elevated volatility
    5. Max consecutive losses — halt trading after N losses in a row
    6. Kelly position sizing  — size proportional to edge, capped at max_position_pct
    """

    def __init__(
        self,
        capital: float = 100_000,
        max_risk_pct: float = 0.02,      # 2% of capital per trade
        atr_multiplier: float = 2.0,     # stop = entry - 2×ATR
        min_rr: float = 2.0,             # minimum reward-to-risk ratio
        max_position_pct: float = 0.05,  # max 5% of portfolio per position
        max_consecutive_losses: int = 3, # halt after 3 losses in a row
        vix_high_threshold: float = 25.0,
        vix_crisis_threshold: float = 35.0,
    ):
        self.capital = capital
        self.max_risk_pct = max_risk_pct
        self.atr_multiplier = atr_multiplier
        self.min_rr = min_rr
        self.max_position_pct = max_position_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.vix_high = vix_high_threshold
        self.vix_crisis = vix_crisis_threshold
        self._consecutive_losses = 0

    # ── Kelly position size ───────────────────────────────────────────────────

    def kelly_fraction(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """Fractional Kelly (25% Kelly for safety)."""
        if avg_loss == 0:
            return 0.0
        b = avg_win / avg_loss
        kelly = (b * win_rate - (1 - win_rate)) / b
        return max(0.0, kelly * 0.25)

    # ── Core evaluation ───────────────────────────────────────────────────────

    def evaluate(
        self,
        entry_price: float,
        atr: float,
        confidence: float,
        direction: int,        # 1 = long, -1 = short
        vix: float = 15.0,
        win_rate: float = 0.55,
        avg_win_pct: float = 0.02,
        avg_loss_pct: float = 0.01,
    ) -> dict:
        """
        Evaluate a potential trade and return:
          - approved   : bool — whether the trade passes all filters
          - shares     : int  — number of shares to buy/sell
          - stop_price : float
          - target_price : float
          - risk_amount  : float — dollar risk on this trade
          - reason       : str  — why rejected (if not approved)
        """
        result = {
            "approved": False,
            "shares": 0,
            "stop_price": None,
            "target_price": None,
            "risk_amount": 0.0,
            "reason": "",
        }

        # ── Rule 5: halt on consecutive losses ───────────────────────────────
        if self._consecutive_losses >= self.max_consecutive_losses:
            result["reason"] = f"Halted: {self._consecutive_losses} consecutive losses"
            return result

        # ── Rule 4: VIX regime gate ───────────────────────────────────────────
        vix_size_multiplier = 1.0
        if vix >= self.vix_crisis:
            result["reason"] = f"VIX={vix:.1f} in crisis regime (>{self.vix_crisis})"
            return result
        elif vix >= self.vix_high:
            vix_size_multiplier = 0.5  # half size in elevated vol

        # ── Stop and target prices ────────────────────────────────────────────
        stop_distance = self.atr_multiplier * atr
        if direction == 1:  # long
            stop_price = entry_price - stop_distance
            target_price = entry_price + stop_distance * self.min_rr
        else:               # short
            stop_price = entry_price + stop_distance
            target_price = entry_price - stop_distance * self.min_rr

        # ── Rule 3: R:R check ─────────────────────────────────────────────────
        actual_rr = abs(target_price - entry_price) / abs(entry_price - stop_price)
        if actual_rr < self.min_rr:
            result["reason"] = f"R:R={actual_rr:.2f} below minimum {self.min_rr}"
            return result

        # ── Rule 1 + 6: position sizing ───────────────────────────────────────
        dollar_risk = self.capital * self.max_risk_pct
        kelly = self.kelly_fraction(win_rate, avg_win_pct, avg_loss_pct)
        confidence_factor = (confidence - 0.5) * 2  # map [0.5,1] → [0,1]

        size_fraction = min(
            kelly * confidence_factor * vix_size_multiplier,
            self.max_position_pct,
        )
        max_dollar_position = self.capital * size_fraction

        # Shares based on ATR-stop risk limit
        shares_by_risk = int(dollar_risk / stop_distance) if stop_distance > 0 else 0
        shares_by_size = int(max_dollar_position / entry_price) if entry_price > 0 else 0
        shares = max(0, min(shares_by_risk, shares_by_size))

        if shares == 0:
            result["reason"] = "Position size rounds to 0 shares"
            return result

        actual_risk = shares * stop_distance
        result.update({
            "approved": True,
            "shares": shares,
            "stop_price": round(stop_price, 4),
            "target_price": round(target_price, 4),
            "risk_amount": round(actual_risk, 2),
            "rr_ratio": round(actual_rr, 2),
            "vix_size_multiplier": vix_size_multiplier,
            "reason": "APPROVED",
        })
        return result

    # ── Trade outcome tracking ────────────────────────────────────────────────

    def record_outcome(self, won: bool):
        if won:
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1

    def reset_halt(self):
        """Manually reset the consecutive-loss counter (e.g. start of new week)."""
        self._consecutive_losses = 0


# ── Backtesting helper ────────────────────────────────────────────────────────

def backtest_with_risk(
    prices: pd.Series,
    signals: pd.Series,     # 1=long, -1=short, 0=flat
    confidences: pd.Series,
    atrs: pd.Series,
    vix: pd.Series = None,
    capital: float = 100_000,
    slippage_pct: float = 0.001,        # 0.1% slippage on each fill
    commission_per_share: float = 0.005, # $0.005/share (IBKR rate)
    **rm_kwargs,
) -> pd.DataFrame:
    """
    Walk through signals chronologically applying RiskManager rules.
    Applies realistic slippage and commission on every open and close.
    Returns a trade log DataFrame.
    """
    rm = RiskManager(capital=capital, **rm_kwargs)
    trades = []
    equity = capital
    in_trade = None

    for i in range(1, len(prices)):
        price = prices.iloc[i]
        sig = signals.iloc[i]
        conf = confidences.iloc[i]
        atr = atrs.iloc[i]
        vix_val = float(vix.iloc[i]) if vix is not None else 15.0

        # Close existing position first
        if in_trade is not None:
            entry = in_trade["entry"]
            direction = in_trade["direction"]
            stop = in_trade["stop"]
            target = in_trade["target"]
            shares = in_trade["shares"]

            # Check stop / target hit (use today's price as proxy)
            hit_stop = (direction == 1 and price <= stop) or \
                       (direction == -1 and price >= stop)
            hit_target = (direction == 1 and price >= target) or \
                         (direction == -1 and price <= target)

            # Exit on stop, target, or a GENUINE reversal (opposite signal) — NOT
            # merely because the entry signal turned flat (sig == 0). The score is
            # an ENTRY trigger, not a continuous hold condition; exiting on every
            # flat bar churns positions out in sub-cost moves (the live exit,
            # src.auto_close, already holds to stop/target — this makes the
            # backtest match live). For BUY-only strategies sig is never -1, so
            # exits become purely stop/target.
            if hit_stop or hit_target or sig == -1:
                # Slippage on exit: adverse to position direction
                exit_slip = price * slippage_pct * (-direction)
                exit_price = price + exit_slip
                commission = shares * commission_per_share * 2  # open + close

                raw_pnl = (exit_price - entry) * shares * direction
                pnl = raw_pnl - commission
                equity += pnl
                won = pnl > 0
                rm.record_outcome(won)
                trades.append({
                    "date": prices.index[i],
                    "entry": entry,
                    "exit": round(exit_price, 4),
                    "direction": direction,
                    "shares": shares,
                    "slippage_cost": round(abs(exit_slip) * shares + price * slippage_pct * shares, 2),
                    "commission": round(commission, 2),
                    "pnl": round(pnl, 2),
                    "equity": round(equity, 2),
                    "won": won,
                    "exit_reason": "stop" if hit_stop else ("target" if hit_target else "reversal"),
                })
                in_trade = None

        # Open new trade
        if sig != 0 and in_trade is None:
            decision = rm.evaluate(
                entry_price=price,
                atr=atr,
                confidence=conf,
                direction=sig,
                vix=vix_val,
            )
            if decision["approved"]:
                # Slippage on entry: adverse to intended direction
                entry_slip = price * slippage_pct * sig
                filled_entry = price + entry_slip
                in_trade = {
                    "entry": round(filled_entry, 4),
                    "direction": sig,
                    "stop": decision["stop_price"],
                    "target": decision["target_price"],
                    "shares": decision["shares"],
                }

    return pd.DataFrame(trades)
