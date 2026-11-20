import pandas as pd
import numpy as np
import math
import time
from ta.momentum import RSIIndicator
from typing import List, Optional, Dict


def compute_rsi(closes: List[float], period: int) -> Optional[float]:
    """RSI(period). Used as a veto: don't buy UP into >70 / DOWN into <30."""
    if not closes or len(closes) < period:
        return None
    series = pd.Series(closes)
    rsi = RSIIndicator(close=series, window=period).rsi()
    if rsi.empty:
        return None
    val = rsi.iloc[-1]
    return float(val) if not pd.isna(val) else None


def compute_heiken_ashi(candles: List[Dict]) -> List[Dict]:
    """Heiken-Ashi candles. Used (via count_consecutive) for the exhaustion veto."""
    if not candles:
        return []

    ha = []
    for i in range(len(candles)):
        c = candles[i]
        ha_close = (c["open"] + c["high"] + c["low"] + c["close"]) / 4

        if i > 0:
            prev = ha[i - 1]
            ha_open = (prev["open"] + prev["close"]) / 2
        else:
            ha_open = (c["open"] + c["close"]) / 2

        ha_high = max(c["high"], ha_open, ha_close)
        ha_low = min(c["low"], ha_open, ha_close)

        ha.append({
            "open": ha_open,
            "high": ha_high,
            "low": ha_low,
            "close": ha_close,
            "isGreen": ha_close >= ha_open,
            "body": abs(ha_close - ha_open)
        })
    return ha


def count_consecutive(ha_candles: List[Dict]) -> Dict:
    """Length of the current same-colour Heiken-Ashi streak (>=6 = exhausted)."""
    if not ha_candles or len(ha_candles) < 2:
        return {"color": None, "count": None}

    last = ha_candles[-1]
    target = "green" if last["isGreen"] else "red"

    count = 0
    for i in range(len(ha_candles) - 1, -1, -1):
        c = ha_candles[i]
        color = "green" if c["isGreen"] else "red"
        if color != target:
            break
        count += 1

    return {"color": target, "count": count}


def realized_drift_vol(candles: List[Dict], lookback: int = 300):
    """(mean, std) of per-candle log returns. Returns (None, None) if there isn't enough data."""
    closes = [c["close"] for c in candles[-lookback:] if c.get("close")]
    if len(closes) < 20:
        return None, None
    arr = np.asarray(closes, dtype=float)
    rets = np.diff(np.log(arr))
    rets = rets[np.isfinite(rets)]
    if len(rets) < 10:
        return None, None
    return float(np.mean(rets)), float(np.std(rets))


def ewma_vol_per_sqrt_s(candles: List[Dict], span: int = 30, bar_seconds: float = 60.0) -> Optional[float]:
    """Short-horizon RiskMetrics EWMA volatility scaled to per-sqrt-second.
    Uses zero-mean squared log returns so recent volatility regime changes are
    captured quickly without multi-hour stale vol lag."""
    if not candles or bar_seconds <= 0:
        return None
    max_bars = max(120, int(span) * 4)
    closes = [float(c["close"]) for c in candles[-max_bars:] if c.get("close") and float(c["close"]) > 0]
    if len(closes) < 12:
        return None
    arr = np.asarray(closes, dtype=float)
    rets = np.diff(np.log(arr))
    rets = rets[np.isfinite(rets)]
    if len(rets) < 10:
        return None
    alpha = 2.0 / (max(2, int(span)) + 1.0)
    lam = 1.0 - alpha
    init_n = min(10, len(rets))
    var = float(np.mean(rets[:init_n] ** 2))
    for r in rets[init_n:]:
        var = lam * var + alpha * float(r * r)
    if var <= 0.0:
        return None
    return float(math.sqrt(var) / math.sqrt(float(bar_seconds)))


def fair_prob_up(current_price: float, strike: float, tau_s: float,
                 sigma_per_sqrt_s: Optional[float]) -> float:
    """Zero-drift continuous-time GBM probability that price closes ABOVE `strike`
    after `tau_s` remaining seconds:
        z = ln(spot / strike) / (sigma * sqrt(tau_s))
        P(S_T > K) = Phi(z) = 0.5 * erfc(-z / sqrt(2))
    Returns 0..1.
    """
    if not current_price or not strike or current_price <= 0 or strike <= 0:
        return 0.5
    tau = max(float(tau_s), 0.5)
    if sigma_per_sqrt_s is None or sigma_per_sqrt_s <= 0:
        return 1.0 if current_price > strike else (0.5 if current_price == strike else 0.0)
    sd = float(sigma_per_sqrt_s) * math.sqrt(tau)
    if sd <= 0:
        return 1.0 if current_price > strike else (0.5 if current_price == strike else 0.0)
    z = math.log(current_price / strike) / sd
    prob = 0.5 * math.erfc(-z / math.sqrt(2.0))
    return float(min(1.0, max(0.0, prob)))


class BasisTracker:
    """Tracks the smoothed live spread (binance_spot - chainlink_live) via a
    time-weighted EMA so fast Binance ticks can be mapped onto Chainlink's exact
    price scale and compared directly against Polymarket's TWAP strike_open."""

    def __init__(self, halflife_s: float = 30.0, max_age_s: float = 120.0):
        self.halflife_s = float(halflife_s)
        self.max_age_s = float(max_age_s)
        self.value: Optional[float] = None
        self.last_ts: float = 0.0

    def reset(self) -> None:
        self.value = None
        self.last_ts = 0.0

    def ready(self, now: Optional[float] = None) -> bool:
        if self.value is None:
            return False
        t = time.time() if now is None else float(now)
        return (t - self.last_ts) <= self.max_age_s

    def update(self, binance_spot: Optional[float], chainlink_live: Optional[float],
               now: Optional[float] = None) -> Optional[float]:
        if not binance_spot or not chainlink_live or binance_spot <= 0 or chainlink_live <= 0:
            return self.value
        raw = float(binance_spot) - float(chainlink_live)
        # Guard against mismatched symbol / corrupt feed spikes (> 2% spread)
        if abs(raw) > 0.02 * float(chainlink_live):
            return self.value
        t = time.time() if now is None else float(now)
        if self.value is None or (t - self.last_ts) > self.max_age_s:
            self.value = raw
        else:
            dt = max(0.0, t - self.last_ts)
            if dt > 0.0:
                alpha = 1.0 - math.exp(-math.log(2.0) * dt / self.halflife_s)
                self.value = (1.0 - alpha) * self.value + alpha * raw
        self.last_ts = t
        return self.value

    def adjust(self, binance_spot: Optional[float], now: Optional[float] = None) -> Optional[float]:
        if not binance_spot or binance_spot <= 0:
            return binance_spot
        if self.ready(now):
            adj = float(binance_spot) - float(self.value)
            return adj if adj > 0 else float(binance_spot)
        return float(binance_spot)
