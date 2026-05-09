"""
GEX Heatmap - Schwab API (FIXED VERSION with History Persistence & Auto-Start)
===============================================================================

FIXES APPLIED:
1. Removed normalization - heatmap now shows actual GEX magnitude
2. Fixed zero-value strikes showing incorrect colors (proper handling at value 127)
3. Aligned heatmap Y-axis with bar chart using correct strike intervals
4. Top 5 gamma/volume charts select by absolute magnitude regardless of ATM position
5. Fixed Intraday Heatmap Y-axis to maintain ±1% of current price (no more scale resets)
6. Added automatic history persistence - saves daily data and loads previous days
7. Added auto-start/stop during market hours (9:15 AM - 4:15 PM ET)

Real-time Gamma Exposure heatmap for futures and index/ETF options.

Supported Symbols:
- Futures: ES (E-mini S&P), NQ (E-mini Nasdaq), GC (Gold)
- Index/ETF: SPX (S&P 500 Index), SPY (S&P 500 ETF), QQQ (Nasdaq 100 ETF)

Features:
- 30 second and 1 minute update intervals
- Configurable strike count (30, 50, 75, 100)
- Magnitude-preserving colors: Deep red (negative) to black (zero) to deep green (positive)
- Historical heatmap visualization
- Automatic daily history saving (configurable retention: 7-90 days, default 30)
- Load single day or multi-day history
- Export current session or all saved history to CSV
- Auto-start/stop during market hours (configurable)
- History stored in: ~/.gex_evolution/history/
- Tokens stored in:  ~/.gex_evolution/history/schwab_tokens.json

Setup:
    1. Create a Schwab developer app at https://developer.schwab.com
    2. Set CLIENT_ID and CLIENT_SECRET in the SchwabConfig class below
    3. Set REDIRECT_URI to match your app (default: https://127.0.0.1)

Requirements:
    pip install PyQt6 pyqtgraph numpy requests authlib pytz

Author: Claude (Anthropic)
Version: 6.2 - Multi-Panel Export, Grid Export & Auto-Refresh (Mar 2026)
"""

import sys
import os
import json
import time
import math
import threading
import webbrowser
import requests
import pickle
from datetime import datetime, timedelta
from collections import deque
from typing import Dict, List, Optional, Tuple
import numpy as np

try:
    import pytz
    HAS_PYTZ = True
except ImportError:
    HAS_PYTZ = False
    print("Warning: pytz not installed. Auto-start will use local time instead of ET.")
    print("Install with: pip install pytz")

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QSpinBox, QFrame, QStatusBar,
    QGroupBox, QGridLayout, QLineEdit, QMessageBox, QTabWidget,
    QTextEdit, QSplitter, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QColor, QFont, QPalette

import pyqtgraph as pg

# ============================================================
# SCHWAB API CONFIGURATION
# ============================================================

class SchwabConfig:
    """Schwab API configuration - user must fill in credentials"""
    
    # Schwab API credentials
    CLIENT_ID = "kI1g7Uz8UhRjv29YHc1aM2UKaPiFvGOo4DSmhlyx9AkPCdKU"
    CLIENT_SECRET = "8cg6EpLYXtg040R9bVH77K2jV6weB68pWkL8GRnIXsfvJebLoXMo36B7QLlnRXKZ"
    REDIRECT_URI = "https://127.0.0.1"
    
    # History persistence settings
    HISTORY_DIR = os.path.expanduser("~/.gex_evolution/history")
    HISTORY_DAYS_TO_KEEP = 30  # Keep 30 days of history (configurable: 7, 14, 30, 60, 90)
    
    # Auto-start/stop market hours (Eastern Time)
    AUTO_START_ENABLED = True  # Set to False to disable auto-start
    MARKET_START_TIME = (9, 15)  # 9:15 AM ET
    MARKET_END_TIME = (16, 15)   # 4:15 PM ET
    AUTO_START_SYMBOL = "SPY"    # Default symbol for auto-start
    AUTO_START_INTERVAL = 60     # Default interval in seconds
    AUTO_START_STRIKES = 75      # Default number of strikes
    
    # API endpoints
    AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
    TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
    BASE_URL = "https://api.schwabapi.com/marketdata/v1"
    
    # Symbol mapping (futures use /, equities use $)
    SYMBOL_MAP = {
        # Futures
        "ES": "/ES",   # E-mini S&P 500
        "NQ": "/NQ",   # E-mini Nasdaq 100
        "GC": "/GC",   # Gold
        # Index/ETF
        "SPX": "$SPX",  # S&P 500 Index
        "SPY": "SPY",   # S&P 500 ETF
        "QQQ": "QQQ",   # Nasdaq 100 ETF
        "VIX": "$VIX",  # CBOE Volatility Index
    }
    
    # Contract multipliers for GEX calculation
    MULTIPLIERS = {
        "ES": 50,
        "NQ": 20,
        "GC": 100,
        "SPX": 100,  # Index options
        "SPY": 100,  # ETF options
        "QQQ": 100,  # ETF options
        "VIX": 100,  # VIX options
    }
    
    # Strike intervals for each symbol
    STRIKE_INTERVALS = {
        "ES": 5,
        "NQ": 25,
        "GC": 5,
        "SPX": 5,
        "SPY": 1,
        "QQQ": 1,
        "VIX": 0.5,  # VIX options trade in $0.50 increments
    }
    
    # Price ranges for simulation
    PRICE_RANGES = {
        "ES": (5800, 6300),
        "NQ": (20000, 23000),
        "GC": (2400, 2900),
        "SPX": (5800, 6300),
        "SPY": (580, 630),
        "QQQ": (500, 550),
        "VIX": (12, 45),  # Typical VIX range; can spike to 80+ in crises
    }
    
    # Symbol categories
    FUTURES = ["ES", "NQ", "GC"]
    EQUITIES = ["SPX", "SPY", "QQQ", "VIX"]
    
    # Price history symbols for RV calculation
    # SPX index may not have price history, use these fallbacks
    RV_SYMBOL_MAP = {
        "ES": "$SPX",    # Try SPX first for ES
        "NQ": "QQQ",     # Use QQQ for NQ
        "GC": "GLD",     # Use GLD ETF for Gold
        "SPX": "$SPX",   # Try SPX directly
        "SPY": "SPY",    # SPY has history
        "QQQ": "QQQ",    # QQQ has history
        "VIX": "$VIX",   # VIX index directly
    }
    
    # Fallback symbols if primary fails
    RV_FALLBACK_MAP = {
        "$SPX": "SPY",   # If SPX fails, use SPY
        "SPX": "SPY",
        "ES": "SPY",
        "$VIX": "VXX",   # If VIX fails, use VXX ETF
        "VIX": "VXX",
    }


# ============================================================
# 1D EXPECTED MOVE CALCULATOR (MenthorQ-style)
# ============================================================

class OneDayRangeCalculator:
    """
    MenthorQ-style 1D Min/Max calculation with:
    - Schwab price history for Realized Volatility
    - ATM IV from options chain
    - Dynamic VIX-based confidence multiplier
    - Spot-weighted effective gamma (GPT Fix #1)
    - Asymmetric bounds based on gamma skew (GPT Fix #2)
    - -Gamma vol override (GPT Fix #3)
    
    Implements Gemini recommendations:
    1. Try/except with IV/16 fallback
    2. Log returns for RV calculation
    3. Dynamic VIX-based multiplier
    
    Implements GPT recommendations:
    1. Spot-weighted gamma (near-ATM matters more)
    2. Asymmetric bounds (not shifted center)
    3. -Gamma vol override (gamma dominates in -gamma regimes)
    """
    
    # Decay constant for spot-weighting (1.2% of spot)
    SPOT_WEIGHT_DECAY = 0.012
    
    # Max asymmetry (30% difference between up/down move)
    MAX_SKEW = 0.30
    
    def __init__(self):
        self.rv_20d = None
        self.rv_last_updated = None
        self.vix_level = None
        
    def fetch_realized_volatility(self, headers, symbol='$SPX', fallback_symbol='SPY'):
        """
        Fetch 20-day realized volatility from Schwab price history.
        
        Args:
            headers: Schwab API headers with auth
            symbol: Primary symbol to fetch (default $SPX)
            fallback_symbol: Fallback if primary fails (default SPY)
            
        Returns:
            Annualized RV as decimal (e.g., 0.15 = 15%)
        """
        symbols_to_try = [symbol]
        if fallback_symbol and fallback_symbol != symbol:
            symbols_to_try.append(fallback_symbol)
        
        for try_symbol in symbols_to_try:
            try:
                print(f"Fetching RV for {try_symbol}...")
                
                url = f"{SchwabConfig.BASE_URL}/pricehistory"
                params = {
                    'symbol': try_symbol,
                    'periodType': 'month',
                    'period': 1,
                    'frequencyType': 'daily',
                    'frequency': 1,
                }
                
                response = requests.get(url, headers=headers, params=params, timeout=15)
                
                if response.status_code != 200:
                    print(f"  API error for {try_symbol}: {response.status_code}")
                    continue
                    
                data = response.json()
                candles = data.get('candles', [])
                
                if len(candles) < 21:
                    print(f"  Insufficient data for {try_symbol}: {len(candles)} candles")
                    continue
                
                # Get last 21 closes (to compute 20 returns)
                closes = np.array([c['close'] for c in candles[-21:]])
                
                # === LOG RETURNS (Gemini fix #2) ===
                log_returns = np.diff(np.log(closes))
                
                # Annualized standard deviation
                rv_20d = np.std(log_returns) * np.sqrt(252)
                
                self.rv_20d = rv_20d
                self.rv_last_updated = datetime.now().date()
                
                print(f"  ✓ 20-Day Realized Volatility ({try_symbol}): {rv_20d*100:.2f}%")
                return rv_20d
                
            except Exception as e:
                print(f"  RV fetch failed for {try_symbol}: {e}")
                continue
        
        # === FALLBACK: IV/16 rule (Gemini fix #1) ===
        print("  ⚠ All RV fetches failed, using IV/16 fallback (16%)")
        self.rv_20d = 0.16  # 16% long-term average
        self.rv_last_updated = datetime.now().date()
        return self.rv_20d
    
    def fetch_vix_level(self, headers):
        """
        Fetch current VIX level from Schwab quotes.
        Used for dynamic confidence multiplier.
        """
        try:
            url = f"{SchwabConfig.BASE_URL}/quotes"
            params = {'symbols': '$VIX', 'fields': 'quote'}
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                vix_data = data.get('$VIX', {})
                quote = vix_data.get('quote', {})
                vix_price = quote.get('lastPrice') or quote.get('closePrice', 18.0)
                self.vix_level = float(vix_price)
                print(f"  VIX Level: {self.vix_level:.2f}")
                return self.vix_level
        except Exception as e:
            print(f"  VIX fetch failed: {e}")
        
        # Default to normal vol regime
        self.vix_level = 18.0
        return self.vix_level
    
    def get_confidence_multiplier(self, vix=None):
        """
        Dynamic multiplier based on VIX regime (Gemini fix #3).
        
        VIX < 15:  Low vol → 1.15 (tighter ~80% range)
        VIX 15-25: Normal  → 1.25 (standard ~85% range)
        VIX 25-35: Elevated → 1.40 (~90% range)
        VIX > 35:  Crisis  → 1.65 (~95% range)
        """
        vix_level = vix if vix is not None else self.vix_level
        
        if vix_level is None:
            return 1.25  # Default
        
        if vix_level < 15:
            return 1.15
        elif vix_level < 25:
            return 1.25
        elif vix_level < 35:
            return 1.40
        else:
            return 1.65
    
    def compute_spot_weighted_gamma(self, spot, strikes, gex_values):
        """
        GPT Fix #1: Compute spot-weighted effective gamma.
        
        Near-ATM gamma matters exponentially more than far OTM.
        Uses exponential decay based on distance from spot.
        
        Args:
            spot: Current price
            strikes: List of strike prices
            gex_values: List of GEX values per strike
            
        Returns:
            tuple: (gamma_eff, gamma_abs, gamma_ratio)
            - gamma_eff: Net spot-weighted gamma (can be negative)
            - gamma_abs: Sum of absolute spot-weighted gamma
            - gamma_ratio: gamma_eff / gamma_abs (-1 to +1)
        """
        if not strikes or not gex_values or len(strikes) != len(gex_values):
            return 0, 0, 0
        
        strikes = np.array(strikes)
        gex = np.array(gex_values)
        
        # Compute distance from spot as percentage
        distance_pct = np.abs(strikes - spot) / spot
        
        # Exponential decay weights: near-ATM → weight ≈ 1, far OTM → weight → 0
        weights = np.exp(-distance_pct / self.SPOT_WEIGHT_DECAY)
        
        # Weighted gamma
        weighted_gex = gex * weights
        
        gamma_eff = np.sum(weighted_gex)
        gamma_abs = np.sum(np.abs(weighted_gex))
        
        if gamma_abs > 0:
            gamma_ratio = gamma_eff / gamma_abs
        else:
            gamma_ratio = 0
        
        return gamma_eff, gamma_abs, gamma_ratio
    
    def get_vol_adjustment(self, atm_iv, gamma_ratio):
        """
        GPT Fix #3: Vol adjustment that respects gamma regime.
        
        In +gamma: IV/RV ratio matters (vol normalization)
        In -gamma: Dampen vol effect, let gamma dominate
        
        Args:
            atm_iv: ATM implied volatility
            gamma_ratio: -1 to +1 (from spot-weighted gamma)
            
        Returns:
            vol_adjustment factor
        """
        if not self.rv_20d or self.rv_20d <= 0:
            return 1.0
        
        iv_rv_ratio = atm_iv / self.rv_20d
        iv_rv_ratio = np.clip(iv_rv_ratio, 0.5, 2.0)
        
        if gamma_ratio >= 0:
            # +Gamma regime: Normal vol normalization
            # sqrt() dampens the effect
            vol_adjustment = np.sqrt(iv_rv_ratio)
        else:
            # -Gamma regime: Dampen vol effect, gamma dominates
            # Only apply 25% of the IV/RV deviation
            # This lets gamma drive the range, not IV
            vol_adjustment = 1.0 + 0.25 * (iv_rv_ratio - 1.0)
            # Ensure we don't go below 0.85 (allow some tightening)
            vol_adjustment = max(vol_adjustment, 0.85)
        
        return vol_adjustment
    
    def get_gamma_modifier(self, gamma_ratio, vix=None):
        """
        Gamma modifier that scales with volatility regime.
        
        gamma_ratio: -1 (all puts) to +1 (all calls)
        
        Normal vol (VIX < 25):
            +gamma → 0.85x (15% tighter)
            -gamma → 1.25x (25% wider)
        
        High vol (VIX > 25):
            +gamma → 0.80x (20% tighter - pinning stronger)
            -gamma → 1.40x (40% wider - squeezes more violent)
        """
        vix_level = vix if vix is not None else self.vix_level
        
        # Scale effect based on vol regime
        if vix_level and vix_level > 25:
            base_effect = 0.30  # High vol - more extreme
        else:
            base_effect = 0.20  # Normal regime
        
        # +gamma tightens, -gamma widens
        modifier = 1.0 - (gamma_ratio * base_effect)
        
        # Clamp to reasonable range
        return np.clip(modifier, 0.70, 1.60)
    
    def calculate_1d_range(self, price, atm_iv, strikes=None, gex_values=None,
                           net_gex=0, total_abs_gex=0, vix=None):
        """
        Calculate 1D Min/Max using enhanced MenthorQ approach.
        
        Args:
            price: Current underlying price
            atm_iv: ATM implied volatility (decimal, e.g., 0.15)
            strikes: List of strike prices (for spot-weighted gamma)
            gex_values: List of GEX values per strike
            net_gex: Fallback net GEX if strikes/gex not provided
            total_abs_gex: Fallback total absolute GEX
            vix: Current VIX level (optional, uses cached if None)
            
        Returns:
            dict with one_d_min, one_d_max, and adjustment details
        """
        vix_level = vix if vix is not None else self.vix_level
        
        # === GPT FIX #1: Spot-Weighted Gamma ===
        if strikes is not None and gex_values is not None:
            gamma_eff, gamma_abs, gamma_ratio = self.compute_spot_weighted_gamma(
                price, strikes, gex_values
            )
        elif total_abs_gex > 0:
            # Fallback to simple ratio
            gamma_ratio = net_gex / total_abs_gex
            gamma_eff = net_gex
            gamma_abs = total_abs_gex
        else:
            gamma_ratio = 0
            gamma_eff = 0
            gamma_abs = 0
        
        # === STEP 1: Base Expected Move ===
        # Gemini formula: price × σ / √252 × K
        multiplier = self.get_confidence_multiplier(vix_level)
        daily_vol = atm_iv / np.sqrt(252)
        base_move = price * daily_vol * multiplier
        
        # === GPT FIX #3: Vol Adjustment (gamma-aware) ===
        vol_adjustment = self.get_vol_adjustment(atm_iv, gamma_ratio)
        adjusted_move = base_move * vol_adjustment
        
        # === STEP 3: Gamma Regime Modifier ===
        gamma_modifier = self.get_gamma_modifier(gamma_ratio, vix_level)
        final_move = adjusted_move * gamma_modifier
        
        # === GPT FIX #2: Asymmetric Bounds ===
        # Instead of shifting center, create unequal up/down distances
        # +gamma (positive ratio) → harder to break UP, easier to break DOWN
        # -gamma (negative ratio) → harder to break DOWN, easier to break UP
        skew = np.clip(gamma_ratio, -self.MAX_SKEW, self.MAX_SKEW)
        
        # Asymmetric multipliers:
        # skew = +0.3 → up_mult = 0.7, down_mult = 1.3 (resistance above)
        # skew = -0.3 → up_mult = 1.3, down_mult = 0.7 (support below)
        up_mult = 1.0 - skew
        down_mult = 1.0 + skew
        
        one_d_max = price + final_move * up_mult
        one_d_min = price - final_move * down_mult
        
        # Calculate effective move for display (average of up/down)
        effective_move = (one_d_max - one_d_min) / 2
        
        return {
            'one_d_min': one_d_min,
            'one_d_max': one_d_max,
            'expected_move': effective_move,
            'up_move': final_move * up_mult,
            'down_move': final_move * down_mult,
            'base_move': base_move,
            'multiplier': multiplier,
            'vol_adjustment': vol_adjustment,
            'gamma_modifier': gamma_modifier,
            'gamma_ratio': gamma_ratio,
            'skew': skew,
            'iv': atm_iv,
            'rv': self.rv_20d,
            'vix': vix_level,
        }


# ============================================================
# TIME AXIS FOR HEATMAP
# ============================================================

class TimeAxisItem(pg.AxisItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timestamps: List[datetime] = []
        
    def set_timestamps(self, timestamps: List[datetime]):
        self.timestamps = list(timestamps)
        
    def tickStrings(self, values, scale, spacing):
        result = []
        for v in values:
            idx = int(round(v))
            if 0 <= idx < len(self.timestamps):
                result.append(self.timestamps[idx].strftime('%H:%M:%S'))
            else:
                result.append('')
        return result


# ============================================================
# DEMO DATA FEED (For testing without API)
# ============================================================

class DemoDataFeed(QObject):
    """Simulated data feed for testing"""
    
    data_updated = pyqtSignal(dict)
    status_updated = pyqtSignal(str)
    
    def __init__(self, symbol: str = "ES", num_strikes: int = 100, interval: int = 30):
        super().__init__()
        self.symbol = symbol.upper()
        self.num_strikes = num_strikes
        self.interval = interval
        self.running = False
        self.expirations = []  # List of selected expirations
        
        # 1D Range Calculator
        self.range_calc = OneDayRangeCalculator()
        # Set simulated RV and VIX for demo mode
        self.range_calc.rv_20d = 0.14  # 14% simulated RV
        self.range_calc.vix_level = 18.0  # Normal VIX
        
        # Simulated prices for known symbols
        self.base_prices = {
            "ES": 6050.0, "/ES": 6050.0,
            "NQ": 21500.0, "/NQ": 21500.0,
            "GC": 2650.0, "/GC": 2650.0,
            "SPX": 6050.0, "$SPX": 6050.0,
            "SPY": 605.0,
            "QQQ": 525.0,
            "VIX": 18.0, "$VIX": 18.0,  # VIX typical starting level
        }
        self.prices = {}
        self.velocities = {}
        self.tick = 0
        
    def set_symbol(self, symbol: str):
        self.symbol = symbol.upper()
        
    def set_num_strikes(self, num: int):
        self.num_strikes = num
        
    def set_interval(self, interval: int):
        self.interval = interval
        
    def set_expirations(self, expirations: List[str]):
        """Set list of expiration dates to aggregate"""
        self.expirations = expirations
        
    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        
    def stop(self):
        self.running = False
        
    def _run(self):
        exp_str = f"{len(self.expirations)} exp" if self.expirations else "no exp"
        self.status_updated.emit(f"Demo mode - {self.symbol} ({exp_str})")
        
        while self.running:
            data = self._generate_data()
            self.data_updated.emit(data)
            
            price = data['price']
            total_gex = sum(data['gex'])
            self.status_updated.emit(
                f"Demo | {self.symbol}: {price:.2f} | {len(data['strikes'])} strikes | "
                f"{len(self.expirations)} exp | Net GEX: {total_gex/1e6:.1f}M | "
                f"{datetime.now().strftime('%H:%M:%S')}"
            )
            
            time.sleep(self.interval)
            
    def _generate_data(self) -> dict:
        self.tick += 1
        
        sym = self.symbol
        
        # Initialize price for this symbol if not seen before
        if sym not in self.prices:
            # Use known price or default based on symbol pattern
            if sym in self.base_prices:
                self.prices[sym] = self.base_prices[sym]
            elif sym.startswith('/'):
                self.prices[sym] = 5000.0  # Futures default
            elif sym.startswith('$'):
                self.prices[sym] = 5000.0  # Index default
            else:
                self.prices[sym] = 500.0   # ETF/stock default
            self.velocities[sym] = 0
        
        # Get config for this symbol (with defaults for unknown symbols)
        strike_interval = SchwabConfig.STRIKE_INTERVALS.get(sym, 
            SchwabConfig.STRIKE_INTERVALS.get(sym.lstrip('/$'), 5))
        multiplier = SchwabConfig.MULTIPLIERS.get(sym,
            SchwabConfig.MULTIPLIERS.get(sym.lstrip('/$'), 100))
        price_range = SchwabConfig.PRICE_RANGES.get(sym,
            SchwabConfig.PRICE_RANGES.get(sym.lstrip('/$'), 
                (self.prices[sym] * 0.9, self.prices[sym] * 1.1)))
        
        # Determine if futures or equity based on price/symbol
        is_futures = sym.startswith('/') or sym in ['ES', 'NQ', 'GC']
        
        # Price simulation — scale velocity relative to the symbol's own reference price
        # so low-priced symbols (VIX ~18) move proportionally to high-priced ones (ES ~6000)
        ref_price = max(self.base_prices.get(sym, self.base_prices.get(sym.lstrip('/$'), 6000.0)), 1.0)
        trend = math.sin(self.tick / 40) * 0.3
        self.velocities[sym] += np.random.randn() * 0.2 + trend * 0.05
        self.velocities[sym] *= 0.92
        
        # Scale velocity based on price magnitude
        price_scale = self.prices[sym] / ref_price
        self.prices[sym] += self.velocities[sym] * price_scale
        
        # Clamp to range
        self.prices[sym] = np.clip(self.prices[sym], price_range[0], price_range[1])
        
        price = self.prices[sym]
        atm = round(price / strike_interval) * strike_interval
        
        # Generate strikes centered on ATM
        strikes_per_side = self.num_strikes // 2
        
        call_strikes = [atm + i * strike_interval for i in range(1, strikes_per_side + 1)]
        put_strikes = [atm - i * strike_interval for i in range(1, strikes_per_side + 1)]
        put_strikes.reverse()  # Low to high
        
        # Generate GEX values - aggregate across expirations
        call_gex = [0.0] * len(call_strikes)
        put_gex = [0.0] * len(put_strikes)
        atm_gex = 0.0
        
        # Base GEX scaling factor
        base_scale = 50e6 if is_futures else 80e6
        
        # Simulated implied volatility (annualized, as decimal)
        # Typical range: 12-30% for SPX, higher during volatility
        base_iv = 0.16 + 0.04 * math.sin(self.tick / 100)  # Oscillates 12-20%
        iv = base_iv + np.random.randn() * 0.01  # Add noise
        iv = max(0.08, min(0.50, iv))  # Clamp to reasonable range
        
        # Simulate VIX variation (oscillates 14-22)
        self.range_calc.vix_level = 18.0 + 4.0 * math.sin(self.tick / 150)
        
        # Number of expirations to simulate
        num_exp = len(self.expirations) if self.expirations else 3
        
        for exp_idx in range(num_exp):
            # Each expiration has different gamma profile
            # Nearer expirations have higher gamma (more GEX)
            exp_weight = 1.0 / (exp_idx + 1)  # Decreasing weight for further expirations
            
            for i, strike in enumerate(call_strikes):
                dist = strike - price
                atm_factor = math.exp(-0.0003 * (dist / max(price_scale, 0.1))**2)
                round_mult = 3.0 if strike % (strike_interval * 10) == 0 else 1.5 if strike % (strike_interval * 5) == 0 else 1.0
                # Net GEX at this strike: calls contribute positive, puts contribute negative.
                # Near ATM call gamma dominates → positive. Far OTM the ratio shifts naturally.
                call_contribution = base_scale * atm_factor * round_mult * multiplier / 100 * exp_weight
                put_contribution = -base_scale * 0.75 * atm_factor * round_mult * multiplier / 100 * exp_weight
                net = (call_contribution + put_contribution) + np.random.randn() * abs(call_contribution) * 0.25
                call_gex[i] += net
                
            for i, strike in enumerate(put_strikes):
                dist = price - strike
                atm_factor = math.exp(-0.0003 * (dist / max(price_scale, 0.1))**2)
                round_mult = 3.0 if strike % (strike_interval * 10) == 0 else 1.5 if strike % (strike_interval * 5) == 0 else 1.0
                # Symmetric: put gamma dominates below ATM → negative, but call OI can push some strikes positive
                put_contribution = -base_scale * atm_factor * round_mult * multiplier / 100 * exp_weight
                call_contribution = base_scale * 0.75 * atm_factor * round_mult * multiplier / 100 * exp_weight
                net = (put_contribution + call_contribution) + np.random.randn() * abs(put_contribution) * 0.25
                put_gex[i] += net
            
            # ATM GEX for this expiration
            atm_gex += (np.random.randn() * 0.3 + 0.2) * base_scale * multiplier / 100 * exp_weight
        
        # Build combined arrays: puts + ATM + calls
        all_strikes = put_strikes + [atm] + call_strikes
        all_gex = put_gex + [atm_gex] + call_gex
        
        # Generate volume data (correlated with GEX magnitude)
        call_volume = []
        put_volume = []
        for i, gex in enumerate(call_gex):
            base_vol = abs(gex) / 1e6 * np.random.uniform(50, 150)
            call_volume.append(int(max(100, base_vol + np.random.randint(-500, 2000))))
        for i, gex in enumerate(put_gex):
            base_vol = abs(gex) / 1e6 * np.random.uniform(50, 150)
            put_volume.append(int(max(100, base_vol + np.random.randint(-500, 2000))))
        
        atm_volume = int(np.random.uniform(500, 3000))
        all_volume = put_volume + [atm_volume] + call_volume
        
        # === Calculate 1D Expected Move (MenthorQ-style with GPT fixes) ===
        range_data = self.range_calc.calculate_1d_range(
            price=price,
            atm_iv=iv,
            strikes=all_strikes,
            gex_values=all_gex
        )
        
        one_d_max = range_data['one_d_max']
        one_d_min = range_data['one_d_min']
        
        # Calculate gamma flip (zero crossing via linear interpolation)
        gamma_flip = None
        for i in range(len(all_strikes) - 1):
            if (all_gex[i] < 0 and all_gex[i + 1] > 0) or (all_gex[i] > 0 and all_gex[i + 1] < 0):
                s1, g1 = all_strikes[i], all_gex[i]
                s2, g2 = all_strikes[i + 1], all_gex[i + 1]
                gamma_flip = s1 + (s2 - s1) * (0 - g1) / (g2 - g1)
                break
        
        # Calculate call wall (highest positive GEX strike) and put wall (most negative GEX strike)
        call_wall = None
        put_wall = None
        if all_gex:
            max_gex_idx = int(np.argmax(all_gex))
            min_gex_idx = int(np.argmin(all_gex))
            call_wall = all_strikes[max_gex_idx]
            put_wall = all_strikes[min_gex_idx]
        
        # Calculate GEX ratio (put GEX / call GEX)
        total_call_gex = sum(g for g in all_gex if g > 0)
        total_put_gex = abs(sum(g for g in all_gex if g < 0))
        gex_ratio = total_put_gex / total_call_gex if total_call_gex > 0 else 0
        
        # Calculate volume-based P/C ratio (put volume / call volume)
        total_call_volume = sum(call_volume)
        total_put_volume = sum(put_volume)
        pc_ratio = total_put_volume / total_call_volume if total_call_volume > 0 else 0
            
        return {
            'timestamp': datetime.now(),
            'symbol': sym,
            'price': price,
            'atm': atm,
            'iv': iv,  # Annualized IV as decimal
            'rv': self.range_calc.rv_20d,
            'vix': self.range_calc.vix_level,
            'one_d_max': one_d_max,
            'one_d_min': one_d_min,
            'expected_move': range_data['expected_move'],
            'up_move': range_data['up_move'],
            'down_move': range_data['down_move'],
            'vol_adjustment': range_data['vol_adjustment'],
            'gamma_modifier': range_data['gamma_modifier'],
            'gamma_ratio': range_data['gamma_ratio'],
            'skew': range_data['skew'],
            'gamma_flip': gamma_flip,
            'call_wall': call_wall,
            'put_wall': put_wall,
            'gex_ratio': gex_ratio,
            'pc_ratio': pc_ratio,
            'expirations': self.expirations,
            'strikes': all_strikes,
            'gex': all_gex,
            'volume': all_volume,
            'call_strikes': call_strikes,
            'put_strikes': put_strikes,
            'call_gex': call_gex,
            'put_gex': put_gex,
            'call_volume': call_volume,
            'put_volume': put_volume,
        }


# ============================================================
# SCHWAB API DATA FEED
# ============================================================

class SchwabDataFeed(QObject):
    """Real Schwab API data feed"""
    
    data_updated = pyqtSignal(dict)
    status_updated = pyqtSignal(str)
    auth_required = pyqtSignal(str)  # Emits auth URL
    expirations_loaded = pyqtSignal(list)  # Emits list of expiration dates
    
    def __init__(self, symbol: str = "ES", num_strikes: int = 100, interval: int = 30):
        super().__init__()
        self.symbol = symbol
        self.num_strikes = num_strikes
        self.interval = interval
        self.running = False
        self.expirations = []  # List of selected expiration dates
        
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = None
        
        # 1D Range Calculator
        self.range_calc = OneDayRangeCalculator()
        self.rv_fetched_today = False
        self.vix_fetched = False
        
        self._load_tokens()
        
    def _load_tokens(self):
        """Load saved tokens from file"""
        token_file = os.path.join(SchwabConfig.HISTORY_DIR, 'schwab_tokens.json')
        if os.path.exists(token_file):
            try:
                with open(token_file, 'r') as f:
                    data = json.load(f)
                    self.access_token = data.get('access_token')
                    self.refresh_token = data.get('refresh_token')
                    expiry = data.get('token_expiry')
                    if expiry:
                        self.token_expiry = datetime.fromisoformat(expiry)
            except Exception as e:
                print(f"Error loading tokens: {e}")
                
    def _save_tokens(self):
        """Save tokens to file"""
        os.makedirs(SchwabConfig.HISTORY_DIR, exist_ok=True)
        token_file = os.path.join(SchwabConfig.HISTORY_DIR, 'schwab_tokens.json')
        try:
            data = {
                'access_token': self.access_token,
                'refresh_token': self.refresh_token,
                'token_expiry': self.token_expiry.isoformat() if self.token_expiry else None
            }
            with open(token_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error saving tokens: {e}")
            
    def get_auth_url(self) -> str:
        """Get OAuth authorization URL"""
        import urllib.parse
        params = {
            'response_type': 'code',
            'client_id': SchwabConfig.CLIENT_ID,
            'redirect_uri': SchwabConfig.REDIRECT_URI,
            'scope': 'api'
        }
        return f"{SchwabConfig.AUTH_URL}?{urllib.parse.urlencode(params)}"
        
    def exchange_code(self, auth_code: str) -> bool:
        """Exchange authorization code for tokens"""
        import requests
        import base64
        
        try:
            credentials = f"{SchwabConfig.CLIENT_ID}:{SchwabConfig.CLIENT_SECRET}"
            encoded = base64.b64encode(credentials.encode()).decode()
            
            headers = {
                'Authorization': f'Basic {encoded}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'authorization_code',
                'code': auth_code,
                'redirect_uri': SchwabConfig.REDIRECT_URI
            }
            
            response = requests.post(SchwabConfig.TOKEN_URL, headers=headers, data=data)
            
            if response.status_code == 200:
                tokens = response.json()
                self.access_token = tokens['access_token']
                self.refresh_token = tokens.get('refresh_token')
                self.token_expiry = datetime.now() + timedelta(seconds=tokens.get('expires_in', 1800))
                self._save_tokens()
                return True
            else:
                self.status_updated.emit(f"Token exchange failed: {response.text}")
                return False
                
        except Exception as e:
            self.status_updated.emit(f"Auth error: {e}")
            return False
            
    def _refresh_access_token(self) -> bool:
        """Refresh the access token"""
        import requests
        import base64
        
        if not self.refresh_token:
            return False
            
        try:
            credentials = f"{SchwabConfig.CLIENT_ID}:{SchwabConfig.CLIENT_SECRET}"
            encoded = base64.b64encode(credentials.encode()).decode()
            
            headers = {
                'Authorization': f'Basic {encoded}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': self.refresh_token
            }
            
            response = requests.post(SchwabConfig.TOKEN_URL, headers=headers, data=data)
            
            if response.status_code == 200:
                tokens = response.json()
                self.access_token = tokens['access_token']
                self.token_expiry = datetime.now() + timedelta(seconds=tokens.get('expires_in', 1800))
                self._save_tokens()
                return True
                
        except Exception as e:
            self.status_updated.emit(f"Token refresh error: {e}")
            
        return False
        
    def _ensure_token(self) -> bool:
        """Ensure we have a valid token"""
        if not self.access_token:
            return False
            
        if self.token_expiry and datetime.now() >= self.token_expiry - timedelta(minutes=5):
            return self._refresh_access_token()
            
        return True
        
    def set_symbol(self, symbol: str):
        self.symbol = symbol
        
    def set_num_strikes(self, num: int):
        self.num_strikes = num
        
    def set_interval(self, interval: int):
        self.interval = interval
        
    def set_expiration(self, expiration: str):
        """Set a single expiration date (format: YYYY-MM-DD)"""
        self.expirations = [expiration] if expiration else []
        
    def set_expirations(self, expirations: List[str]):
        """Set multiple expiration dates to aggregate"""
        self.expirations = expirations if expirations else []
        
    def fetch_expirations(self) -> List[str]:
        """Fetch available expiration dates for the current symbol"""
        import requests
        
        if not self._ensure_token():
            return []
            
        symbol = SchwabConfig.SYMBOL_MAP.get(self.symbol, self.symbol)
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json'
        }
        
        # Get option chain to find expirations
        chain_url = f"{SchwabConfig.BASE_URL}/chains"
        
        params = {
            'symbol': symbol,
            'contractType': 'ALL',
            'strikeCount': 1,  # Minimal data, just need expirations
            'includeUnderlyingQuote': 'true',
        }
        
        try:
            response = requests.get(chain_url, headers=headers, params=params)
            
            if response.status_code == 200:
                chain_data = response.json()
                
                # Extract expiration dates from call and put maps
                expirations = set()
                
                call_map = chain_data.get('callExpDateMap', {})
                for exp_key in call_map.keys():
                    # Format: "2024-01-19:5" (date:DTE)
                    date_part = exp_key.split(':')[0]
                    expirations.add(date_part)
                    
                put_map = chain_data.get('putExpDateMap', {})
                for exp_key in put_map.keys():
                    date_part = exp_key.split(':')[0]
                    expirations.add(date_part)
                    
                # Sort and return all available expirations
                sorted_exps = sorted(list(expirations))
                self.status_updated.emit(f"Found {len(sorted_exps)} expirations for {self.symbol}")
                return sorted_exps
            else:
                self.status_updated.emit(f"Failed to fetch expirations: {response.status_code} - {response.text[:200]}")
                return []
                
        except Exception as e:
            self.status_updated.emit(f"Error fetching expirations: {e}")
            return []
        
    def start(self):
        if not self._ensure_token():
            auth_url = self.get_auth_url()
            self.auth_required.emit(auth_url)
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        
    def stop(self):
        self.running = False
        
    def _run(self):
        import requests
        
        exp_str = f"{len(self.expirations)} exp" if self.expirations else "no exp"
        self.status_updated.emit(f"Connecting to Schwab API for {self.symbol} ({exp_str})...")
        
        while self.running:
            if not self._ensure_token():
                self.status_updated.emit("Token expired - please re-authenticate")
                break
                
            try:
                data = self._fetch_option_chain()
                if data:
                    self.data_updated.emit(data)
                    price = data['price']
                    total_gex = sum(data.get('gex', [])) if 'gex' in data else sum(data.get('call_gex', [])) + sum(data.get('put_gex', []))
                    num_strikes = len(data.get('strikes', [])) if 'strikes' in data else len(data.get('call_strikes', [])) + len(data.get('put_strikes', []))
                    self.status_updated.emit(
                        f"{self.symbol}: {price:.2f} | {num_strikes} strikes | {len(self.expirations)} exp | Net GEX: {total_gex/1e6:.1f}M | "
                        f"{datetime.now().strftime('%H:%M:%S')}"
                    )
            except Exception as e:
                self.status_updated.emit(f"API error: {e}")
                import traceback
                traceback.print_exc()
                
            time.sleep(self.interval)
            
    def _fetch_option_chain(self) -> Optional[dict]:
        """Fetch option chain from Schwab API for multiple expirations"""
        import requests
        
        if not self.expirations:
            self.status_updated.emit("No expiration dates selected")
            return None
        
        # Map symbol if needed, otherwise use as-is
        raw_symbol = self.symbol
        symbol = SchwabConfig.SYMBOL_MAP.get(raw_symbol, raw_symbol)
        
        # Calculate strikes per side (total / 2 for each side)
        strikes_per_side = self.num_strikes // 2
        
        print(f"\n=== Fetching {raw_symbol} (API: {symbol}) for {len(self.expirations)} expirations ===")
        print(f"Expirations: {self.expirations}")
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json'
        }
        
        # === FETCH RV AND VIX (once per day) ===
        today = datetime.now().date()
        
        # Fetch Realized Volatility (once per day)
        if not self.rv_fetched_today or self.range_calc.rv_last_updated != today:
            print("Fetching Realized Volatility...")
            # Determine RV symbol: try SPX first, fallback to SPY
            rv_symbol = SchwabConfig.RV_SYMBOL_MAP.get(raw_symbol, '$SPX')
            fallback = SchwabConfig.RV_FALLBACK_MAP.get(rv_symbol, 'SPY')
            self.range_calc.fetch_realized_volatility(headers, rv_symbol, fallback)
            self.rv_fetched_today = True
        
        # Fetch VIX (once per session, could update more frequently)
        if not self.vix_fetched:
            print("Fetching VIX level...")
            self.range_calc.fetch_vix_level(headers)
            self.vix_fetched = True
        
        # Get underlying quote first
        quote_url = f"{SchwabConfig.BASE_URL}/quotes"
        params = {'symbols': symbol}
        
        response = requests.get(quote_url, headers=headers, params=params)
        
        if response.status_code != 200:
            self.status_updated.emit(f"Quote error: {response.status_code}")
            return None
            
        quote_data = response.json()
        
        # Handle different response formats
        price = 0
        if symbol in quote_data:
            price = quote_data[symbol].get('quote', {}).get('lastPrice', 0)
        else:
            for key, val in quote_data.items():
                if isinstance(val, dict) and 'quote' in val:
                    price = val['quote'].get('lastPrice', 0)
                    break
        
        if not price:
            self.status_updated.emit(f"Could not get price for {symbol}")
            return None
            
        # Get strike interval for this symbol
        strike_interval = SchwabConfig.STRIKE_INTERVALS.get(raw_symbol, 
            SchwabConfig.STRIKE_INTERVALS.get(raw_symbol.lstrip('/$'), 
                1 if price < 1000 else 5))
        multiplier = SchwabConfig.MULTIPLIERS.get(raw_symbol,
            SchwabConfig.MULTIPLIERS.get(raw_symbol.lstrip('/$'), 100))
        
        atm = round(price / strike_interval) * strike_interval
        print(f"Price: {price}, ATM: {atm}")
        
        # Aggregate GEX across all expirations
        # Use a single dict: net GEX per strike = call GEX + put GEX (put is negative)
        net_gex_by_strike = {}
        vol_by_strike = {}
        atm_iv = None  # Track ATM implied volatility
        
        chain_url = f"{SchwabConfig.BASE_URL}/chains"
        
        for exp_idx, expiration in enumerate(self.expirations):
            print(f"  Fetching expiration: {expiration}")
            
            params = {
                'symbol': symbol,
                'contractType': 'ALL',
                'strikeCount': self.num_strikes + 20,
                'includeUnderlyingQuote': 'true',
                'strategy': 'SINGLE',
                'range': 'ALL',
                'fromDate': expiration,
                'toDate': expiration,
            }
            
            response = requests.get(chain_url, headers=headers, params=params, timeout=15)
            
            if response.status_code != 200:
                print(f"    Error fetching {expiration}: {response.status_code}")
                continue
                
            chain_data = response.json()
            call_map = chain_data.get('callExpDateMap', {})
            put_map = chain_data.get('putExpDateMap', {})
            
            # Process calls - positive GEX at every strike
            for exp_date, strikes in call_map.items():
                for strike_str, options in strikes.items():
                    strike = float(strike_str)
                    opt = options[0] if options else {}
                    gamma = opt.get('gamma', 0) or 0
                    oi = opt.get('openInterest', 0) or 0
                    vol = opt.get('totalVolume', 0) or 0
                    iv = opt.get('volatility', 0) or 0
                    gex = gamma * oi * (price ** 2) * 0.01 * multiplier
                    
                    net_gex_by_strike[strike] = net_gex_by_strike.get(strike, 0) + gex
                    vol_by_strike[strike] = vol_by_strike.get(strike, 0) + vol
                    
                    # Capture ATM IV from nearest expiration
                    if exp_idx == 0 and strike == atm and iv > 0:
                        atm_iv = iv / 100.0
                        
            # Process puts - negative GEX at every strike
            for exp_date, strikes in put_map.items():
                for strike_str, options in strikes.items():
                    strike = float(strike_str)
                    opt = options[0] if options else {}
                    gamma = opt.get('gamma', 0) or 0
                    oi = opt.get('openInterest', 0) or 0
                    vol = opt.get('totalVolume', 0) or 0
                    iv = opt.get('volatility', 0) or 0
                    gex = -gamma * oi * (price ** 2) * 0.01 * multiplier
                    
                    net_gex_by_strike[strike] = net_gex_by_strike.get(strike, 0) + gex
                    vol_by_strike[strike] = vol_by_strike.get(strike, 0) + vol
                    
                    # Average call/put ATM IV from nearest expiration
                    if exp_idx == 0 and strike == atm and iv > 0:
                        if atm_iv is not None:
                            atm_iv = (atm_iv + iv / 100.0) / 2
                        else:
                            atm_iv = iv / 100.0
            
            print(f"    Got {len(call_map)} call exp, {len(put_map)} put exp")
        
        # Select strikes_per_side nearest above ATM and below ATM, plus ATM itself
        all_strike_keys = sorted(net_gex_by_strike.keys())
        
        strikes_above = [s for s in all_strike_keys if s > atm][:strikes_per_side]
        strikes_below = [s for s in reversed(all_strike_keys) if s < atm][:strikes_per_side]
        strikes_below.reverse()  # Back to low-to-high
        
        # Build combined arrays: below ATM + ATM + above ATM
        all_strikes = strikes_below + [atm] + strikes_above
        all_gex = [net_gex_by_strike.get(s, 0) for s in all_strikes]
        all_volume = [vol_by_strike.get(s, 0) for s in all_strikes]
        
        # Derive call/put strike/gex/volume arrays for Top 5 widget compatibility
        call_strikes_sorted = strikes_above
        put_strikes_sorted = strikes_below
        call_gex = [net_gex_by_strike.get(s, 0) for s in call_strikes_sorted]
        put_gex = [net_gex_by_strike.get(s, 0) for s in put_strikes_sorted]
        call_volume = [vol_by_strike.get(s, 0) for s in call_strikes_sorted]
        put_volume = [vol_by_strike.get(s, 0) for s in put_strikes_sorted]
        
        # Calculate gamma flip level (zero crossing)
        gamma_flip = None
        for i in range(len(all_strikes) - 1):
            if (all_gex[i] < 0 and all_gex[i + 1] > 0) or (all_gex[i] > 0 and all_gex[i + 1] < 0):
                # Linear interpolation to find exact zero crossing
                s1, g1 = all_strikes[i], all_gex[i]
                s2, g2 = all_strikes[i + 1], all_gex[i + 1]
                gamma_flip = s1 + (s2 - s1) * (0 - g1) / (g2 - g1)
                break
        
        # Find highest GEX strike (Call Wall) and lowest GEX strike (Put Wall)
        call_wall = None
        put_wall = None
        if all_gex:
            max_gex_idx = np.argmax(all_gex)
            min_gex_idx = np.argmin(all_gex)
            call_wall = all_strikes[max_gex_idx]
            put_wall = all_strikes[min_gex_idx]
        
        # Calculate GEX ratio (put GEX / call GEX)
        total_call_gex = sum(g for g in all_gex if g > 0)
        total_put_gex = abs(sum(g for g in all_gex if g < 0))
        gex_ratio = total_put_gex / total_call_gex if total_call_gex > 0 else 0
        
        # Calculate volume-based P/C ratio (put volume / call volume)
        total_call_volume = sum(call_volume)
        total_put_volume = sum(put_volume)
        pc_ratio = total_put_volume / total_call_volume if total_call_volume > 0 else 0
        
        # === Calculate 1D Expected Move (MenthorQ-style) ===
        # Default IV if not available
        if atm_iv is None or atm_iv <= 0:
            atm_iv = 0.16  # Default 16% IV
        
        # Use OneDayRangeCalculator with spot-weighted gamma
        range_data = self.range_calc.calculate_1d_range(
            price=price,
            atm_iv=atm_iv,
            strikes=all_strikes,
            gex_values=all_gex
        )
        
        one_d_max = range_data['one_d_max']
        one_d_min = range_data['one_d_min']
        
        # Enhanced logging with GPT fixes info
        print(f"Final: {len(put_strikes_sorted)} puts + 1 ATM + {len(call_strikes_sorted)} calls = {len(all_strikes)} total")
        print(f"IV: {atm_iv*100:.1f}%, RV: {self.range_calc.rv_20d*100:.1f}% (vol_adj: {range_data['vol_adjustment']:.2f})")
        print(f"VIX: {self.range_calc.vix_level:.1f}, Multiplier: {range_data['multiplier']:.2f}")
        print(f"Gamma Ratio: {range_data['gamma_ratio']:.2f}, Gamma Mod: {range_data['gamma_modifier']:.2f}, Skew: {range_data['skew']:.2f}")
        print(f"1D Range: {one_d_min:.2f} - {one_d_max:.2f} (↑{range_data['up_move']:.1f} / ↓{range_data['down_move']:.1f} pts)")
        
        if not call_strikes_sorted and not put_strikes_sorted:
            self.status_updated.emit(f"No options found for {symbol}")
            return None
        
        return {
            'timestamp': datetime.now(),
            'symbol': raw_symbol,
            'price': price,
            'atm': atm,
            'iv': atm_iv,
            'rv': self.range_calc.rv_20d,
            'vix': self.range_calc.vix_level,
            'one_d_max': one_d_max,
            'one_d_min': one_d_min,
            'expected_move': range_data['expected_move'],
            'up_move': range_data['up_move'],
            'down_move': range_data['down_move'],
            'vol_adjustment': range_data['vol_adjustment'],
            'gamma_modifier': range_data['gamma_modifier'],
            'gamma_ratio': range_data['gamma_ratio'],
            'skew': range_data['skew'],
            'gamma_flip': gamma_flip,
            'call_wall': call_wall,
            'put_wall': put_wall,
            'gex_ratio': gex_ratio,
            'pc_ratio': pc_ratio,
            'expirations': self.expirations,
            'strikes': all_strikes,
            'gex': all_gex,
            'volume': all_volume,
            'call_strikes': call_strikes_sorted,
            'put_strikes': put_strikes_sorted,
            'call_gex': call_gex,
            'put_gex': put_gex,
            'call_volume': call_volume,
            'put_volume': put_volume,
        }


# ============================================================
# GEX HEATMAP WIDGET
# ============================================================

class GEXHeatmapWidget(QWidget):
    """
    Heatmap visualization with:
    - X axis: Time
    - Y axis: Strike prices (puts below, calls above)
    - Color: Green (positive GEX) to Red (negative GEX)
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.history: deque = deque(maxlen=1000)  # ~16 hours at 1min
        self.timestamps: List[datetime] = []
        self.num_strikes = 100
        self._y_lo: float = None
        self._y_hi: float = None
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Split into two separate Qt widgets so bars can NEVER bleed into the heatmap.
        # A shared QGraphicsScene/grid-layout cannot guarantee pixel-level clipping of
        # BarGraphItem children. Two separate GraphicsLayoutWidgets with a fixed-width
        # bar widget eliminates the problem entirely at the Qt layout level.
        h_layout = QHBoxLayout()
        h_layout.setSpacing(2)
        h_layout.setContentsMargins(0, 0, 0, 0)

        # ── Heatmap widget (stretches to fill available space) ────────
        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setBackground('#0a0a0a')
        h_layout.addWidget(self.graphics, stretch=1)

        # ── Bar chart widget (fixed 180px, never grows) ───────────────
        self.bar_graphics = pg.GraphicsLayoutWidget()
        self.bar_graphics.setBackground('#0a0a0a')
        self.bar_graphics.setFixedWidth(180)
        h_layout.addWidget(self.bar_graphics, stretch=0)

        layout.addLayout(h_layout)

        # Time axis
        self.time_axis = TimeAxisItem(orientation='bottom')

        # === Heatmap plot (in heatmap widget) ===
        self.plot = self.graphics.addPlot(
            row=0, col=0, rowspan=2,
            axisItems={'bottom': self.time_axis}
        )
        self.plot.setLabel('left', 'Strike Price', color='#aaa')
        self.plot.setLabel('bottom', 'Time', color='#aaa')
        self.plot.showGrid(x=True, y=True, alpha=0.15)

        # === Bar chart plot (in its own widget) ===
        self.bar_plot = self.bar_graphics.addPlot(row=0, col=0, rowspan=2)
        self.bar_plot.setLabel('bottom', 'Net GEX', color='#aaa')
        self.bar_plot.showGrid(x=True, y=True, alpha=0.15)
        self.bar_plot.hideAxis('left')
        self.bar_plot.getAxis('left').setWidth(0)

        # The two widgets are physically separate, so their bottom axes can
        # auto-size to different heights (timestamps vs. short numbers), which
        # shifts the bar plot area relative to the heatmap area.
        # Locking both bottom axes to the same fixed pixel height guarantees
        # the plot areas always start at the same pixel Y position.
        BOTTOM_AXIS_HEIGHT = 48
        self.plot.getAxis('bottom').setHeight(BOTTOM_AXIS_HEIGHT)
        self.bar_plot.getAxis('bottom').setHeight(BOTTOM_AXIS_HEIGHT)

        # Connect heatmap ViewBox sigYRangeChanged → mirror to bar_plot immediately.
        # This fires after every pyqtgraph layout pass, so it is the last word
        # on bar_plot Y — no explicit calls in update methods can achieve that.
        self.plot.getViewBox().sigYRangeChanged.connect(self._on_heatmap_y_changed)
        
        # Create lookup table for red-black-green gradient
        # 256 entries: 0-127 = red to black, 128-255 = black to green
        lut = np.zeros((256, 4), dtype=np.ubyte)
        
        # Red to black (negative GEX)
        for i in range(128):
            t = i / 127.0  # 0 to 1
            # Deep red -> Black
            lut[i, 0] = int(180 * (1 - t))  # R: 180 -> 0
            lut[i, 1] = int(30 * (1 - t))   # G: 30 -> 0
            lut[i, 2] = int(30 * (1 - t))   # B: 30 -> 0
            lut[i, 3] = 255
        
        # Black to green (positive GEX)
        for i in range(128, 256):
            t = (i - 128) / 127.0  # 0 to 1
            # Black -> Deep green
            lut[i, 0] = int(30 * t)   # R: 0 -> 30
            lut[i, 1] = int(180 * t)  # G: 0 -> 180
            lut[i, 2] = int(30 * t)   # B: 0 -> 30
            lut[i, 3] = 255
        
        self.lut = lut
        
        # Heatmap image
        self.heatmap = pg.ImageItem()
        self.heatmap.setLookupTable(self.lut)
        self.heatmap.setZValue(-100)  # Put behind other elements
        self.plot.addItem(self.heatmap)
        
        # Price line (white) - on top
        self.price_line = pg.PlotDataItem(
            pen=pg.mkPen('#ffffff', width=2.5),
            antialias=True
        )
        self.price_line.setZValue(100)
        self.plot.addItem(self.price_line)
        
        # Current price marker
        self.price_marker = pg.ScatterPlotItem(
            size=12,
            brush=pg.mkBrush('#ffffff'),
            pen=pg.mkPen('#000000', width=1)
        )
        self.price_marker.setZValue(101)
        self.plot.addItem(self.price_marker)
        
        # 1D Max line (cyan) - on heatmap and bar chart
        self.one_d_max_line = pg.InfiniteLine(
            angle=0,
            pen=pg.mkPen('#00ffff', width=1.5, style=Qt.PenStyle.DashLine),
        )
        self.one_d_max_line.setZValue(49)
        self.plot.addItem(self.one_d_max_line)
        
        self.one_d_max_line_bar = pg.InfiniteLine(
            angle=0,
            pen=pg.mkPen('#00ffff', width=1.5, style=Qt.PenStyle.DashLine),
        )
        self.one_d_max_line_bar.setZValue(49)
        self.bar_plot.addItem(self.one_d_max_line_bar)
        
        # 1D Min line (magenta) - on heatmap and bar chart
        self.one_d_min_line = pg.InfiniteLine(
            angle=0,
            pen=pg.mkPen('#ff00ff', width=1.5, style=Qt.PenStyle.DashLine),
        )
        self.one_d_min_line.setZValue(49)
        self.plot.addItem(self.one_d_min_line)
        
        self.one_d_min_line_bar = pg.InfiniteLine(
            angle=0,
            pen=pg.mkPen('#ff00ff', width=1.5, style=Qt.PenStyle.DashLine),
        )
        self.one_d_min_line_bar.setZValue(49)
        self.bar_plot.addItem(self.one_d_min_line_bar)
        
        # Price line on bar chart too
        self.price_line_bar = pg.InfiniteLine(
            angle=0,
            pen=pg.mkPen('#ffffff', width=2),
        )
        self.price_line_bar.setZValue(100)
        self.bar_plot.addItem(self.price_line_bar)
        
        # Gamma Flip line (orange) - on heatmap and bar chart  
        self.gamma_flip_line = pg.InfiniteLine(
            angle=0,
            pen=pg.mkPen('#ff8800', width=2, style=Qt.PenStyle.DashLine),
        )
        self.gamma_flip_line.setZValue(50)
        self.plot.addItem(self.gamma_flip_line)
        
        self.gamma_flip_line_bar = pg.InfiniteLine(
            angle=0,
            pen=pg.mkPen('#ff8800', width=2, style=Qt.PenStyle.DashLine),
        )
        self.gamma_flip_line_bar.setZValue(50)
        self.bar_plot.addItem(self.gamma_flip_line_bar)
        
        # Store bar items for cleanup
        self._bar_items = []
        
    def set_num_strikes(self, num: int):
        self.num_strikes = num
        
    def update_data(self, data: dict):
        """Update heatmap with new data"""
        print(f"\n=== Heatmap received data ===")
        print(f"Symbol: {data.get('symbol')}, Price: {data.get('price')}, ATM: {data.get('atm')}")
        
        # Check for new combined format
        if 'strikes' in data and 'gex' in data:
            print(f"Total strikes: {len(data['strikes'])}")
            print(f"Strike range: {data['strikes'][0]} to {data['strikes'][-1]}")
        else:
            print(f"Calls: {len(data.get('call_strikes', []))}, Puts: {len(data.get('put_strikes', []))}")
        
        self.history.append(data)
        self.timestamps = [h['timestamp'] for h in self.history]
        self.time_axis.set_timestamps(self.timestamps)
        
        self._update_heatmap()
        self._update_price_line()
        self._update_bar_chart(data)
        
        # Update Gamma Flip lines on both plots
        if data.get('gamma_flip'):
            self.gamma_flip_line.setValue(data['gamma_flip'])
            self.gamma_flip_line_bar.setValue(data['gamma_flip'])
        
        # Update 1D Min/Max lines on both plots
        if data.get('one_d_max'):
            self.one_d_max_line.setValue(data['one_d_max'])
            self.one_d_max_line_bar.setValue(data['one_d_max'])
        if data.get('one_d_min'):
            self.one_d_min_line.setValue(data['one_d_min'])
            self.one_d_min_line_bar.setValue(data['one_d_min'])
        
        # Update price line on bar chart
        if data.get('price'):
            self.price_line_bar.setValue(data['price'])
        
        # Calculate totals
        if 'gex' in data:
            total_call_gex = sum(g for g in data['gex'] if g > 0)
            total_put_gex = sum(g for g in data['gex'] if g < 0)
        else:
            total_call_gex = sum(data.get('call_gex', []))
            total_put_gex = sum(data.get('put_gex', []))
            
        return {
            'price': data['price'],
            'atm': data.get('atm', data['price']),
            'iv': data.get('iv', 0),
            'rv': data.get('rv', 0),
            'vix': data.get('vix', 0),
            'one_d_max': data.get('one_d_max', 0),
            'one_d_min': data.get('one_d_min', 0),
            'expected_move': data.get('expected_move', 0),
            'up_move': data.get('up_move', 0),
            'down_move': data.get('down_move', 0),
            'vol_adjustment': data.get('vol_adjustment', 1.0),
            'gamma_modifier': data.get('gamma_modifier', 1.0),
            'gamma_ratio': data.get('gamma_ratio', 0),
            'skew': data.get('skew', 0),
            'gamma_flip': data.get('gamma_flip', None),
            'call_wall': data.get('call_wall', None),
            'put_wall': data.get('put_wall', None),
            'pc_ratio': data.get('pc_ratio', 0),
            'gex_ratio': data.get('gex_ratio', 0),
            'total_call_gex': total_call_gex,
            'total_put_gex': total_put_gex,
        }
    
    def _on_heatmap_y_changed(self, vb, y_range):
        """Mirror heatmap Y range to bar_plot after every ViewBox layout pass."""
        y_lo, y_hi = y_range
        if y_hi > y_lo:
            self.bar_plot.blockSignals(True)
            self.bar_plot.setYRange(y_lo, y_hi, padding=0)
            self.bar_plot.enableAutoRange(axis='y', enable=False)
            self.bar_plot.blockSignals(False)

    def _update_bar_chart(self, data: dict):
        """Update the Net GEX bar chart - single BarGraphItem for all strikes."""
        if 'strikes' not in data or 'gex' not in data:
            return

        strikes = data['strikes']
        gex_values = data['gex']

        if not strikes:
            return

        strikes_arr = np.array(strikes, dtype=float)
        gex_arr = np.array(gex_values, dtype=float)

        # Use the true minimum gap between any two adjacent strikes so bars
        # never overlap even when intervals are non-uniform.  Cap at 85% so
        # there is always a small visual gap between bars.
        if len(strikes_arr) > 1:
            bar_height = float(np.diff(strikes_arr).min()) * 0.85
        else:
            bar_height = 5.0

        # Remove old bar item(s)
        for item in getattr(self, '_bar_items', []):
            self.bar_plot.removeItem(item)
        self._bar_items = []

        # Build per-bar brushes: green for positive GEX, red for negative
        brushes = [
            pg.mkBrush(30, 180, 30, 200) if g >= 0 else pg.mkBrush(180, 30, 30, 200)
            for g in gex_arr
        ]
        pens = [
            pg.mkPen(60, 210, 60, 255, width=0.5) if g >= 0 else pg.mkPen(210, 60, 60, 255, width=0.5)
            for g in gex_arr
        ]

        # Single BarGraphItem with full arrays — avoids per-item addItem overhead
        # and lets pyqtgraph clip all bars uniformly inside one ViewBox render pass.
        bar = pg.BarGraphItem(
            x0=np.zeros(len(strikes_arr)),
            y=strikes_arr,                               # center of each bar (BarGraphItem treats y as center)
            height=bar_height,
            width=gex_arr,
            brushes=brushes,
            pens=pens
        )
        self.bar_plot.addItem(bar)
        self._bar_items.append(bar)

        # X autorange fits bar widths. Y is kept in sync by _on_heatmap_y_changed.
        self.bar_plot.enableAutoRange(axis='x', enable=True)
        self.bar_plot.enableAutoRange(axis='y', enable=False)
    
    def _update_heatmap(self):
        """Rebuild heatmap from history"""
        if len(self.history) < 1:
            return
            
        # Get all unique strikes across history
        all_strikes = set()
        for h in self.history:
            # Support both combined and separate formats
            if 'strikes' in h:
                all_strikes.update(h['strikes'])
            else:
                all_strikes.update(h.get('put_strikes', []))
                all_strikes.update(h.get('call_strikes', []))
            
        if not all_strikes:
            print("No strikes found in history!")
            return
            
        strikes = np.array(sorted(all_strikes))
        if len(strikes) < 1:
            return
            
        n_strikes = len(strikes)
        n_times = max(len(self.history), 2)  # At least 2 for display
        
        print(f"\n=== Building Heatmap ===")
        print(f"Time points: {len(self.history)}, Strikes: {n_strikes}")
        print(f"Strike range: {strikes[0]} to {strikes[-1]}")
        
        # Build heatmap matrix (rows=strikes, cols=time)
        heatmap_data = np.zeros((n_strikes, n_times))
        strike_to_idx = {s: i for i, s in enumerate(strikes)}
        
        for t_idx, h in enumerate(self.history):
            # Support both combined and separate formats
            if 'strikes' in h and 'gex' in h:
                for strike, gex in zip(h['strikes'], h['gex']):
                    if strike in strike_to_idx:
                        heatmap_data[strike_to_idx[strike], t_idx] = gex
            else:
                # Old format with separate put/call
                for strike, gex in zip(h.get('put_strikes', []), h.get('put_gex', [])):
                    if strike in strike_to_idx:
                        heatmap_data[strike_to_idx[strike], t_idx] = gex
                for strike, gex in zip(h.get('call_strikes', []), h.get('call_gex', [])):
                    if strike in strike_to_idx:
                        heatmap_data[strike_to_idx[strike], t_idx] = gex
        
        # If only 1 time point, duplicate for display
        if len(self.history) == 1:
            heatmap_data[:, 1] = heatmap_data[:, 0]
                    
        # FIX #1 & #2: Use raw GEX values with configurable saturation
        # MAGNITUDE SCALING OPTIONS:
        # - "max": Use absolute max (shows full range, but mid-values very dark)
        # - "p99": Use 99th percentile (clips top 1%, better mid-range visibility)
        # - "p95": Use 95th percentile (clips top 5%, best mid-range visibility)
        
        saturation_mode = "p99"  # ← ADJUST THIS: "max", "p99", or "p95"
        
        abs_values = np.abs(heatmap_data[heatmap_data != 0])
        if len(abs_values) > 0:
            if saturation_mode == "max":
                max_abs_gex = np.max(abs_values)
            elif saturation_mode == "p99":
                max_abs_gex = np.percentile(abs_values, 99)
            elif saturation_mode == "p95":
                max_abs_gex = np.percentile(abs_values, 95)
            else:
                max_abs_gex = np.max(abs_values)
        else:
            max_abs_gex = 1e6  # Default if no data
        
        if max_abs_gex == 0:
            max_abs_gex = 1e6
        
        # Map to -1 to +1 range (negative=red, zero=black, positive=green)
        # Values beyond threshold will be clipped (saturated color)
        normalized = np.clip(heatmap_data / max_abs_gex, -1.0, 1.0)
        
        # Scale to 0-255 where: 0=max negative, 127=zero, 255=max positive
        img_scaled = ((normalized + 1.0) * 127.5).astype(np.uint8)
        
        print(f"Raw GEX range: {heatmap_data.min()/1e6:.1f}M to {heatmap_data.max()/1e6:.1f}M")
        print(f"Saturation mode: {saturation_mode}")
        print(f"Saturation threshold: {max_abs_gex/1e6:.1f}M")
        print(f"Values clipped: {np.sum(np.abs(heatmap_data) > max_abs_gex)} pixels")
        print(f"Normalized range: {normalized.min():.3f} to {normalized.max():.3f}")
        print(f"Scaled range: {img_scaled.min()} to {img_scaled.max()} (127=zero)")
        print(f"Zero values properly at 127: {np.sum(img_scaled == 127)} pixels")
        print(f"Matrix shape before transpose: {img_scaled.shape}")
        
        # Transpose: ImageItem expects (x=time, y=strikes)
        img_data = img_scaled.T  # Now shape is (n_times, n_strikes)
        print(f"Matrix shape after transpose: {img_data.shape}")
        
        # Set image data
        self.heatmap.setImage(img_data, autoLevels=False, levels=[0, 255])
        
        # Position and scale the image to match strike prices
        strike_min, strike_max = strikes[0], strikes[-1]
        strike_span = strike_max - strike_min if strike_max != strike_min else 1
        
        # Calculate per-strike height
        if n_strikes > 1:
            strike_height = (strikes[1] - strikes[0])  # Actual strike interval
        else:
            strike_height = strike_interval if 'strike_interval' in locals() else 5
        
        # FIX #3: Set image rect to align with bar chart Y-axis
        # Image pixels should map directly to strike prices
        # setRect(x, y, width, height) where y=bottom strike, height=total range
        from PyQt6.QtCore import QRectF
        y_start = strikes[0] - strike_height / 2  # Start half a strike below lowest
        y_span = n_strikes * strike_height  # Each pixel is exactly one strike interval tall
        rect = QRectF(0, y_start, n_times, y_span)
        self.heatmap.setRect(rect)
        
        print(f"Image rect: x=0, y={y_start:.2f}, w={n_times}, h={y_span:.2f} ({n_strikes} strikes × {strike_height} interval)")
        
        # Set view range - X axis auto-adjusts with time, Y axis fixed to ±1% of current price
        self.plot.setXRange(-0.5, n_times + 0.5, padding=0)
        
        # Get current price from most recent data point
        if self.history:
            current_price = self.history[-1].get('price', strike_min + (strike_max - strike_min) / 2)
            
            # Set Y range to ±1% of current price
            y_range_pct = 0.01  # 1%
            y_min = current_price * (1 - y_range_pct)
            y_max = current_price * (1 + y_range_pct)
            
            self.plot.setYRange(y_min, y_max, padding=0)
            self._y_lo, self._y_hi = y_min, y_max
            print(f"Y-axis fixed to ±1% of current price: {y_min:.2f} to {y_max:.2f} (price: {current_price:.2f})")
        else:
            # Fallback if no history yet
            padding = strike_height * 0.5
            y_min = strike_min - padding
            y_max = strike_max + padding
            self.plot.setYRange(y_min, y_max, padding=0)
            self._y_lo, self._y_hi = y_min, y_max
        
        # Disable auto-range on both so Y stays locked
        self.plot.enableAutoRange(axis='y', enable=False)
        self.plot.enableAutoRange(axis='x', enable=False)
        self.bar_plot.enableAutoRange(axis='y', enable=False)
        
        # Force update
        self.heatmap.update()
        self.plot.update()
        
    def _update_price_line(self):
        """Update the price line overlay"""
        if len(self.history) < 1:
            return
            
        x = list(range(len(self.history)))
        y = [h['price'] for h in self.history]
        
        # Duplicate first point if only one data point
        if len(x) == 1:
            x = [0, 1]
            y = [y[0], y[0]]
        
        self.price_line.setData(x, y)
        
        if self.history:
            last_x = len(self.history) - 1 if len(self.history) > 1 else 0.5
            self.price_marker.setData([last_x], [self.history[-1]['price']])
            
    def clear_history(self):
        """Clear all history and reset display"""
        self.history.clear()
        self.timestamps.clear()
        
        # Clear visual elements
        self.heatmap.clear()
        self.price_line.clear()
        self.price_marker.clear()
        
        # Clear bar chart items
        for item in getattr(self, '_bar_items', []):
            self.bar_plot.removeItem(item)
        self._bar_items = []
        
        # Re-enable auto-range for next data
        self.plot.enableAutoRange(axis='y', enable=True)
        self.plot.enableAutoRange(axis='x', enable=True)
        self.bar_plot.enableAutoRange(axis='x', enable=True)
        self.bar_plot.enableAutoRange(axis='y', enable=True)
    
    def export_to_csv(self, filepath: str) -> bool:
        """Export history to CSV file"""
        if not self.history:
            return False
            
        try:
            with open(filepath, 'w', newline='') as f:
                import csv
                writer = csv.writer(f)
                
                # Write header
                header = ['timestamp', 'symbol', 'price', 'atm']
                
                # Get all unique strikes from first entry
                if self.history:
                    first = self.history[0]
                    if 'strikes' in first:
                        strikes = first['strikes']
                        for strike in strikes:
                            header.append(f'GEX_{strike}')
                
                writer.writerow(header)
                
                # Write data rows
                for entry in self.history:
                    row = [
                        entry['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                        entry.get('symbol', ''),
                        entry.get('price', ''),
                        entry.get('atm', ''),
                    ]
                    
                    if 'gex' in entry:
                        row.extend(entry['gex'])
                    
                    writer.writerow(row)
                    
            return True
        except Exception as e:
            print(f"Error exporting to CSV: {e}")
            return False
    
    def save_history_to_file(self, symbol: str = None):
        """
        Save current day's history to a file.
        Creates one file per symbol per day.
        """
        if not self.history:
            print("No history to save")
            return False
        
        try:
            # Create history directory if it doesn't exist
            os.makedirs(SchwabConfig.HISTORY_DIR, exist_ok=True)
            
            # Get symbol from history if not provided
            if symbol is None:
                symbol = self.history[0].get('symbol', 'UNKNOWN')
            
            # Get date from first entry
            today = self.history[0]['timestamp'].date()
            
            # Create filename: SYMBOL_YYYY-MM-DD.pkl
            filename = f"{symbol}_{today.strftime('%Y-%m-%d')}.pkl"
            filepath = os.path.join(SchwabConfig.HISTORY_DIR, filename)
            
            # Convert deque to list for pickling
            history_data = {
                'symbol': symbol,
                'date': today,
                'history': list(self.history),
                'saved_at': datetime.now()
            }
            
            with open(filepath, 'wb') as f:
                pickle.dump(history_data, f)
            
            print(f"✓ Saved history to: {filepath}")
            print(f"  Records: {len(self.history)}, Date: {today}")
            return True
            
        except Exception as e:
            print(f"Error saving history: {e}")
            return False
    
    def load_history_from_file(self, symbol: str, date: datetime.date = None):
        """
        Load history from a specific date.
        If date is None, loads today's history if it exists.
        """
        try:
            if date is None:
                date = datetime.now().date()
            
            # Create filename
            filename = f"{symbol}_{date.strftime('%Y-%m-%d')}.pkl"
            filepath = os.path.join(SchwabConfig.HISTORY_DIR, filename)
            
            if not os.path.exists(filepath):
                print(f"No saved history found for {symbol} on {date}")
                return False
            
            with open(filepath, 'rb') as f:
                history_data = pickle.load(f)
            
            # Load the history
            self.history = deque(history_data['history'], maxlen=1000)
            self.timestamps = [h['timestamp'] for h in self.history]
            self.time_axis.set_timestamps(self.timestamps)
            
            # Update display
            self._update_heatmap()
            self._update_price_line()
            if self.history:
                self._update_bar_chart(self.history[-1])
            
            print(f"✓ Loaded history from: {filepath}")
            print(f"  Records: {len(self.history)}, Date: {history_data['date']}")
            return True
            
        except Exception as e:
            print(f"Error loading history: {e}")
            return False
    
    def load_multi_day_history(self, symbol: str, days: int = 5):
        """
        Load history from multiple previous days and combine them.
        
        Args:
            symbol: Symbol to load (e.g., "SPY")
            days: Number of days to load (default 5, max based on HISTORY_DAYS_TO_KEEP)
        """
        try:
            days = min(days, SchwabConfig.HISTORY_DAYS_TO_KEEP)
            combined_history = []
            
            # Load from most recent to oldest
            for i in range(days):
                target_date = datetime.now().date() - timedelta(days=i)
                filename = f"{symbol}_{target_date.strftime('%Y-%m-%d')}.pkl"
                filepath = os.path.join(SchwabConfig.HISTORY_DIR, filename)
                
                if os.path.exists(filepath):
                    with open(filepath, 'rb') as f:
                        history_data = pickle.load(f)
                        combined_history.extend(history_data['history'])
                        print(f"  Loaded {len(history_data['history'])} records from {target_date}")
            
            if combined_history:
                # Sort by timestamp
                combined_history.sort(key=lambda x: x['timestamp'])
                
                # Update history
                self.history = deque(combined_history, maxlen=1000)
                self.timestamps = [h['timestamp'] for h in self.history]
                self.time_axis.set_timestamps(self.timestamps)
                
                # Update display
                self._update_heatmap()
                self._update_price_line()
                if self.history:
                    self._update_bar_chart(self.history[-1])
                
                print(f"✓ Loaded {len(combined_history)} total records from {days} days")
                return True
            else:
                print(f"No history found for {symbol} in the last {days} days")
                return False
                
        except Exception as e:
            print(f"Error loading multi-day history: {e}")
            return False
    
    def cleanup_old_history(self):
        """
        Delete history files older than HISTORY_DAYS_TO_KEEP.
        Runs automatically on startup.
        """
        try:
            if not os.path.exists(SchwabConfig.HISTORY_DIR):
                return
            
            cutoff_date = datetime.now().date() - timedelta(days=SchwabConfig.HISTORY_DAYS_TO_KEEP)
            deleted_count = 0
            
            for filename in os.listdir(SchwabConfig.HISTORY_DIR):
                if filename.endswith('.pkl'):
                    try:
                        # Extract date from filename (SYMBOL_YYYY-MM-DD.pkl)
                        date_str = filename.split('_', 1)[1].replace('.pkl', '')
                        file_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                        
                        if file_date < cutoff_date:
                            filepath = os.path.join(SchwabConfig.HISTORY_DIR, filename)
                            os.remove(filepath)
                            deleted_count += 1
                            print(f"  Deleted old history: {filename}")
                    except:
                        pass  # Skip malformed filenames
            
            if deleted_count > 0:
                print(f"✓ Cleaned up {deleted_count} old history files")
                
        except Exception as e:
            print(f"Error cleaning up old history: {e}")


# ============================================================
# TOP 5 WIDGET - Shows Top 5 Gamma/Volume Charts
# ============================================================

class Top5Widget(QWidget):
    """
    Widget showing:
    - Left: Net GEX bar chart
    - Top middle: Top 5 Gamma Puts (most negative)
    - Top right: Top 5 Gamma Calls (most positive)
    - Bottom middle: Top 5 Volume Puts
    - Bottom right: Top 5 Volume Calls
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.history: deque = deque(maxlen=1000)
        self.timestamps: List[datetime] = []
        # Opacity map: 1st=100%, 2nd=65%, 3rd=40%, 4th=25%, 5th=15%
        self.opacity_map = {0: 255, 1: 166, 2: 102, 3: 64, 4: 38}
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Graphics widget
        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setBackground('#0a0a0a')
        layout.addWidget(self.graphics)
        
        # === LEFT COLUMN: Net GEX Bar Chart ===
        self.bar_plot = self.graphics.addPlot(row=0, col=0, rowspan=2)
        self.bar_plot.setLabel('left', 'Strike', color='#aaa')
        self.bar_plot.setLabel('bottom', 'Net GEX', color='#aaa')
        self.bar_plot.showGrid(x=True, y=True, alpha=0.15)
        self.bar_plot.setMaximumWidth(250)
        self._bar_items = []
        
        # Price line on bar chart
        self.price_line_bar = pg.InfiniteLine(
            angle=0,
            pen=pg.mkPen('#ffffff', width=2),
        )
        self.price_line_bar.setZValue(100)
        self.bar_plot.addItem(self.price_line_bar)
        
        # 1D Max line (cyan) on bar chart
        self.one_d_max_line_bar = pg.InfiniteLine(
            angle=0,
            pen=pg.mkPen('#00ffff', width=1.5, style=Qt.PenStyle.DashLine),
        )
        self.one_d_max_line_bar.setZValue(49)
        self.bar_plot.addItem(self.one_d_max_line_bar)
        
        # 1D Min line (magenta) on bar chart
        self.one_d_min_line_bar = pg.InfiniteLine(
            angle=0,
            pen=pg.mkPen('#ff00ff', width=1.5, style=Qt.PenStyle.DashLine),
        )
        self.one_d_min_line_bar.setZValue(49)
        self.bar_plot.addItem(self.one_d_min_line_bar)
        
        # === TOP MIDDLE: Gamma Puts ===
        self.gamma_put_axis = TimeAxisItem(orientation='bottom')
        self.gamma_put_plot = self.graphics.addPlot(
            row=0, col=1,
            axisItems={'bottom': self.gamma_put_axis}
        )
        self.gamma_put_plot.setTitle('SPX Gamma Puts', color='#ff6666', size='10pt')
        self.gamma_put_plot.setLabel('left', 'Strike', color='#aaa')
        self.gamma_put_plot.showGrid(x=True, y=True, alpha=0.15)
        
        # Gamma put price line
        self.gamma_put_price_line = pg.PlotDataItem(
            pen=pg.mkPen('#ffffff', width=2),
            antialias=True
        )
        self.gamma_put_price_line.setZValue(100)
        self.gamma_put_plot.addItem(self.gamma_put_price_line)
        
        # Gamma put scatter items (5 ranks)
        self.gamma_put_scatters = []
        for rank in range(5):
            opacity = self.opacity_map[rank]
            scatter = pg.ScatterPlotItem(
                size=10 - rank,  # Larger for higher rank
                brush=pg.mkBrush(255, 100, 100, opacity),
                pen=pg.mkPen(255, 50, 50, min(255, opacity + 50), width=0.5)
            )
            scatter.setZValue(90 - rank)
            self.gamma_put_plot.addItem(scatter)
            self.gamma_put_scatters.append(scatter)
        
        # 1D lines on gamma put plot
        self.gamma_put_1d_max = pg.InfiniteLine(angle=0, pen=pg.mkPen('#00ffff', width=1.5, style=Qt.PenStyle.DashLine))
        self.gamma_put_1d_min = pg.InfiniteLine(angle=0, pen=pg.mkPen('#ff00ff', width=1.5, style=Qt.PenStyle.DashLine))
        self.gamma_put_1d_max.setZValue(48)
        self.gamma_put_1d_min.setZValue(48)
        self.gamma_put_plot.addItem(self.gamma_put_1d_max)
        self.gamma_put_plot.addItem(self.gamma_put_1d_min)
        
        # === TOP RIGHT: Gamma Calls ===
        self.gamma_call_axis = TimeAxisItem(orientation='bottom')
        self.gamma_call_plot = self.graphics.addPlot(
            row=0, col=2,
            axisItems={'bottom': self.gamma_call_axis}
        )
        self.gamma_call_plot.setTitle('SPX Gamma Calls', color='#66ff66', size='10pt')
        self.gamma_call_plot.setLabel('left', 'Strike', color='#aaa')
        self.gamma_call_plot.showGrid(x=True, y=True, alpha=0.15)
        
        # Gamma call price line
        self.gamma_call_price_line = pg.PlotDataItem(
            pen=pg.mkPen('#ffffff', width=2),
            antialias=True
        )
        self.gamma_call_price_line.setZValue(100)
        self.gamma_call_plot.addItem(self.gamma_call_price_line)
        
        # Gamma call scatter items (5 ranks)
        self.gamma_call_scatters = []
        for rank in range(5):
            opacity = self.opacity_map[rank]
            scatter = pg.ScatterPlotItem(
                size=10 - rank,
                brush=pg.mkBrush(100, 255, 100, opacity),
                pen=pg.mkPen(50, 255, 50, min(255, opacity + 50), width=0.5)
            )
            scatter.setZValue(90 - rank)
            self.gamma_call_plot.addItem(scatter)
            self.gamma_call_scatters.append(scatter)
        
        # 1D lines on gamma call plot
        self.gamma_call_1d_max = pg.InfiniteLine(angle=0, pen=pg.mkPen('#00ffff', width=1.5, style=Qt.PenStyle.DashLine))
        self.gamma_call_1d_min = pg.InfiniteLine(angle=0, pen=pg.mkPen('#ff00ff', width=1.5, style=Qt.PenStyle.DashLine))
        self.gamma_call_1d_max.setZValue(48)
        self.gamma_call_1d_min.setZValue(48)
        self.gamma_call_plot.addItem(self.gamma_call_1d_max)
        self.gamma_call_plot.addItem(self.gamma_call_1d_min)
        
        # === BOTTOM MIDDLE: Volume Puts ===
        self.vol_put_axis = TimeAxisItem(orientation='bottom')
        self.vol_put_plot = self.graphics.addPlot(
            row=1, col=1,
            axisItems={'bottom': self.vol_put_axis}
        )
        self.vol_put_plot.setTitle('SPX Volume Puts', color='#ff6666', size='10pt')
        self.vol_put_plot.setLabel('left', 'Strike', color='#aaa')
        self.vol_put_plot.showGrid(x=True, y=True, alpha=0.15)
        
        # Volume put price line
        self.vol_put_price_line = pg.PlotDataItem(
            pen=pg.mkPen('#ffffff', width=2),
            antialias=True
        )
        self.vol_put_price_line.setZValue(100)
        self.vol_put_plot.addItem(self.vol_put_price_line)
        
        # Volume put scatter items (5 ranks)
        self.vol_put_scatters = []
        for rank in range(5):
            opacity = self.opacity_map[rank]
            scatter = pg.ScatterPlotItem(
                size=10 - rank,
                brush=pg.mkBrush(255, 100, 100, opacity),
                pen=pg.mkPen(255, 50, 50, min(255, opacity + 50), width=0.5)
            )
            scatter.setZValue(90 - rank)
            self.vol_put_plot.addItem(scatter)
            self.vol_put_scatters.append(scatter)
        
        # 1D lines on volume put plot
        self.vol_put_1d_max = pg.InfiniteLine(angle=0, pen=pg.mkPen('#00ffff', width=1.5, style=Qt.PenStyle.DashLine))
        self.vol_put_1d_min = pg.InfiniteLine(angle=0, pen=pg.mkPen('#ff00ff', width=1.5, style=Qt.PenStyle.DashLine))
        self.vol_put_1d_max.setZValue(48)
        self.vol_put_1d_min.setZValue(48)
        self.vol_put_plot.addItem(self.vol_put_1d_max)
        self.vol_put_plot.addItem(self.vol_put_1d_min)
        
        # === BOTTOM RIGHT: Volume Calls ===
        self.vol_call_axis = TimeAxisItem(orientation='bottom')
        self.vol_call_plot = self.graphics.addPlot(
            row=1, col=2,
            axisItems={'bottom': self.vol_call_axis}
        )
        self.vol_call_plot.setTitle('SPX Volume Calls', color='#66ff66', size='10pt')
        self.vol_call_plot.setLabel('left', 'Strike', color='#aaa')
        self.vol_call_plot.showGrid(x=True, y=True, alpha=0.15)
        
        # Volume call price line
        self.vol_call_price_line = pg.PlotDataItem(
            pen=pg.mkPen('#ffffff', width=2),
            antialias=True
        )
        self.vol_call_price_line.setZValue(100)
        self.vol_call_plot.addItem(self.vol_call_price_line)
        
        # Volume call scatter items (5 ranks)
        self.vol_call_scatters = []
        for rank in range(5):
            opacity = self.opacity_map[rank]
            scatter = pg.ScatterPlotItem(
                size=10 - rank,
                brush=pg.mkBrush(100, 255, 100, opacity),
                pen=pg.mkPen(50, 255, 50, min(255, opacity + 50), width=0.5)
            )
            scatter.setZValue(90 - rank)
            self.vol_call_plot.addItem(scatter)
            self.vol_call_scatters.append(scatter)
        
        # 1D lines on volume call plot
        self.vol_call_1d_max = pg.InfiniteLine(angle=0, pen=pg.mkPen('#00ffff', width=1.5, style=Qt.PenStyle.DashLine))
        self.vol_call_1d_min = pg.InfiniteLine(angle=0, pen=pg.mkPen('#ff00ff', width=1.5, style=Qt.PenStyle.DashLine))
        self.vol_call_1d_max.setZValue(48)
        self.vol_call_1d_min.setZValue(48)
        self.vol_call_plot.addItem(self.vol_call_1d_max)
        self.vol_call_plot.addItem(self.vol_call_1d_min)
        
        # Create legend labels for each plot
        self._add_legend(self.gamma_put_plot, 'GEX Put', 'red')
        self._add_legend(self.gamma_call_plot, 'GEX Call', 'green')
        self._add_legend(self.vol_put_plot, 'Vol Put', 'red')
        self._add_legend(self.vol_call_plot, 'Vol Call', 'green')
    
    def _add_legend(self, plot, prefix, color):
        """Add a simple legend to a plot"""
        # Legend is built into the data display
        pass
        
    def update_data(self, data: dict):
        """Update all charts with new data"""
        self.history.append(data)
        self.timestamps = [h['timestamp'] for h in self.history]
        
        # Update time axes
        self.gamma_put_axis.set_timestamps(self.timestamps)
        self.gamma_call_axis.set_timestamps(self.timestamps)
        self.vol_put_axis.set_timestamps(self.timestamps)
        self.vol_call_axis.set_timestamps(self.timestamps)
        
        # Update title with symbol
        symbol = data.get('symbol', 'SPX')
        self.gamma_put_plot.setTitle(f'{symbol} Gamma Puts', color='#ff6666', size='10pt')
        self.gamma_call_plot.setTitle(f'{symbol} Gamma Calls', color='#66ff66', size='10pt')
        self.vol_put_plot.setTitle(f'{symbol} Volume Puts', color='#ff6666', size='10pt')
        self.vol_call_plot.setTitle(f'{symbol} Volume Calls', color='#66ff66', size='10pt')
        
        # Update bar chart
        self._update_bar_chart(data)
        
        # Update scatter plots
        self._update_scatter_plots()
        
        # Update price line on bar chart
        if data.get('price'):
            self.price_line_bar.setValue(data['price'])
        
        # Update 1D Min/Max lines on all plots
        if data.get('one_d_max'):
            one_d_max = data['one_d_max']
            self.one_d_max_line_bar.setValue(one_d_max)
            self.gamma_put_1d_max.setValue(one_d_max)
            self.gamma_call_1d_max.setValue(one_d_max)
            self.vol_put_1d_max.setValue(one_d_max)
            self.vol_call_1d_max.setValue(one_d_max)
        
        if data.get('one_d_min'):
            one_d_min = data['one_d_min']
            self.one_d_min_line_bar.setValue(one_d_min)
            self.gamma_put_1d_min.setValue(one_d_min)
            self.gamma_call_1d_min.setValue(one_d_min)
            self.vol_put_1d_min.setValue(one_d_min)
            self.vol_call_1d_min.setValue(one_d_min)
        
        # Calculate totals for return
        if 'gex' in data:
            total_call_gex = sum(g for g in data['gex'] if g > 0)
            total_put_gex = sum(g for g in data['gex'] if g < 0)
        else:
            total_call_gex = sum(data.get('call_gex', []))
            total_put_gex = sum(data.get('put_gex', []))
            
        return {
            'price': data['price'],
            'atm': data.get('atm', data['price']),
            'total_call_gex': total_call_gex,
            'total_put_gex': total_put_gex,
        }
    
    def _update_bar_chart(self, data: dict):
        """Update the Net GEX bar chart"""
        if 'strikes' not in data or 'gex' not in data:
            return
            
        strikes = data['strikes']
        gex_values = data['gex']
        
        if not strikes:
            return
        
        # Calculate bar height based on strike interval
        # Use 0.6x interval and center each bar on its strike (y = strike - height/2)
        if len(strikes) > 1:
            strike_interval = strikes[1] - strikes[0]
            bar_height = strike_interval * 0.6
        else:
            strike_interval = 5
            bar_height = 3.0
        
        # Separate and rank
        call_data = [(s, g) for s, g in zip(strikes, gex_values) if g > 0]
        put_data = [(s, g) for s, g in zip(strikes, gex_values) if g < 0]
        
        call_data.sort(key=lambda x: x[1], reverse=True)
        put_data.sort(key=lambda x: x[1])
        
        # Remove old bars
        for item in self._bar_items:
            self.bar_plot.removeItem(item)
        self._bar_items = []
        
        # Create bars with opacity - centered on strike
        for rank, (strike, gex) in enumerate(call_data):
            opacity = self.opacity_map.get(rank, 26)
            bar = pg.BarGraphItem(
                x0=0, y=[strike - bar_height / 2], height=bar_height, width=[gex],
                brush=pg.mkBrush(0, 170, 0, opacity),
                pen=pg.mkPen(0, 255, 0, min(255, opacity + 50), width=0.5)
            )
            self.bar_plot.addItem(bar)
            self._bar_items.append(bar)
        
        for rank, (strike, gex) in enumerate(put_data):
            opacity = self.opacity_map.get(rank, 26)
            bar = pg.BarGraphItem(
                x0=0, y=[strike - bar_height / 2], height=bar_height, width=[gex],
                brush=pg.mkBrush(170, 0, 0, opacity),
                pen=pg.mkPen(255, 0, 0, min(255, opacity + 50), width=0.5)
            )
            self.bar_plot.addItem(bar)
            self._bar_items.append(bar)
        
        # Set Y range
        if strikes:
            self.bar_plot.setYRange(min(strikes), max(strikes), padding=0.02)
        self.bar_plot.enableAutoRange(axis='x', enable=True)
    
    def _update_scatter_plots(self):
        """Update the scatter plots with historical top 5 data"""
        if len(self.history) < 1:
            return
        
        # Build arrays for each rank (0-4) for each chart type
        gamma_put_data = [[] for _ in range(5)]  # List of (x, y) for each rank
        gamma_call_data = [[] for _ in range(5)]
        vol_put_data = [[] for _ in range(5)]
        vol_call_data = [[] for _ in range(5)]
        
        prices_x = []
        prices_y = []
        
        for t_idx, h in enumerate(self.history):
            prices_x.append(t_idx)
            prices_y.append(h['price'])
            
            # Use the full combined arrays — strikes/gex/volume contain net GEX
            # at every strike. Top 5 GEX Calls = 5 most positive net GEX strikes.
            # Top 5 GEX Puts = 5 most negative net GEX strikes.
            # Volume charts split by position relative to ATM (calls above, puts below).
            all_strikes = h.get('strikes', [])
            all_gex = h.get('gex', [])
            all_volume = h.get('volume', [0] * len(all_strikes))
            atm = h.get('atm', h.get('price', 0))
            
            if not all_strikes or not all_gex:
                continue
            
            combined = list(zip(all_strikes, all_gex, all_volume))
            
            # Top 5 GEX Puts: most negative net GEX (sort ascending, take first 5)
            sorted_by_gex_asc = sorted(combined, key=lambda x: x[1])
            for rank, (strike, gex, vol) in enumerate(sorted_by_gex_asc[:5]):
                gamma_put_data[rank].append((t_idx, strike))
            
            # Top 5 GEX Calls: most positive net GEX (sort descending, take first 5)
            sorted_by_gex_desc = sorted(combined, key=lambda x: x[1], reverse=True)
            for rank, (strike, gex, vol) in enumerate(sorted_by_gex_desc[:5]):
                gamma_call_data[rank].append((t_idx, strike))
            
            # Top 5 Volume Puts: highest volume among strikes BELOW ATM
            put_side = [(s, g, v) for s, g, v in combined if s < atm and v > 0]
            put_side.sort(key=lambda x: x[2], reverse=True)
            for rank, (strike, gex, vol) in enumerate(put_side[:5]):
                vol_put_data[rank].append((t_idx, strike))
            
            # Top 5 Volume Calls: highest volume among strikes ABOVE ATM
            call_side = [(s, g, v) for s, g, v in combined if s > atm and v > 0]
            call_side.sort(key=lambda x: x[2], reverse=True)
            for rank, (strike, gex, vol) in enumerate(call_side[:5]):
                vol_call_data[rank].append((t_idx, strike))
        
        # Update scatter plots
        for rank in range(5):
            if gamma_put_data[rank]:
                x = [p[0] for p in gamma_put_data[rank]]
                y = [p[1] for p in gamma_put_data[rank]]
                self.gamma_put_scatters[rank].setData(x, y)
            else:
                self.gamma_put_scatters[rank].clear()
            
            if gamma_call_data[rank]:
                x = [p[0] for p in gamma_call_data[rank]]
                y = [p[1] for p in gamma_call_data[rank]]
                self.gamma_call_scatters[rank].setData(x, y)
            else:
                self.gamma_call_scatters[rank].clear()
            
            if vol_put_data[rank]:
                x = [p[0] for p in vol_put_data[rank]]
                y = [p[1] for p in vol_put_data[rank]]
                self.vol_put_scatters[rank].setData(x, y)
            else:
                self.vol_put_scatters[rank].clear()
            
            if vol_call_data[rank]:
                x = [p[0] for p in vol_call_data[rank]]
                y = [p[1] for p in vol_call_data[rank]]
                self.vol_call_scatters[rank].setData(x, y)
            else:
                self.vol_call_scatters[rank].clear()
        
        # Update price lines
        if prices_x:
            self.gamma_put_price_line.setData(prices_x, prices_y)
            self.gamma_call_price_line.setData(prices_x, prices_y)
            self.vol_put_price_line.setData(prices_x, prices_y)
            self.vol_call_price_line.setData(prices_x, prices_y)
        
        # Auto-range X axes
        if self.timestamps:
            n = len(self.timestamps)
            for plot in [self.gamma_put_plot, self.gamma_call_plot, 
                         self.vol_put_plot, self.vol_call_plot]:
                plot.setXRange(-0.5, n + 0.5, padding=0)
    
    def clear_history(self):
        """Clear all history"""
        self.history.clear()
        self.timestamps.clear()
        
        # Clear scatter plots
        for rank in range(5):
            self.gamma_put_scatters[rank].clear()
            self.gamma_call_scatters[rank].clear()
            self.vol_put_scatters[rank].clear()
            self.vol_call_scatters[rank].clear()
        
        # Clear price lines
        self.gamma_put_price_line.clear()
        self.gamma_call_price_line.clear()
        self.vol_put_price_line.clear()
        self.vol_call_price_line.clear()
        
        # Clear bar chart
        for item in self._bar_items:
            self.bar_plot.removeItem(item)
        self._bar_items = []


# ============================================================
# NET GEX GRID WIDGET
# ============================================================

class SingleGridPanel(QWidget):
    """
    Pure display panel for one symbol's Net GEX Grid.
    No controls — all shared controls live in NetGEXGridWidget.
    Exposes load_grid() as its only public entry point.
    - Rows: 50 strikes centered on ATM (24 below, ATM, 25 above) + Total row
    - Columns: selected expirations + Total column
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_data_feed = None
        self.grid_data = {}
        self.strikes = []
        self.current_price = 0
        self.atm = 0
        self.symbol = ""
        self.selected_expirations = []
        self._top3_cells = set()   # (row, col) cells claimed by top-3 highlight
        self._col_gex = {}         # col_idx -> [gex per strike row, in strike order]
        self._setup_ui()

    # Fixed width for both tables' vertical headers so columns stay aligned
    _VH_WIDTH = 58

    def _setup_ui(self):
        from PyQt6.QtWidgets import QTableWidget, QHeaderView
        from PyQt6.QtCore import Qt

        _TABLE_SS = """
            QTableWidget {
                gridline-color: #333;
                border: 1px solid #444;
            }
            QHeaderView::section {
                background-color: #1a1a1a;
                color: #aaa;
                padding: 4px;
                border: 1px solid #333;
                font-weight: bold;
                font-size: 9px;
            }
        """

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self.title_label = QLabel("—")
        self.title_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #fff; padding: 4px 5px;")
        layout.addWidget(self.title_label)

        # ── Main strikes table (scrollable) ───────────────────────────
        self.table = QTableWidget()
        self.table.setStyleSheet(_TABLE_SS)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setFixedWidth(self._VH_WIDTH)
        layout.addWidget(self.table, stretch=1)

        # ── Pinned Total row (always visible at the bottom) ────────────
        self.total_table = QTableWidget(1, 1)
        self.total_table.setStyleSheet(_TABLE_SS)
        self.total_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.total_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.total_table.horizontalHeader().hide()          # columns shown on main table
        # Fixed mode is REQUIRED — Stretch would override every setColumnWidth() call
        self.total_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.total_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.total_table.verticalHeader().setDefaultSectionSize(26)
        self.total_table.verticalHeader().setFixedWidth(self._VH_WIDTH)
        self.total_table.setFixedHeight(
            self.total_table.verticalHeader().defaultSectionSize() + 4   # row + border
        )
        layout.addWidget(self.total_table)

        # geometriesChanged fires AFTER the full Stretch recalculation completes,
        # which is what we need (sectionResized fires mid-calculation, per column).
        self.table.horizontalHeader().geometriesChanged.connect(self._sync_total_col_widths)

        self.info_label = QLabel("Waiting for Load Grid...")
        self.info_label.setStyleSheet("color: #888; padding: 3px;")
        layout.addWidget(self.info_label)

    def resizeEvent(self, event):
        """Re-sync column widths whenever the panel is resized."""
        super().resizeEvent(event)
        self._sync_total_col_widths()

    def _sync_total_col_widths(self):
        """Copy every column width from main table to total_table."""
        n = self.table.columnCount()
        if n != self.total_table.columnCount():
            return
        for col in range(n):
            self.total_table.setColumnWidth(col, self.table.columnWidth(col))

    def set_data_feed(self, data_feed):
        self.main_data_feed = data_feed

    # ------------------------------------------------------------------
    # Public entry point called by NetGEXGridWidget
    # ------------------------------------------------------------------
    def load_grid(self, symbol: str, selected_expirations: list, is_demo: bool, data_feed):
        """Load grid for the given symbol + expirations. Called by shared controls."""
        self.symbol = symbol.strip().upper()
        self.selected_expirations = selected_expirations
        self.main_data_feed = data_feed
        self.current_price = 0

        self._top3_cells = set()
        self._col_gex = {}
        self.info_label.setText(f"Loading {self.symbol}...")
        QApplication.processEvents()

        try:
            if is_demo:
                self._fetch_demo_grid_data()
            else:
                self._fetch_real_grid_data()
        except Exception as e:
            self.info_label.setText(f"Error: {e}")
            print(f"Grid load error ({self.symbol}): {e}")

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------
    def _fetch_demo_grid_data(self):
        if self.current_price == 0:
            price_ranges = {
                "ES": 6000, "NQ": 21000, "GC": 2650,
                "SPX": 6000, "SPY": 600, "QQQ": 520,
                "VIX": 18, "$VIX": 18,
            }
            self.current_price = price_ranges.get(self.symbol,
                                 price_ranges.get(self.symbol.lstrip('/$'), 100))

        si = self._get_strike_interval()
        self.atm = round(self.current_price / si) * si
        self._build_strike_list()
        self._populate_demo()

    def _fetch_real_grid_data(self):
        if not self.main_data_feed or not hasattr(self.main_data_feed, 'access_token'):
            self.info_label.setText("Not authenticated — start main feed first.")
            return

        self._fetch_current_price()

        if self.current_price == 0:
            self.info_label.setText("Could not fetch price.")
            return

        si = self._get_strike_interval()
        self.atm = round(self.current_price / si) * si
        self._build_strike_list()
        self._populate_real()

    def _fetch_current_price(self):
        import requests
        api_symbol = SchwabConfig.SYMBOL_MAP.get(self.symbol, self.symbol)
        headers = {
            'Authorization': f'Bearer {self.main_data_feed.access_token}',
            'Accept': 'application/json',
        }
        try:
            resp = requests.get(f"{SchwabConfig.BASE_URL}/quotes",
                                headers=headers, params={'symbols': api_symbol}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if api_symbol in data:
                    self.current_price = data[api_symbol].get('quote', {}).get('lastPrice', 0)
                else:
                    for val in data.values():
                        if isinstance(val, dict) and 'quote' in val:
                            self.current_price = val['quote'].get('lastPrice', 0)
                            break
        except Exception as e:
            print(f"Price fetch error: {e}")

    def _build_strike_list(self):
        """50 strikes: 24 below ATM, ATM, 25 above."""
        si = self._get_strike_interval()
        self.strikes = []
        for i in range(24, 0, -1):
            self.strikes.append(self.atm - i * si)
        self.strikes.append(self.atm)
        for i in range(1, 26):
            self.strikes.append(self.atm + i * si)

    def _get_strike_interval(self) -> float:
        sym = self.symbol.lstrip('/$')
        return SchwabConfig.STRIKE_INTERVALS.get(self.symbol,
               SchwabConfig.STRIKE_INTERVALS.get(sym, 5))

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------
    def _populate_real(self):
        import requests
        from PyQt6.QtWidgets import QTableWidgetItem
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QColor

        num_rows = len(self.strikes)          # total row lives in total_table now
        num_cols = len(self.selected_expirations) + 1
        self.table.setRowCount(num_rows)
        self.table.setColumnCount(num_cols)
        self.total_table.setRowCount(1)
        self.total_table.setColumnCount(num_cols)
        api_symbol = SchwabConfig.SYMBOL_MAP.get(self.symbol, self.symbol)
        multiplier = SchwabConfig.MULTIPLIERS.get(self.symbol, 100)
        headers = {
            'Authorization': f'Bearer {self.main_data_feed.access_token}',
            'Accept': 'application/json',
        }
        chain_url = f"{SchwabConfig.BASE_URL}/chains"
        max_gex = 1_000_000_000

        all_strike_gex = {s: [] for s in self.strikes}
        all_exp_totals = []

        for col, expiration in enumerate(self.selected_expirations):
            self.info_label.setText(f"{self.symbol}: loading {expiration} ({col+1}/{len(self.selected_expirations)})")
            QApplication.processEvents()

            params = {
                'symbol': api_symbol, 'contractType': 'ALL', 'strikeCount': 50,
                'includeUnderlyingQuote': 'true', 'strategy': 'SINGLE', 'range': 'ALL',
                'fromDate': expiration, 'toDate': expiration,
            }
            try:
                resp = requests.get(chain_url, headers=headers, params=params, timeout=15)
                if resp.status_code != 200:
                    raise ValueError(f"HTTP {resp.status_code}")

                chain = resp.json()
                strike_gex = {}

                for _, strikes_dict in chain.get('callExpDateMap', {}).items():
                    for sk, opts in strikes_dict.items():
                        opt = opts[0] if opts else {}
                        g = (opt.get('gamma') or 0) * (opt.get('openInterest') or 0)
                        strike_gex[float(sk)] = strike_gex.get(float(sk), 0) + g * self.current_price**2 * 0.01 * multiplier

                for _, strikes_dict in chain.get('putExpDateMap', {}).items():
                    for sk, opts in strikes_dict.items():
                        opt = opts[0] if opts else {}
                        g = (opt.get('gamma') or 0) * (opt.get('openInterest') or 0)
                        strike_gex[float(sk)] = strike_gex.get(float(sk), 0) - g * self.current_price**2 * 0.01 * multiplier

                if strike_gex:
                    max_gex = max(max_gex, max(abs(v) for v in strike_gex.values()))

                exp_total = 0
                col_vals = []
                for row, strike in enumerate(self.strikes):
                    ng = strike_gex.get(strike, 0)
                    all_strike_gex[strike].append(ng)
                    exp_total += ng
                    col_vals.append(ng)
                    self.table.setItem(row, col, self._make_item(ng, max_gex))
                self._col_gex[col] = col_vals
                all_exp_totals.append(exp_total)

            except Exception as e:
                print(f"  Error {expiration}: {e}")
                for row in range(len(self.strikes)):
                    item = QTableWidgetItem("--")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(QColor(20, 20, 20))
                    item.setForeground(QColor(100, 100, 100))
                    self.table.setItem(row, col, item)
                all_exp_totals.append(0)

        self._fill_totals(all_strike_gex, all_exp_totals, max_gex)
        self._set_headers()
        self._apply_all_highlights()
        self._highlight_atm()
        self.title_label.setText(f"{self.symbol} @ {self.current_price:.2f}")
        self.info_label.setText(f"{len(self.selected_expirations)} exp \u00d7 {len(self.strikes)} strikes")

    def _populate_demo(self):
        from PyQt6.QtGui import QColor
        import random

        num_rows = len(self.strikes)          # total row lives in total_table now
        num_cols = len(self.selected_expirations) + 1
        self.table.setRowCount(num_rows)
        self.table.setColumnCount(num_cols)
        self.total_table.setRowCount(1)
        self.total_table.setColumnCount(num_cols)

        max_gex = 500_000_000
        all_strike_gex = {s: [] for s in self.strikes}
        all_exp_totals = []

        for col, _ in enumerate(self.selected_expirations):
            exp_total = 0
            col_vals = []
            for row, strike in enumerate(self.strikes):
                distance = abs(strike - self.atm)
                base = max(max_gex * (1.0 - distance / (self.atm * 0.1)), 0)
                base *= max(1.0 - col * 0.03, 0.3)
                ng = base * random.uniform(-1.2, 1.5)
                if strike > self.atm:
                    ng = abs(ng) * random.uniform(0.9, 1.3) + (-abs(ng) * random.uniform(0.6, 0.9))
                elif strike < self.atm:
                    ng = (-abs(ng) * random.uniform(0.9, 1.3)) + abs(ng) * random.uniform(0.6, 0.9)
                all_strike_gex[strike].append(ng)
                exp_total += ng
                col_vals.append(ng)
                self.table.setItem(row, col, self._make_item(ng, max_gex))
            self._col_gex[col] = col_vals
            all_exp_totals.append(exp_total)

        self._fill_totals(all_strike_gex, all_exp_totals, max_gex)
        self._set_headers()
        self._apply_all_highlights()
        self._highlight_atm()
        self.title_label.setText(f"{self.symbol} @ {self.current_price:.2f} (Demo)")
        self.info_label.setText(f"{len(self.selected_expirations)} exp \u00d7 {len(self.strikes)} strikes (Demo)")

    def _fill_totals(self, all_strike_gex, all_exp_totals, max_gex):
        from PyQt6.QtGui import QColor
        total_col = len(self.selected_expirations)

        # ── Total column (rightmost column of main table) ──────────────
        total_col_vals = []
        for row, strike in enumerate(self.strikes):
            sv = sum(all_strike_gex[strike])
            total_col_vals.append(sv)
            item = self._make_item(sv, max_gex)
            item.setBackground(QColor(30, 30, 50))
            f = item.font(); f.setBold(True); item.setFont(f)
            self.table.setItem(row, total_col, item)
        self._col_gex[total_col] = total_col_vals

        # ── Total row (pinned bottom table) ────────────────────────────
        for col, et in enumerate(all_exp_totals):
            item = self._make_item(et, max_gex)
            item.setBackground(QColor(30, 30, 50))
            f = item.font(); f.setBold(True); item.setFont(f)
            self.total_table.setItem(0, col, item)

        item = self._make_item(sum(all_exp_totals), max_gex)
        item.setBackground(QColor(40, 40, 60))
        f = item.font(); f.setBold(True); item.setFont(f)
        self.total_table.setItem(0, total_col, item)

    def _set_headers(self):
        col_headers = []
        for exp in self.selected_expirations:
            try:
                col_headers.append(datetime.strptime(exp, '%Y-%m-%d').strftime('%b %d').upper())
            except:
                col_headers.append(exp[-5:])
        col_headers.append("TOTAL")
        self.table.setHorizontalHeaderLabels(col_headers)

        si = self._get_strike_interval()
        fmt = ":.1f" if si < 1.0 else ":.0f"
        row_headers = [f"{s:{fmt[1:]}}" for s in self.strikes]   # no "TOTAL" in main table
        self.table.setVerticalHeaderLabels(row_headers)

        # Label the pinned total row
        self.total_table.setVerticalHeaderLabels(["TOTAL"])

        # Defer sync to after Qt's layout pass completes (singleShot(0) = next event loop tick)
        QTimer.singleShot(0, self._sync_total_col_widths)

    def _apply_all_highlights(self):
        """Per-column: top 3 positive -> green gradient, top 3 negative -> red gradient.
        Rank 1 = brightest, rank 3 = dimmest. Overwrites base gradient color."""
        from PyQt6.QtGui import QColor

        # Green shades rank 1..3
        green_colors = [QColor(0, 210, 80), QColor(0, 155, 55), QColor(0, 100, 35)]
        # Red shades rank 1..3  (rank 1 = most negative = brightest)
        red_colors   = [QColor(220, 0, 0), QColor(165, 0, 0), QColor(110, 0, 0)]

        self._top3_cells = set()

        for col, col_vals in self._col_gex.items():
            if not col_vals:
                continue

            # Pair (row_index, gex_value) — data rows only (exclude total row)
            pairs = list(enumerate(col_vals))

            # Top 3 positive (highest first)
            pos_ranked = sorted([p for p in pairs if p[1] > 0], key=lambda x: x[1], reverse=True)[:3]
            # Top 3 negative (most negative first)
            neg_ranked = sorted([p for p in pairs if p[1] < 0], key=lambda x: x[1])[:3]

            for rank, (row, _) in enumerate(pos_ranked):
                item = self.table.item(row, col)
                if item:
                    item.setBackground(green_colors[rank])
                    f = item.font(); f.setBold(True); item.setFont(f)
                    self._top3_cells.add((row, col))

            for rank, (row, _) in enumerate(neg_ranked):
                item = self.table.item(row, col)
                if item:
                    item.setBackground(red_colors[rank])
                    f = item.font(); f.setBold(True); item.setFont(f)
                    self._top3_cells.add((row, col))

    def _highlight_atm(self):
        """Yellow background on ATM row cells not already claimed by top-3 highlight."""
        from PyQt6.QtGui import QColor
        atm_yellow = QColor(160, 130, 0)

        try:
            atm_row = self.strikes.index(self.atm)
        except ValueError:
            atm_row = len(self.strikes) // 2

        total_col = len(self.selected_expirations)
        for col in range(total_col + 1):   # include Total column
            item = self.table.item(atm_row, col)
            if item:
                f = item.font(); f.setBold(True); item.setFont(f)
                if (atm_row, col) not in self._top3_cells:
                    item.setBackground(atm_yellow)

    def _make_item(self, net_gex: float, max_gex: float):
        from PyQt6.QtWidgets import QTableWidgetItem
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QColor

        if abs(net_gex) >= 1_000_000:
            text = f"{net_gex/1_000_000:+.1f}M"
        elif abs(net_gex) >= 1_000:
            text = f"{net_gex/1_000:+.1f}K"
        else:
            text = f"{net_gex:+.0f}"

        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        font = item.font()
        font.setPointSize(7)
        font.setBold(True)
        item.setFont(font)

        n = max(-1.0, min(1.0, net_gex / max_gex)) if max_gex else 0
        t = abs(n)
        if n < 0:
            item.setBackground(QColor(max(int(220*t), 10), max(int(50*t), 5), max(int(50*t), 5)))
        else:
            item.setBackground(QColor(max(int(50*t), 5), max(int(220*t), 10), max(int(50*t), 5)))
        item.setForeground(QColor(255, 255, 255))
        return item

    def get_export_data(self) -> dict:
        """
        Return raw grid data for CSV export.
        Returns a dict with symbol, price, strikes, expirations, and gex_matrix.
        gex_matrix[row][col] = net GEX value (float), including Total row/col.
        Returns {} if no data loaded.
        """
        if not self.strikes or not self.selected_expirations:
            return {}

        num_exp = len(self.selected_expirations)
        num_strikes = len(self.strikes)

        # Reconstruct full matrix from _col_gex (col_idx -> list of gex per strike)
        gex_matrix = []
        for row in range(num_strikes):
            row_data = []
            for col in range(num_exp + 1):   # data cols + Total col
                vals = self._col_gex.get(col, [])
                row_data.append(vals[row] if row < len(vals) else 0.0)
            gex_matrix.append(row_data)

        # Total row from the pinned total_table
        total_row_data = []
        for col in range(num_exp + 1):
            item = self.total_table.item(0, col)
            try:
                raw = item.text().replace('+', '').replace('M', 'e6').replace('K', 'e3')
                total_row_data.append(float(raw))
            except Exception:
                total_row_data.append(0.0)
        gex_matrix.append(total_row_data)

        col_headers = []
        for exp in self.selected_expirations:
            try:
                col_headers.append(datetime.strptime(exp, '%Y-%m-%d').strftime('%Y-%m-%d'))
            except Exception:
                col_headers.append(exp)
        col_headers.append('TOTAL')

        row_headers = [str(s) for s in self.strikes] + ['TOTAL']

        return {
            'symbol': self.symbol,
            'price': self.current_price,
            'atm': self.atm,
            'col_headers': col_headers,
            'row_headers': row_headers,
            'gex_matrix': gex_matrix,
        }

    def clear_grid(self):
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.total_table.setRowCount(1)
        self.total_table.setColumnCount(1)
        self.total_table.setItem(0, 0, None)
        self.total_table.setVerticalHeaderLabels(["TOTAL"])
        self.title_label.setText("\u2014")
        self.info_label.setText("Waiting for Load Grid...")


class NetGEXGridWidget(QWidget):
    """
    Net GEX Grid tab with shared controls and 1/2/3 panel toggle.
    Each panel has its own independent expiration list (Option A).
    """

    DEFAULTS = ["SPX", "SPY", "QQQ"]

    # Emitted from worker threads to update UI on the main thread
    _exp_loaded  = pyqtSignal(int)   # sym index
    _all_fetched = pyqtSignal()      # all threads done — re-enable Load Expiry

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_data_feed = None
        # Per-symbol expiration state (index 0=Sym1, 1=Sym2, 2=Sym3)
        self._avail_exps = [[], [], []]
        self._sel_exps   = [[], [], []]
        self.active_count = 3
        self._exp_loaded.connect(self._on_exps_loaded)
        self._all_fetched.connect(lambda: self.btn_load_exp.setEnabled(True))
        self._setup_ui()

    def _setup_ui(self):
        from PyQt6.QtWidgets import QHeaderView
        from PyQt6.QtCore import Qt

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Shared control bar ─────────────────────────────────────────
        ctrl = QFrame()
        ctrl.setObjectName("gridControlFrame")
        ctrl.setStyleSheet("""
            #gridControlFrame {
                background-color: #1e1e1e;
                border-radius: 8px;
                border: 1px solid #333;
            }
        """)
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(15, 10, 15, 10)
        cl.setSpacing(8)

        # ── Symbol count toggle ────────────────────────────────────────
        cl.addWidget(QLabel("Symbols:"))
        self._count_btns = []
        for n in (1, 2, 3):
            btn = QPushButton(str(n))
            btn.setCheckable(True)
            btn.setFixedWidth(32)
            btn.setObjectName("countToggleBtn")
            btn.setStyleSheet("""
                QPushButton#countToggleBtn {
                    background-color: #2a2a2a; color: #aaa;
                    border: 1px solid #555; border-radius: 4px; padding: 4px;
                }
                QPushButton#countToggleBtn:checked {
                    background-color: #2a5a6b; color: white; border-color: #3a8a9b;
                }
            """)
            btn.clicked.connect(lambda checked, x=n: self._set_active_count(x))
            cl.addWidget(btn)
            self._count_btns.append(btn)
        self._count_btns[2].setChecked(True)  # default = 3

        cl.addSpacing(12)

        # ── Symbol inputs ──────────────────────────────────────────────
        self._sym_inputs = []
        self._sym_labels = []
        for i, default in enumerate(self.DEFAULTS):
            lbl = QLabel(f"{'  ' if i > 0 else ''}Sym {i+1}:")
            cl.addWidget(lbl)
            inp = QLineEdit()
            inp.setText(default)
            inp.setFixedWidth(70)
            inp.setObjectName("symbolInput")
            cl.addWidget(inp)
            self._sym_inputs.append(inp)
            self._sym_labels.append(lbl)

        cl.addSpacing(12)

        # ── Single Load Expiry (fetches all 3 symbols in parallel) ─────
        self.btn_load_exp = QPushButton("Load Expiry")
        self.btn_load_exp.setObjectName("loadButton")
        self.btn_load_exp.clicked.connect(self._load_expirations)
        cl.addWidget(self.btn_load_exp)

        cl.addSpacing(8)

        # ── Per-symbol Select Expiry buttons ───────────────────────────
        self._select_exp_btns = []
        self._sel_exp_labels  = []
        for i in range(3):
            btn = QPushButton(f"S{i+1} Expiry (0)")
            btn.setObjectName("gridExpBtn")
            btn.setStyleSheet("""
                QPushButton#gridExpBtn {
                    background-color: #4a3a6b; color: white;
                    border: none; padding: 6px 10px;
                }
                QPushButton#gridExpBtn:hover { background-color: #5a4a7b; }
                QPushButton#gridExpBtn:disabled { background-color: #333; color: #666; }
            """)
            btn.setEnabled(False)
            btn.clicked.connect(lambda checked, idx=i: self._show_expiration_dialog(idx))
            cl.addWidget(btn)
            self._select_exp_btns.append(btn)

        cl.addSpacing(12)

        # ── Load Grid ─────────────────────────────────────────────────
        self.btn_load_grid = QPushButton("\U0001f504 Load Grid")
        self.btn_load_grid.setObjectName("loadGridButton")
        self.btn_load_grid.setStyleSheet("""
            #loadGridButton {
                background-color: #2a5a6b; color: white;
                border: none; padding: 8px 20px; font-weight: bold;
            }
            #loadGridButton:hover { background-color: #3a7a8b; }
            #loadGridButton:disabled { background-color: #333; color: #666; }
        """)
        self.btn_load_grid.clicked.connect(self._load_all_grids)
        self.btn_load_grid.setEnabled(False)
        cl.addWidget(self.btn_load_grid)

        cl.addSpacing(12)

        # ── Demo Mode ─────────────────────────────────────────────────
        self.demo_check = QCheckBox("Demo Mode")
        self.demo_check.setChecked(True)
        cl.addWidget(self.demo_check)

        cl.addSpacing(12)

        # ── Export button ──────────────────────────────────────────────
        self.btn_export_grid = QPushButton("⬇ Export CSV")
        self.btn_export_grid.setObjectName("loadButton")
        self.btn_export_grid.setToolTip("Export Net GEX grid data for all active panels to CSV")
        self.btn_export_grid.clicked.connect(self._export_grids_csv)
        cl.addWidget(self.btn_export_grid)

        cl.addSpacing(12)

        # ── Auto-Refresh ───────────────────────────────────────────────
        cl.addWidget(QLabel("Auto-Refresh:"))
        self.refresh_combo = QComboBox()
        self.refresh_combo.addItems(["Off", "5 min", "15 min", "30 min"])
        self.refresh_combo.setToolTip("Automatically reload all grids at the selected interval")
        self.refresh_combo.currentTextChanged.connect(self._on_refresh_interval_changed)
        cl.addWidget(self.refresh_combo)

        # Countdown label (e.g. "Next: 4:23")
        self.refresh_countdown_lbl = QLabel("")
        self.refresh_countdown_lbl.setStyleSheet("color: #8aff8a; font-size: 11px; min-width: 70px;")
        cl.addWidget(self.refresh_countdown_lbl)

        # Internal timer state
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._auto_refresh_tick)
        self._refresh_interval_secs = 0   # 0 = off
        self._refresh_remaining_secs = 0

        cl.addStretch()
        root.addWidget(ctrl)

        # ── Panel splitter ─────────────────────────────────────────────
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(0)
        self.splitter.setChildrenCollapsible(False)

        self.panels = [SingleGridPanel() for _ in range(3)]
        for idx, panel in enumerate(self.panels):
            self.splitter.addWidget(panel)
            self.splitter.setCollapsible(idx, False)
            self.splitter.handle(idx).setEnabled(False)

        self.splitter.setSizes([500, 500, 500])
        root.addWidget(self.splitter, stretch=1)

        # Apply initial visibility
        self._set_active_count(3)

    # ------------------------------------------------------------------
    # Symbol count toggle
    # ------------------------------------------------------------------
    def _set_active_count(self, n: int):
        self.active_count = n
        for btn in self._count_btns:
            btn.setChecked(False)
        self._count_btns[n - 1].setChecked(True)

        # Show/hide panels and sym inputs
        for i, panel in enumerate(self.panels):
            panel.setVisible(i < n)
        for i in range(3):
            visible = i < n
            self._sym_inputs[i].setVisible(visible)
            self._sym_labels[i].setVisible(visible)
            self._select_exp_btns[i].setVisible(visible)

        # Re-equalise splitter sizes for visible panels
        sizes = [500 if i < n else 0 for i in range(3)]
        self.splitter.setSizes(sizes)

    # ------------------------------------------------------------------
    # Shared expiration logic
    # ------------------------------------------------------------------
    def _load_expirations(self):
        print("[NetGEXGridWidget] Load Expiry clicked", flush=True)
        try:
            is_demo = self.demo_check.isChecked()

            # If the connected feed is a DemoDataFeed, always use demo path
            if not is_demo and isinstance(self.main_data_feed, DemoDataFeed):
                print("[NetGEXGridWidget] Feed is DemoDataFeed — using demo path", flush=True)
                is_demo = True

            # Fall back to demo if no feed at all
            if not is_demo and not self.main_data_feed:
                print("[NetGEXGridWidget] No feed — falling back to demo", flush=True)
                is_demo = True

            print(f"[NetGEXGridWidget] is_demo={is_demo}, feed type={type(self.main_data_feed).__name__}", flush=True)

            if is_demo:
                from datetime import datetime, timedelta
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                expirations, current, added = [], today, 0
                while len(expirations) < 30 and added < 100:
                    if current.weekday() < 5:
                        expirations.append(current.strftime('%Y-%m-%d'))
                    current += timedelta(days=1)
                    added += 1
                print(f"[NetGEXGridWidget] Generated {len(expirations)} demo expirations", flush=True)
                for i in range(3):
                    self._avail_exps[i] = expirations[:]
                    self._sel_exps[i]   = expirations[:10]
                    self._select_exp_btns[i].setEnabled(True)
                    self._select_exp_btns[i].setText(
                        f"S{i+1} Expiry ({len(self._sel_exps[i])})")
                    print(f"[NetGEXGridWidget] S{i+1} button enabled with {len(self._sel_exps[i])} expirations", flush=True)
                self.btn_load_grid.setEnabled(True)
                print("[NetGEXGridWidget] Load Grid enabled", flush=True)
                return

            # ── Live API path ───────────────────────────────────────────
            syms = [self._sym_inputs[i].text().strip().upper()
                    for i in range(self.active_count)]

            def fetch_for(idx, sym):
                try:
                    print(f"[NetGEXGridWidget] fetch_for Sym{idx+1} {sym} starting", flush=True)
                    temp = SchwabDataFeed(sym, 100, 30)
                    if hasattr(self.main_data_feed, 'access_token'):
                        temp.access_token  = self.main_data_feed.access_token
                        temp.refresh_token = self.main_data_feed.refresh_token
                        temp.token_expiry  = self.main_data_feed.token_expiry
                    token_ok = temp._ensure_token()
                    print(f"[NetGEXGridWidget] Sym{idx+1} _ensure_token={token_ok}", flush=True)
                    if not token_ok:
                        return
                    exps = temp.fetch_expirations()
                    print(f"[NetGEXGridWidget] Sym{idx+1} fetch_expirations returned {len(exps) if exps else 0} items", flush=True)
                    if exps:
                        self._avail_exps[idx] = exps[:30]
                        self._sel_exps[idx]   = exps[:10]
                        self._exp_loaded.emit(idx)  # thread-safe queued connection
                except Exception as e:
                    import traceback
                    print(f"[NetGEXGridWidget] fetch_for Sym{idx+1} {sym} EXCEPTION:", flush=True)
                    traceback.print_exc()

            for idx, sym in enumerate(syms):
                if sym:
                    threading.Thread(target=fetch_for, args=(idx, sym), daemon=True).start()

        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Load Expiry Error",
                                 f"Unexpected error:\n{e}")

    def _do_load_expirations(self):
        pass  # superseded by _load_expirations

    def _on_exps_loaded(self, idx: int):
        """Called on main thread after a symbol's expirations arrive."""
        self._select_exp_btns[idx].setEnabled(True)
        self._select_exp_btns[idx].setText(
            f"S{idx+1} Expiry ({len(self._sel_exps[idx])})")
        # Enable Load Grid as soon as at least one symbol has selections
        if any(len(self._sel_exps[i]) > 0 for i in range(3)):
            self.btn_load_grid.setEnabled(True)

    def _show_expiration_dialog(self, sym_idx: int):
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QDialogButtonBox,
                                     QListWidget, QListWidgetItem)

        sym = self._sym_inputs[sym_idx].text().strip().upper() or f"Sym {sym_idx+1}"
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Select Expirations — {sym}")
        dialog.setMinimumWidth(350)
        dialog.setMinimumHeight(500)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"Select up to 30 expiration dates for {sym}:"))

        lw = QListWidget()
        lw.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for exp in self._avail_exps[sym_idx]:
            item = QListWidgetItem(exp)
            lw.addItem(item)
            if exp in self._sel_exps[sym_idx]:
                item.setSelected(True)
        layout.addWidget(lw)

        count_lbl = QLabel(f"Selected: {len(self._sel_exps[sym_idx])} / 30 max")
        layout.addWidget(count_lbl)

        def _update():
            n = len(lw.selectedItems())
            count_lbl.setText(f"Selected: {n} / 30 max")
            count_lbl.setStyleSheet("color: red;" if n > 30 else "color: white;")
        lw.itemSelectionChanged.connect(_update)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dialog.accept)
        btns.rejected.connect(dialog.reject)
        layout.addWidget(btns)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = [item.text() for item in lw.selectedItems()]
            if not selected:
                QMessageBox.warning(self, "None Selected",
                                    "Select at least 1 expiration.")
                return
            if len(selected) > 30:
                QMessageBox.warning(self, "Too Many",
                                    "Select at most 30 expirations.")
                return
            self._sel_exps[sym_idx] = sorted(selected)
            self._select_exp_btns[sym_idx].setText(
                f"S{sym_idx+1} Expiry ({len(self._sel_exps[sym_idx])})")

    # ------------------------------------------------------------------
    # Load all active panels
    # ------------------------------------------------------------------
    def _load_all_grids(self):
        is_demo = self.demo_check.isChecked()
        self.btn_load_grid.setEnabled(False)

        try:
            for i in range(self.active_count):
                sym = self._sym_inputs[i].text().strip().upper()
                if not sym:
                    QMessageBox.warning(self, "Missing Symbol",
                                        f"Please enter a symbol for panel {i+1}.")
                    continue
                if not self._sel_exps[i]:
                    QMessageBox.warning(self, "No Expirations",
                                        f"Please select expirations for Sym {i+1} ({sym}) first.")
                    continue
                self.panels[i].load_grid(sym, self._sel_exps[i],
                                         is_demo, self.main_data_feed)
        finally:
            self.btn_load_grid.setEnabled(True)

    # ------------------------------------------------------------------
    # Grid export
    # ------------------------------------------------------------------
    def _export_grids_csv(self):
        """Export Net GEX grid data from all active panels to CSV files."""
        from PyQt6.QtWidgets import QFileDialog

        # Check that at least one panel has data
        any_data = False
        for i in range(self.active_count):
            if self.panels[i].strikes:
                any_data = True
                break

        if not any_data:
            QMessageBox.warning(self, "No Data",
                                "No grid data to export. Load the grid first.")
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        exported_files = []
        errors = []

        for i in range(self.active_count):
            panel = self.panels[i]
            data = panel.get_export_data()
            if not data:
                continue

            sym = data['symbol'] or f"panel{i+1}"
            default_name = f"gex_grid_{sym}_{timestamp}.csv"

            filepath, _ = QFileDialog.getSaveFileName(
                self,
                f"Export Grid — {sym} (Panel {i+1})",
                default_name,
                "CSV Files (*.csv);;All Files (*)"
            )
            if not filepath:
                continue

            try:
                import csv
                col_headers = data['col_headers']
                row_headers = data['row_headers']
                gex_matrix = data['gex_matrix']

                with open(filepath, 'w', newline='') as f:
                    writer = csv.writer(f)
                    # Metadata rows
                    writer.writerow(['Symbol', sym])
                    writer.writerow(['Price', f"{data['price']:.2f}"])
                    writer.writerow(['ATM', f"{data['atm']:.2f}"])
                    writer.writerow(['Exported', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
                    writer.writerow([])
                    # Header row: blank (strike label col) + expiration cols
                    writer.writerow(['Strike'] + col_headers)
                    # Data rows
                    for row_idx, row_data in enumerate(gex_matrix):
                        writer.writerow([row_headers[row_idx]] + [f"{v:.0f}" for v in row_data])

                exported_files.append(f"Panel {i+1} ({sym}) → {filepath}")
            except Exception as e:
                errors.append(f"Panel {i+1} ({sym}): {e}")

        if exported_files:
            msg = "Exported:\n" + "\n".join(exported_files)
            if errors:
                msg += "\n\nErrors:\n" + "\n".join(errors)
            QMessageBox.information(self, "Export Complete", msg)
        elif errors:
            QMessageBox.warning(self, "Export Failed", "\n".join(errors))

    # ------------------------------------------------------------------
    # Auto-refresh
    # ------------------------------------------------------------------
    def _on_refresh_interval_changed(self, text: str):
        """Start or stop the auto-refresh timer based on the selected interval."""
        self._refresh_timer.stop()
        self.refresh_countdown_lbl.setText("")

        interval_map = {"Off": 0, "5 min": 300, "15 min": 900, "30 min": 1800}
        self._refresh_interval_secs = interval_map.get(text, 0)

        if self._refresh_interval_secs > 0:
            self._refresh_remaining_secs = self._refresh_interval_secs
            self._update_countdown_label()
            # Tick every second for the countdown display
            self._refresh_timer.start(1000)

    def _auto_refresh_tick(self):
        """Called every second while auto-refresh is active."""
        self._refresh_remaining_secs -= 1
        self._update_countdown_label()

        if self._refresh_remaining_secs <= 0:
            # Time to reload
            self._refresh_remaining_secs = self._refresh_interval_secs
            if self.btn_load_grid.isEnabled():
                print(f"[Auto-Refresh] Reloading grids at {datetime.now().strftime('%H:%M:%S')}")
                self._load_all_grids()

    def _update_countdown_label(self):
        """Update the countdown label with minutes:seconds remaining."""
        if self._refresh_interval_secs <= 0:
            self.refresh_countdown_lbl.setText("")
            return
        mins, secs = divmod(self._refresh_remaining_secs, 60)
        self.refresh_countdown_lbl.setText(f"Next: {mins}:{secs:02d}")

    # ------------------------------------------------------------------
    # MainWindow interface (unchanged API)
    # ------------------------------------------------------------------
    def set_data_feed(self, data_feed):
        self.main_data_feed = data_feed
        for p in self.panels:
            p.set_data_feed(data_feed)

    def update_data(self, data: dict):
        pass  # manual refresh only

    def clear_history(self):
        for p in self.panels:
            p.clear_grid()


class NetVolGEXHeatmapWidget(QWidget):
    """
    Net Volume GEX heatmap panel (Option B proxy).

    Formula per strike:
        net_vol_gex[i] = gex[i] × (volume[i] / max_volume)

    Color scheme: Black (zero) → Purple (positive/bullish) → Orange (negative/bearish)
    Independent per-panel scaling (self-normalizing each update).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history: deque = deque(maxlen=1000)
        self.timestamps: List[datetime] = []
        self.num_strikes = 100
        self._y_lo: float = None
        self._y_hi: float = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        h_layout = QHBoxLayout()
        h_layout.setSpacing(2)
        h_layout.setContentsMargins(0, 0, 0, 0)

        # Heatmap widget
        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setBackground('#0a0a0a')
        h_layout.addWidget(self.graphics, stretch=1)

        # Bar chart widget (fixed 180px)
        self.bar_graphics = pg.GraphicsLayoutWidget()
        self.bar_graphics.setBackground('#0a0a0a')
        self.bar_graphics.setFixedWidth(180)
        h_layout.addWidget(self.bar_graphics, stretch=0)

        layout.addLayout(h_layout)

        self.time_axis = TimeAxisItem(orientation='bottom')

        # Heatmap plot
        self.plot = self.graphics.addPlot(
            row=0, col=0, rowspan=2,
            axisItems={'bottom': self.time_axis}
        )
        self.plot.setLabel('left', 'Strike Price', color='#aaa')
        self.plot.setLabel('bottom', 'Time', color='#aaa')
        self.plot.showGrid(x=True, y=True, alpha=0.15)

        # Bar chart plot
        self.bar_plot = self.bar_graphics.addPlot(row=0, col=0, rowspan=2)
        self.bar_plot.setLabel('bottom', 'Net Vol GEX', color='#aaa')
        self.bar_plot.showGrid(x=True, y=True, alpha=0.15)
        self.bar_plot.hideAxis('left')
        self.bar_plot.getAxis('left').setWidth(0)

        BOTTOM_AXIS_HEIGHT = 48
        self.plot.getAxis('bottom').setHeight(BOTTOM_AXIS_HEIGHT)
        self.bar_plot.getAxis('bottom').setHeight(BOTTOM_AXIS_HEIGHT)

        self.plot.getViewBox().sigYRangeChanged.connect(self._on_heatmap_y_changed)

        # Purple / Orange LUT
        # 0   → max orange  (most negative)
        # 127 → black       (zero)
        # 255 → max purple  (most positive)
        lut = np.zeros((256, 4), dtype=np.ubyte)
        for i in range(128):               # orange → black
            t = i / 127.0
            lut[i, 0] = int(230 * (1 - t))   # R: 230 → 0
            lut[i, 1] = int(110 * (1 - t))   # G: 110 → 0
            lut[i, 2] = 0                      # B: 0
            lut[i, 3] = 255
        for i in range(128, 256):          # black → purple
            t = (i - 128) / 127.0
            lut[i, 0] = int(130 * t)          # R: 0 → 130
            lut[i, 1] = 0                      # G: 0
            lut[i, 2] = int(220 * t)          # B: 0 → 220
            lut[i, 3] = 255
        self.lut = lut

        # Heatmap image
        self.heatmap = pg.ImageItem()
        self.heatmap.setLookupTable(self.lut)
        self.heatmap.setZValue(-100)
        self.plot.addItem(self.heatmap)

        # Price line (white)
        self.price_line = pg.PlotDataItem(
            pen=pg.mkPen('#ffffff', width=2.5),
            antialias=True
        )
        self.price_line.setZValue(100)
        self.plot.addItem(self.price_line)

        self.price_marker = pg.ScatterPlotItem(
            size=12,
            brush=pg.mkBrush('#ffffff'),
            pen=pg.mkPen('#000000', width=1)
        )
        self.price_marker.setZValue(101)
        self.plot.addItem(self.price_marker)

        # Price line on bar chart
        self.price_line_bar = pg.InfiniteLine(
            angle=0,
            pen=pg.mkPen('#ffffff', width=2),
        )
        self.price_line_bar.setZValue(100)
        self.bar_plot.addItem(self.price_line_bar)

        self._bar_items = []

    def set_num_strikes(self, num: int):
        self.num_strikes = num

    # ------------------------------------------------------------------
    # Core formula
    # ------------------------------------------------------------------
    def _compute_net_vol_gex(self, data: dict) -> Tuple[List[float], List[float]]:
        """
        Option B proxy: net_vol_gex[i] = gex[i] × (volume[i] / max_volume)
        Returns (strikes, net_vol_gex_values).
        """
        strikes = data.get('strikes', [])
        gex = data.get('gex', [])
        volume = data.get('volume', [])

        if not strikes or not gex:
            return [], []

        vol_arr = np.array(volume, dtype=float) if volume else np.zeros(len(strikes))
        gex_arr = np.array(gex, dtype=float)

        max_vol = float(np.max(np.abs(vol_arr))) if len(vol_arr) > 0 else 1.0
        if max_vol == 0:
            max_vol = 1.0

        net_vol_gex = gex_arr * (vol_arr / max_vol)
        return list(strikes), list(net_vol_gex)

    # ------------------------------------------------------------------
    # Public update entry point
    # ------------------------------------------------------------------
    def update_data(self, data: dict):
        """Store data snapshot and refresh visuals."""
        strikes, nvg = self._compute_net_vol_gex(data)
        if not strikes:
            return

        # Build a lightweight snapshot for history (strikes + net_vol_gex values + price)
        snapshot = {
            'timestamp': data['timestamp'],
            'symbol': data.get('symbol', ''),
            'price': data.get('price', 0),
            'atm': data.get('atm', data.get('price', 0)),
            'strikes': strikes,
            'net_vol_gex': nvg,
        }
        self.history.append(snapshot)
        self.timestamps = [h['timestamp'] for h in self.history]
        self.time_axis.set_timestamps(self.timestamps)

        self._update_heatmap()
        self._update_price_line()
        self._update_bar_chart(snapshot)

        if data.get('price'):
            self.price_line_bar.setValue(data['price'])

    # ------------------------------------------------------------------
    # Heatmap rebuild
    # ------------------------------------------------------------------
    def _update_heatmap(self):
        if len(self.history) < 1:
            return

        all_strikes = set()
        for h in self.history:
            all_strikes.update(h['strikes'])
        if not all_strikes:
            return

        strikes = np.array(sorted(all_strikes))
        n_strikes = len(strikes)
        n_times = max(len(self.history), 2)

        heatmap_data = np.zeros((n_strikes, n_times))
        strike_to_idx = {s: i for i, s in enumerate(strikes)}

        for t_idx, h in enumerate(self.history):
            for strike, nvg in zip(h['strikes'], h['net_vol_gex']):
                if strike in strike_to_idx:
                    heatmap_data[strike_to_idx[strike], t_idx] = nvg

        if len(self.history) == 1:
            heatmap_data[:, 1] = heatmap_data[:, 0]

        # Independent per-panel scaling
        abs_vals = np.abs(heatmap_data[heatmap_data != 0])
        if len(abs_vals) > 0:
            max_abs = np.percentile(abs_vals, 99)
        else:
            max_abs = 1.0
        if max_abs == 0:
            max_abs = 1.0

        normalized = np.clip(heatmap_data / max_abs, -1.0, 1.0)
        img_scaled = ((normalized + 1.0) * 127.5).astype(np.uint8)
        img_data = img_scaled.T  # (n_times, n_strikes)

        self.heatmap.setImage(img_data, autoLevels=False, levels=[0, 255])

        if n_strikes > 1:
            strike_height = float(strikes[1] - strikes[0])
        else:
            strike_height = 5.0

        from PyQt6.QtCore import QRectF
        y_start = strikes[0] - strike_height / 2
        y_span = n_strikes * strike_height
        rect = QRectF(0, y_start, n_times, y_span)
        self.heatmap.setRect(rect)

        self.plot.setXRange(-0.5, n_times + 0.5, padding=0)

        if self.history:
            current_price = self.history[-1].get('price', float(strikes.mean()))
            y_range_pct = 0.01
            y_min = current_price * (1 - y_range_pct)
            y_max = current_price * (1 + y_range_pct)
            self.plot.setYRange(y_min, y_max, padding=0)
            self._y_lo, self._y_hi = y_min, y_max

        self.plot.enableAutoRange(axis='y', enable=False)
        self.plot.enableAutoRange(axis='x', enable=False)
        self.bar_plot.enableAutoRange(axis='y', enable=False)
        self.heatmap.update()
        self.plot.update()

    # ------------------------------------------------------------------
    # Bar chart
    # ------------------------------------------------------------------
    def _on_heatmap_y_changed(self, vb, y_range):
        y_lo, y_hi = y_range
        if y_hi > y_lo:
            self.bar_plot.blockSignals(True)
            self.bar_plot.setYRange(y_lo, y_hi, padding=0)
            self.bar_plot.enableAutoRange(axis='y', enable=False)
            self.bar_plot.blockSignals(False)

    def _update_bar_chart(self, snapshot: dict):
        strikes = snapshot.get('strikes', [])
        nvg_values = snapshot.get('net_vol_gex', [])
        if not strikes:
            return

        strikes_arr = np.array(strikes, dtype=float)
        nvg_arr = np.array(nvg_values, dtype=float)

        if len(strikes_arr) > 1:
            bar_height = float(np.diff(strikes_arr).min()) * 0.85
        else:
            bar_height = 5.0

        for item in getattr(self, '_bar_items', []):
            self.bar_plot.removeItem(item)
        self._bar_items = []

        # Purple for positive, orange for negative
        brushes = [
            pg.mkBrush(130, 0, 220, 200) if v >= 0 else pg.mkBrush(230, 110, 0, 200)
            for v in nvg_arr
        ]
        pens = [
            pg.mkPen(160, 30, 255, 255, width=0.5) if v >= 0 else pg.mkPen(255, 140, 0, 255, width=0.5)
            for v in nvg_arr
        ]

        bar = pg.BarGraphItem(
            x0=np.zeros(len(strikes_arr)),
            y=strikes_arr,
            height=bar_height,
            width=nvg_arr,
            brushes=brushes,
            pens=pens
        )
        self.bar_plot.addItem(bar)
        self._bar_items.append(bar)

        self.bar_plot.enableAutoRange(axis='x', enable=True)
        self.bar_plot.enableAutoRange(axis='y', enable=False)

    # ------------------------------------------------------------------
    # Price line
    # ------------------------------------------------------------------
    def _update_price_line(self):
        if len(self.history) < 1:
            return
        x = list(range(len(self.history)))
        y = [h['price'] for h in self.history]
        if len(x) == 1:
            x = [0, 1]
            y = [y[0], y[0]]
        self.price_line.setData(x, y)
        if self.history:
            last_x = len(self.history) - 1 if len(self.history) > 1 else 0.5
            self.price_marker.setData([last_x], [self.history[-1]['price']])

    def clear_history(self):
        self.history.clear()
        self.timestamps.clear()
        self.heatmap.clear()
        self.price_line.clear()
        self.price_marker.clear()
        for item in getattr(self, '_bar_items', []):
            self.bar_plot.removeItem(item)
        self._bar_items = []
        self.plot.enableAutoRange(axis='y', enable=True)
        self.plot.enableAutoRange(axis='x', enable=True)
        self.bar_plot.enableAutoRange(axis='x', enable=True)
        self.bar_plot.enableAutoRange(axis='y', enable=True)


class DualHeatmapTab(QWidget):
    """
    Intraday Heatmap tab — three side-by-side GEXHeatmapWidget panels.
    All feed management lives in MainWindow. Pure display container.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._net_vol_visible = True   # current Net Vol GEX row visibility
        self._sym_visible = [True, True, True]  # per-symbol visibility
        self.setup_ui()

    def setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Outer vertical splitter: top row (GEX heatmaps) + bottom row (Net Vol GEX)
        self.v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.v_splitter.setHandleWidth(5)
        self.v_splitter.setStyleSheet("QSplitter::handle { background: #555; }")

        # ── TOP ROW ──────────────────────────────────────────────────
        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        self.top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.top_splitter.setHandleWidth(4)
        self.top_splitter.setStyleSheet("QSplitter::handle { background: #444; }")

        for idx in range(1, 4):
            panel = QFrame()
            panel.setObjectName("heatmapPanel")
            p_layout = QVBoxLayout(panel)
            p_layout.setContentsMargins(4, 4, 4, 4)
            p_layout.setSpacing(2)

            header_widget = QWidget()
            header_layout = QHBoxLayout(header_widget)
            header_layout.setContentsMargins(8, 4, 8, 4)
            header_layout.setSpacing(0)

            lbl = QLabel(f"Symbol {idx}")
            lbl.setObjectName("panelHeaderLabel")
            header_layout.addWidget(lbl)
            setattr(self, f"lbl_sym{idx}", lbl)

            sep = QLabel("  |  ")
            sep.setStyleSheet("color: #555;")
            header_layout.addWidget(sep)
            setattr(self, f"lbl_sep{idx}", sep)

            lbl_price = QLabel("Price: --")
            lbl_price.setObjectName("panelPriceLabel")
            header_layout.addWidget(lbl_price)
            setattr(self, f"lbl_price{idx}", lbl_price)

            header_layout.addSpacing(18)

            lbl_net_gex = QLabel("Net GEX: --")
            lbl_net_gex.setObjectName("panelNetGexLabel")
            header_layout.addWidget(lbl_net_gex)
            setattr(self, f"lbl_net_gex{idx}", lbl_net_gex)

            header_layout.addSpacing(18)

            lbl_call_wall = QLabel("Call Wall: --")
            lbl_call_wall.setObjectName("panelCallWallLabel")
            header_layout.addWidget(lbl_call_wall)
            setattr(self, f"lbl_call_wall{idx}", lbl_call_wall)

            header_layout.addSpacing(18)

            lbl_put_wall = QLabel("Put Wall: --")
            lbl_put_wall.setObjectName("panelPutWallLabel")
            header_layout.addWidget(lbl_put_wall)
            setattr(self, f"lbl_put_wall{idx}", lbl_put_wall)

            header_layout.addStretch()
            p_layout.addWidget(header_widget)

            heatmap = GEXHeatmapWidget()
            p_layout.addWidget(heatmap, stretch=1)
            setattr(self, f"heatmap{idx}", heatmap)
            setattr(self, f"_top_panel{idx}", panel)

            self.top_splitter.addWidget(panel)

        self.top_splitter.setSizes([500, 500, 500])
        top_layout.addWidget(self.top_splitter)
        self.v_splitter.addWidget(top_container)

        # ── BOTTOM ROW (Net Vol GEX) ──────────────────────────────────
        self.bottom_container = QWidget()
        bottom_layout = QVBoxLayout(self.bottom_container)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(0)

        self.bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.bottom_splitter.setHandleWidth(4)
        self.bottom_splitter.setStyleSheet("QSplitter::handle { background: #444; }")

        for idx in range(1, 4):
            panel = QFrame()
            panel.setObjectName("heatmapPanel")
            panel.setStyleSheet(
                "#heatmapPanel { background-color: #0c0c0f; border: 1px solid #3a2a4a; border-radius: 4px; }"
            )
            p_layout = QVBoxLayout(panel)
            p_layout.setContentsMargins(4, 4, 4, 4)
            p_layout.setSpacing(2)

            # Header for bottom panel
            header_widget = QWidget()
            header_layout = QHBoxLayout(header_widget)
            header_layout.setContentsMargins(8, 3, 8, 3)
            header_layout.setSpacing(0)

            lbl = QLabel(f"Symbol {idx} — Net Vol GEX")
            lbl.setObjectName("panelNVGHeaderLabel")
            lbl.setStyleSheet(
                "#panelNVGHeaderLabel { font-size: 12px; font-weight: bold; color: #a060e0; }"
            )
            header_layout.addWidget(lbl)
            setattr(self, f"lbl_nvg_sym{idx}", lbl)
            header_layout.addStretch()
            p_layout.addWidget(header_widget)

            nvg_widget = NetVolGEXHeatmapWidget()
            p_layout.addWidget(nvg_widget, stretch=1)
            setattr(self, f"nvg{idx}", nvg_widget)
            setattr(self, f"_bot_panel{idx}", panel)

            self.bottom_splitter.addWidget(panel)

        self.bottom_splitter.setSizes([500, 500, 500])
        bottom_layout.addWidget(self.bottom_splitter)
        self.v_splitter.addWidget(self.bottom_container)

        # Equal top/bottom heights
        self.v_splitter.setSizes([500, 500])
        root.addWidget(self.v_splitter)

    # ------------------------------------------------------------------
    # Visibility toggles
    # ------------------------------------------------------------------
    def set_net_vol_gex_visible(self, visible: bool):
        """Show/hide the entire bottom Net Vol GEX row."""
        self._net_vol_visible = visible
        self.bottom_container.setVisible(visible)

    def set_symbol_visible(self, idx: int, visible: bool):
        """Show/hide column idx (1-based) in both top and bottom rows."""
        self._sym_visible[idx - 1] = visible
        top_panel = getattr(self, f"_top_panel{idx}")
        bot_panel = getattr(self, f"_bot_panel{idx}")
        top_panel.setVisible(visible)
        bot_panel.setVisible(visible)

    # ------------------------------------------------------------------
    # Net Vol GEX data updates
    # ------------------------------------------------------------------
    def update_nvg(self, idx: int, data: dict):
        """Feed data to Net Vol GEX panel idx (1-based)."""
        nvg = getattr(self, f"nvg{idx}")
        nvg.update_data(data)

    def set_nvg_sym_label(self, idx: int, symbol: str):
        lbl = getattr(self, f"lbl_nvg_sym{idx}")
        lbl.setText(f"Symbol {idx} — {symbol} — Net Vol GEX")

    # ------------------------------------------------------------------
    # Public helpers called by MainWindow
    # ------------------------------------------------------------------
    def set_sym1_label(self, symbol: str):
        self.lbl_sym1.setText(f"Symbol 1 — {symbol}")
        self.set_nvg_sym_label(1, symbol)

    def set_sym2_label(self, symbol: str):
        self.lbl_sym2.setText(f"Symbol 2 — {symbol}")
        self.set_nvg_sym_label(2, symbol)

    def set_sym3_label(self, symbol: str):
        self.lbl_sym3.setText(f"Symbol 3 — {symbol}")
        self.set_nvg_sym_label(3, symbol)

    def update_sym_stats(self, idx: int, stats: dict):
        """Update per-panel inline stats (Price, Net GEX, Call Wall, Put Wall)."""
        price = stats.get('price', 0)
        call_gex = stats.get('total_call_gex', 0)
        put_gex = stats.get('total_put_gex', 0)
        net_gex = call_gex + put_gex
        call_wall = stats.get('call_wall', None)
        put_wall = stats.get('put_wall', None)

        lbl_price = getattr(self, f"lbl_price{idx}")
        lbl_net_gex = getattr(self, f"lbl_net_gex{idx}")
        lbl_call_wall = getattr(self, f"lbl_call_wall{idx}")
        lbl_put_wall = getattr(self, f"lbl_put_wall{idx}")

        lbl_price.setText(f"Price: {price:.2f}")
        lbl_price.setStyleSheet("color: #e0e0e0;")

        if net_gex >= 0:
            lbl_net_gex.setText(f"Net GEX: +{net_gex/1e6:.1f}M")
            lbl_net_gex.setStyleSheet("color: #00ff00; font-weight: bold;")
        else:
            lbl_net_gex.setText(f"Net GEX: {net_gex/1e6:.1f}M")
            lbl_net_gex.setStyleSheet("color: #ff4444; font-weight: bold;")

        if call_wall:
            lbl_call_wall.setText(f"Call Wall: {call_wall:.0f}")
            lbl_call_wall.setStyleSheet("color: #00ff00;")
        else:
            lbl_call_wall.setText("Call Wall: --")
            lbl_call_wall.setStyleSheet("color: #888;")

        if put_wall:
            lbl_put_wall.setText(f"Put Wall: {put_wall:.0f}")
            lbl_put_wall.setStyleSheet("color: #ff4444;")
        else:
            lbl_put_wall.setText("Put Wall: --")
            lbl_put_wall.setStyleSheet("color: #888;")

    def set_strikes(self, num: int):
        for i in range(1, 4):
            getattr(self, f"heatmap{i}").set_num_strikes(num)
            getattr(self, f"nvg{i}").set_num_strikes(num)

    def clear_all(self):
        for i in range(1, 4):
            getattr(self, f"heatmap{i}").clear_history()
            getattr(self, f"nvg{i}").clear_history()

    # keep old name for any lingering call sites
    def clear_both(self):
        self.clear_all()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GEX Heatmap - Schwab API")
        self.setGeometry(100, 100, 1500, 950)
        
        self.data_feed = None
        self.data_feed2 = None
        self.data_feed3 = None
        self.stats = {}
        self.last_save_date = None
        self.current_symbol = None
        self.auto_started = False  # Track if we auto-started today
        self.available_expirations2 = []
        self.selected_expirations2 = []
        self.available_expirations3 = []
        self.selected_expirations3 = []
        
        self.setup_ui()
        self.apply_dark_theme()
        
        # Auto-save timer (check every 5 minutes)
        self.autosave_timer = QTimer()
        self.autosave_timer.timeout.connect(self._autosave_check)
        self.autosave_timer.start(300000)  # 5 minutes
        
        # Market hours scheduler (check every minute)
        self.market_hours_timer = QTimer()
        self.market_hours_timer.timeout.connect(self._check_market_hours)
        self.market_hours_timer.start(60000)  # 1 minute
        # Run immediately on startup if enabled
        if SchwabConfig.AUTO_START_ENABLED:
            QTimer.singleShot(2000, self._check_market_hours)  # Wait 2 seconds for UI to load
        
        # Cleanup old history on startup
        self.heatmap.cleanup_old_history()  # heatmap == intraday_tab.heatmap1
        print(f"\nHistory settings:")
        print(f"  Directory: {SchwabConfig.HISTORY_DIR}")
        print(f"  Days to keep: {SchwabConfig.HISTORY_DAYS_TO_KEEP}")
        
        if SchwabConfig.AUTO_START_ENABLED:
            print(f"\nAuto-start enabled:")
            print(f"  Market hours: {SchwabConfig.MARKET_START_TIME[0]:02d}:{SchwabConfig.MARKET_START_TIME[1]:02d} - "
                  f"{SchwabConfig.MARKET_END_TIME[0]:02d}:{SchwabConfig.MARKET_END_TIME[1]:02d} ET")
            print(f"  Symbol: {SchwabConfig.AUTO_START_SYMBOL}")
            print(f"  Interval: {SchwabConfig.AUTO_START_INTERVAL}s")
        print()
        
    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Control panel
        self.controls_frame = self._create_controls()
        layout.addWidget(self.controls_frame)
        
        # Tab widget at the bottom
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.South)  # Tabs at bottom like Excel
        
        # Tab 1: Intraday Heatmap (dual panel)
        self.intraday_tab = DualHeatmapTab()
        self.heatmap = self.intraday_tab.heatmap1  # backward-compat alias
        self.tab_widget.addTab(self.intraday_tab, "Intraday Heatmap")
        
        # Tab 2: Top 5 View
        self.top5_view = Top5Widget()
        self.tab_widget.addTab(self.top5_view, "Top 5 GEX/Volume")
        
        # Tab 3: Net GEX Grid
        self.gex_grid = NetGEXGridWidget()
        self.tab_widget.addTab(self.gex_grid, "Net GEX Grid")
        
        # Show/hide controls depending on active tab (hidden on Net GEX Grid)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        
        layout.addWidget(self.tab_widget, stretch=1)
        
        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Select symbol and click Start")
        
    def _create_controls(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("controlFrame")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(15, 12, 15, 12)
        
        # ── Symbols group: 1, 2, 3 side by side ──────────────────────
        lbl_syms = QLabel("Symbols:")
        layout.addWidget(lbl_syms)

        # Symbol count toggle (mirrors Net GEX Grid style)
        self._sym_count_btns = []
        for n in (1, 2, 3):
            btn = QPushButton(str(n))
            btn.setCheckable(True)
            btn.setFixedWidth(28)
            btn.setObjectName("countToggleBtn")
            btn.setStyleSheet("""
                QPushButton#countToggleBtn {
                    background-color: #2a2a2a; color: #aaa;
                    border: 1px solid #555; border-radius: 4px; padding: 3px;
                    font-size: 11px;
                }
                QPushButton#countToggleBtn:checked {
                    background-color: #2a5a6b; color: white; border-color: #3a8a9b;
                }
            """)
            btn.clicked.connect(lambda checked, x=n: self._set_intraday_sym_count(x))
            layout.addWidget(btn)
            self._sym_count_btns.append(btn)
        self._sym_count_btns[2].setChecked(True)  # default = 3
        self._intraday_sym_count = 3

        layout.addSpacing(6)

        lbl_s1 = QLabel("1:")
        lbl_s1.setStyleSheet("color: #ccc;")
        layout.addWidget(lbl_s1)
        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText("SPX")
        self.symbol_input.setText("SPX")
        self.symbol_input.setFixedWidth(65)
        self.symbol_input.setObjectName("symbolInput")
        layout.addWidget(self.symbol_input)

        layout.addSpacing(4)

        lbl_s2 = QLabel("2:")
        lbl_s2.setStyleSheet("color: #4a9eff; font-weight: bold;")
        layout.addWidget(lbl_s2)
        self.symbol2_input = QLineEdit()
        self.symbol2_input.setPlaceholderText("SPY")
        self.symbol2_input.setText("SPY")
        self.symbol2_input.setFixedWidth(65)
        self.symbol2_input.setObjectName("symbolInput")
        layout.addWidget(self.symbol2_input)

        layout.addSpacing(4)

        lbl_s3 = QLabel("3:")
        lbl_s3.setStyleSheet("color: #66ffaa; font-weight: bold;")
        layout.addWidget(lbl_s3)
        self.symbol3_input = QLineEdit()
        self.symbol3_input.setPlaceholderText("QQQ")
        self.symbol3_input.setText("QQQ")
        self.symbol3_input.setFixedWidth(65)
        self.symbol3_input.setObjectName("symbolInput")
        layout.addWidget(self.symbol3_input)

        layout.addSpacing(10)

        # Load expirations button
        self.btn_load_exp = QPushButton("Load Expiry")
        self.btn_load_exp.setObjectName("loadButton")
        self.btn_load_exp.clicked.connect(self._load_expirations)
        self.btn_load_exp.setToolTip("Fetch available expiration dates from API")
        layout.addWidget(self.btn_load_exp)
        
        layout.addSpacing(10)
        
        # Expiration multi-select (shows as button that opens dialog)
        self.btn_select_exp = QPushButton("Select Expiry (0)")
        self.btn_select_exp.setObjectName("expButton")
        self.btn_select_exp.clicked.connect(self._show_expiration_dialog)
        self.btn_select_exp.setToolTip("Select up to 10 expiration dates")
        self.btn_select_exp.setEnabled(False)
        layout.addWidget(self.btn_select_exp)
        
        # Store expirations data
        self.available_expirations = []
        self.selected_expirations = []
        
        layout.addSpacing(15)
        
        # Strike count (total strikes including ATM)
        layout.addWidget(QLabel("Strikes:"))
        self.strikes_combo = QComboBox()
        self.strikes_combo.addItems(["30", "50", "75", "100"])
        self.strikes_combo.setCurrentText("100")
        self.strikes_combo.setToolTip("Total strikes (puts + ATM + calls)")
        self.strikes_combo.currentTextChanged.connect(self._on_strikes_changed)
        layout.addWidget(self.strikes_combo)
        
        layout.addSpacing(15)
        
        # Update interval
        layout.addWidget(QLabel("Interval:"))
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["30 sec", "1 min", "2 min", "5 min"])
        self.interval_combo.currentTextChanged.connect(self._on_interval_changed)
        layout.addWidget(self.interval_combo)
        
        layout.addSpacing(15)
        
        # Demo mode checkbox
        self.demo_check = QCheckBox("Demo Mode")
        self.demo_check.setChecked(True)  # Default to demo
        self.demo_check.setToolTip("Use simulated data (no API required)")
        layout.addWidget(self.demo_check)
        
        layout.addSpacing(10)
        
        # Auto-start checkbox
        self.auto_start_check = QCheckBox("Auto-Start")
        self.auto_start_check.setObjectName("autoStartCheck")
        self.auto_start_check.setChecked(SchwabConfig.AUTO_START_ENABLED)
        self.auto_start_check.setToolTip(f"Automatically start/stop during market hours\n"
                                         f"({SchwabConfig.MARKET_START_TIME[0]:02d}:{SchwabConfig.MARKET_START_TIME[1]:02d} - "
                                         f"{SchwabConfig.MARKET_END_TIME[0]:02d}:{SchwabConfig.MARKET_END_TIME[1]:02d} ET)")
        self.auto_start_check.toggled.connect(self._toggle_auto_start)
        layout.addWidget(self.auto_start_check)

        layout.addSpacing(6)

        # Net Vol GEX toggle
        self.net_vol_gex_check = QCheckBox("Net Vol GEX")
        self.net_vol_gex_check.setObjectName("netVolGexCheck")
        self.net_vol_gex_check.setChecked(True)
        self.net_vol_gex_check.setToolTip(
            "Show/hide Net Volume GEX panels\n"
            "Purple = bullish (call vol dominant)\n"
            "Orange = bearish (put vol dominant)"
        )
        self.net_vol_gex_check.toggled.connect(self._toggle_net_vol_gex)
        layout.addWidget(self.net_vol_gex_check)
        
        layout.addSpacing(20)
        
        # Start button
        self.btn_start = QPushButton("▶ Start")
        self.btn_start.setObjectName("startButton")
        self.btn_start.clicked.connect(self.start_feed)
        layout.addWidget(self.btn_start)
        
        # Stop button
        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setObjectName("stopButton")
        self.btn_stop.clicked.connect(self.stop_feed)
        self.btn_stop.setEnabled(False)
        layout.addWidget(self.btn_stop)
        
        # Clear button
        btn_clear = QPushButton("Clear")
        btn_clear.setObjectName("clearButton")
        btn_clear.clicked.connect(self._clear_all_history)
        layout.addWidget(btn_clear)
        
        # Load History button
        btn_load_history = QPushButton("📂 Load History")
        btn_load_history.setObjectName("loadHistoryButton")
        btn_load_history.clicked.connect(self._load_history_dialog)
        btn_load_history.setToolTip("Load saved history from previous days")
        layout.addWidget(btn_load_history)
        
        # Export CSV button
        btn_export = QPushButton("📥 Export CSV")
        btn_export.setObjectName("exportButton")
        btn_export.clicked.connect(self._export_csv)
        btn_export.setToolTip("Export history to CSV file")
        layout.addWidget(btn_export)
        
        layout.addStretch()
        
        return frame
        
    def apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #121212;
                color: #e0e0e0;
            }
            
            #controlFrame {
                background-color: #1e1e1e;
                border-radius: 8px;
                border: 1px solid #333;
            }
            
            QLabel {
                color: #ccc;
                font-size: 12px;
            }
            
            #priceLabel {
                font-size: 16px;
                font-weight: bold;
                color: #ffffff;
            }
            
            #gammaFlipLabel {
                color: #ff8800;
                font-weight: bold;
            }
            
            #callWallLabel {
                color: #00ff00;
            }
            
            #putWallLabel {
                color: #ff4444;
            }
            
            #pcRatioLabel {
                color: #aaaaff;
            }
            
            #netGexLabel {
                font-weight: bold;
            }
            
            QComboBox {
                padding: 6px 12px;
                background-color: #2a2a2a;
                border: 1px solid #444;
                border-radius: 4px;
                color: #fff;
                min-width: 80px;
            }
            
            QComboBox:hover {
                border-color: #666;
            }
            
            QComboBox::drop-down {
                border: none;
            }
            
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                border: 1px solid #444;
                selection-background-color: #444;
            }
            
            QLineEdit {
                padding: 6px 10px;
                background-color: #2a2a2a;
                border: 1px solid #444;
                border-radius: 4px;
                color: #fff;
            }
            
            QLineEdit:focus {
                border-color: #0078d4;
            }
            
            QLineEdit::placeholder {
                color: #666;
            }
            
            #symbolInput {
                font-weight: bold;
                text-transform: uppercase;
            }
            
            #expInput {
                font-family: monospace;
            }
            
            QCheckBox {
                color: #ccc;
                spacing: 8px;
            }
            
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            
            QPushButton {
                padding: 8px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }
            
            #startButton {
                background-color: #1a6b2e;
                color: white;
                border: none;
            }
            
            #startButton:hover {
                background-color: #228b3b;
            }
            
            #startButton:disabled {
                background-color: #333;
                color: #666;
            }
            
            #stopButton {
                background-color: #6b1a1a;
                color: white;
                border: none;
            }
            
            #stopButton:hover {
                background-color: #8b2222;
            }
            
            #stopButton:disabled {
                background-color: #333;
                color: #666;
            }
            
            #clearButton {
                background-color: #333;
                color: #fff;
                border: 1px solid #444;
            }
            
            #clearButton:hover {
                background-color: #444;
            }
            
            #loadButton {
                background-color: #1a4a6b;
                color: white;
                border: none;
                padding: 6px 14px;
            }
            
            #loadButton:hover {
                background-color: #226b8b;
            }
            
            #expButton {
                background-color: #4a3a6b;
                color: white;
                border: none;
                padding: 6px 14px;
                min-width: 150px;
            }
            
            #expButton:hover {
                background-color: #5a4a7b;
            }
            
            #expButton:disabled {
                background-color: #333;
                color: #666;
            }
            
            #exportButton {
                background-color: #2a5a3a;
                color: white;
                border: none;
                padding: 6px 14px;
            }
            
            #exportButton:hover {
                background-color: #3a6a4a;
            }
            
            QTabWidget::pane {
                border: 1px solid #333;
                background-color: #121212;
            }
            
            QTabBar::tab {
                background-color: #1e1e1e;
                color: #aaa;
                border: 1px solid #333;
                padding: 8px 20px;
                margin-right: 2px;
            }
            
            QTabBar::tab:selected {
                background-color: #2a2a2a;
                color: #fff;
                border-bottom: 2px solid #4a9eff;
            }
            
            QTabBar::tab:hover {
                background-color: #333;
            }
            
            QStatusBar {
                background-color: #1a1a1a;
                color: #888;
                border-top: 1px solid #333;
            }
            
            #heatmapPanel {
                background-color: #0f0f0f;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
            }
            
            #panelHeader {
                background-color: #1a1a1a;
                border-bottom: 1px solid #2a2a2a;
                border-radius: 0px;
            }
            
            #panelHeaderLabel {
                font-size: 13px;
                font-weight: bold;
                color: #4a9eff;
            }
            
            #panelHint {
                font-size: 11px;
                color: #555;
                font-style: italic;
            }
            
            #loadHistoryButton {
                background-color: #1a4a6b;
                color: white;
                border: none;
                padding: 6px 14px;
            }
            
            #loadHistoryButton:hover {
                background-color: #226b8b;
            }
        """)
        
    def _get_interval_seconds(self) -> int:
        text = self.interval_combo.currentText()
        if "30" in text:
            return 30
        elif "1" in text:
            return 60
        elif "2" in text:
            return 120
        else:
            return 300
            
    def _on_strikes_changed(self, strikes: str):
        num = int(strikes)
        self.intraday_tab.set_strikes(num)
        if self.data_feed:
            self.data_feed.set_num_strikes(num)
            
    def _on_interval_changed(self, interval: str):
        secs = self._get_interval_seconds()
        if self.data_feed:
            self.data_feed.set_interval(secs)
        if self.data_feed2:
            self.data_feed2.set_interval(secs)
        if self.data_feed3:
            self.data_feed3.set_interval(secs)
            
    def _load_expirations(self):
        """Load available expiration dates from API"""
        symbol = self.symbol_input.text().strip().upper()
        if not symbol:
            QMessageBox.warning(self, "Input Required", "Please enter a symbol first.")
            return
            
        if self.demo_check.isChecked():
            # Generate demo expirations - weekdays only, including today
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            expirations = []
            
            # Start from today and add weekdays
            current = today
            days_added = 0
            while len(expirations) < 60:
                # Skip weekends (5=Saturday, 6=Sunday)
                if current.weekday() < 5:
                    expirations.append(current.strftime('%Y-%m-%d'))
                current += timedelta(days=1)
                days_added += 1
                if days_added > 200:  # Safety limit
                    break
            
            self.available_expirations = expirations
            self.selected_expirations = expirations[:3]  # Default select first 3
            # Symbols 2 and 3 share the same expiration list
            self.available_expirations2 = expirations
            self.selected_expirations2 = expirations[:3]
            self.available_expirations3 = expirations
            self.selected_expirations3 = expirations[:3]
            self.btn_select_exp.setEnabled(True)
            self.btn_select_exp.setText(f"Select Expiry ({len(self.selected_expirations)})")
            self.status.showMessage(f"Loaded {len(expirations)} demo expirations (weekdays only)")
            return
            
        # Real API call
        self.status.showMessage("Loading expirations...")
        self.btn_load_exp.setEnabled(False)
        
        try:
            # Create temporary feed to fetch expirations
            temp_feed = SchwabDataFeed(symbol, 100, 30)
            temp_feed.status_updated.connect(self.on_status)
            
            if not temp_feed._ensure_token():
                # Need to authenticate first
                auth_url = temp_feed.get_auth_url()
                self._handle_auth_for_expirations(temp_feed)
                return
                
            # Fetch expirations
            expirations = temp_feed.fetch_expirations()
            
            if expirations:
                self.available_expirations = expirations  # all available
                self.selected_expirations = expirations[:3]  # Default select first 3
                # Symbols 2 and 3 share the same expiration list
                self.available_expirations2 = self.available_expirations
                self.selected_expirations2 = list(self.selected_expirations)
                self.available_expirations3 = self.available_expirations
                self.selected_expirations3 = list(self.selected_expirations)
                self.btn_select_exp.setEnabled(True)
                self.btn_select_exp.setText(f"Select Expiry ({len(self.selected_expirations)})")
                self.status.showMessage(f"Loaded {len(self.available_expirations)} expirations for {symbol}")
            else:
                self.status.showMessage("No expirations found")
                
        except Exception as e:
            self.status.showMessage(f"Error loading expirations: {e}")
        finally:
            self.btn_load_exp.setEnabled(True)
            
    def _handle_auth_for_expirations(self, temp_feed):
        """Handle authentication when loading expirations"""
        import urllib.parse
        
        auth_url = temp_feed.get_auth_url()
        webbrowser.open(auth_url)
        
        from PyQt6.QtWidgets import QInputDialog
        
        code, ok = QInputDialog.getText(
            self,
            "Schwab Authentication",
            "After logging in, paste the ENTIRE redirect URL here:",
            QLineEdit.EchoMode.Normal
        )
        
        if ok and code:
            try:
                if 'code=' in code:
                    parsed = urllib.parse.urlparse(code)
                    params = urllib.parse.parse_qs(parsed.query)
                    auth_code = params.get('code', [''])[0]
                else:
                    auth_code = code
                    
                auth_code = urllib.parse.unquote(auth_code)
                
                if auth_code and temp_feed.exchange_code(auth_code):
                    # Now fetch expirations
                    expirations = temp_feed.fetch_expirations()
                    if expirations:
                        self.available_expirations = expirations  # all available
                        self.selected_expirations = expirations[:3]
                        self.btn_select_exp.setEnabled(True)
                        self.btn_select_exp.setText(f"Select Expiry ({len(self.selected_expirations)})")
                        self.status.showMessage(f"Loaded {len(self.available_expirations)} expirations")
                else:
                    QMessageBox.warning(self, "Error", "Authentication failed")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed: {e}")
        
        self.btn_load_exp.setEnabled(True)
        
    def _show_expiration_dialog(self):
        """Show dialog to select multiple expirations"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QDialogButtonBox, QListWidget, QListWidgetItem, QLabel
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Expirations")
        dialog.setMinimumWidth(300)
        dialog.setMinimumHeight(400)
        
        layout = QVBoxLayout(dialog)
        
        label = QLabel("Select expiration dates:")
        layout.addWidget(label)
        
        # List widget with checkboxes
        list_widget = QListWidget()
        list_widget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        
        for exp in self.available_expirations:
            item = QListWidgetItem(exp)
            list_widget.addItem(item)
            if exp in self.selected_expirations:
                item.setSelected(True)
                
        layout.addWidget(list_widget)
        
        # Info label
        info_label = QLabel(f"Selected: {len(self.selected_expirations)}")
        layout.addWidget(info_label)
        
        def update_count():
            count = len(list_widget.selectedItems())
            info_label.setText(f"Selected: {count}")
            info_label.setStyleSheet("")
                
        list_widget.itemSelectionChanged.connect(update_count)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = [item.text() for item in list_widget.selectedItems()]
            if len(selected) == 0:
                QMessageBox.warning(self, "None Selected", "Please select at least 1 expiration.")
                return
                
            self.selected_expirations = sorted(selected)
            self.selected_expirations2 = list(self.selected_expirations)  # keep Symbol 2 in sync
            self.selected_expirations3 = list(self.selected_expirations)  # keep Symbol 3 in sync
            self.btn_select_exp.setText(f"Select Expiry ({len(self.selected_expirations)})")
            self.status.showMessage(f"Selected {len(self.selected_expirations)} expirations (applied to both symbols)")
            
    def start_feed(self):
        symbol = self.symbol_input.text().strip().upper()
        symbol2 = self.symbol2_input.text().strip().upper()
        symbol3 = self.symbol3_input.text().strip().upper()
        num_strikes = int(self.strikes_combo.currentText())
        interval = self._get_interval_seconds()
        
        # Validate Symbol 1
        if not symbol:
            QMessageBox.warning(self, "Input Required", "Please enter a symbol.")
            return
            
        # Check expirations for Symbol 1
        if not self.selected_expirations:
            if self.demo_check.isChecked():
                self._load_expirations()
            else:
                QMessageBox.warning(
                    self, 
                    "Expirations Required", 
                    "Please click 'Load Expiry' first, then select the dates."
                )
                return
        
        # ── Feed 1 ────────────────────────────────────────────────────
        if self.demo_check.isChecked():
            self.data_feed = DemoDataFeed(symbol, num_strikes, interval)
            self.data_feed.set_expirations(self.selected_expirations)
        else:
            if not SchwabConfig.CLIENT_ID or not SchwabConfig.CLIENT_SECRET:
                QMessageBox.warning(
                    self,
                    "API Configuration Required",
                    "Please configure your Schwab API credentials in the SchwabConfig class.\n\n"
                    "1. Go to https://developer.schwab.com\n"
                    "2. Create an app and get your Client ID and Secret\n"
                    "3. Update the CLIENT_ID and CLIENT_SECRET in the code\n\n"
                    "For now, you can use Demo Mode."
                )
                return
            self.data_feed = SchwabDataFeed(symbol, num_strikes, interval)
            self.data_feed.set_expirations(self.selected_expirations)
            self.data_feed.auth_required.connect(self._on_auth_required)
        
        self.gex_grid.set_data_feed(self.data_feed)
        self.data_feed.data_updated.connect(self.on_data)
        self.data_feed.status_updated.connect(self.on_status)
        self.data_feed.start()
        self.intraday_tab.set_sym1_label(symbol)
        
        # ── Feed 2 (optional — only if Symbol 2 is filled in) ─────────
        if symbol2:
            # Expirations are shared with Symbol 1; auto-load if not yet populated
            if not self.selected_expirations2:
                self._load_expirations()
            
            if self.demo_check.isChecked():
                self.data_feed2 = DemoDataFeed(symbol2, num_strikes, interval)
                self.data_feed2.set_expirations(self.selected_expirations2)
            else:
                self.data_feed2 = SchwabDataFeed(symbol2, num_strikes, interval)
                self.data_feed2.set_expirations(self.selected_expirations2)
            
            self.data_feed2.data_updated.connect(self.on_data2)
            self.data_feed2.status_updated.connect(self.on_status)
            self.data_feed2.start()
            self.intraday_tab.set_sym2_label(symbol2)

        # ── Feed 3 (optional) ─────────────────────────────────────────
        if symbol3:
            if not self.selected_expirations3:
                self._load_expirations()

            if self.demo_check.isChecked():
                self.data_feed3 = DemoDataFeed(symbol3, num_strikes, interval)
                self.data_feed3.set_expirations(self.selected_expirations3)
            else:
                self.data_feed3 = SchwabDataFeed(symbol3, num_strikes, interval)
                self.data_feed3.set_expirations(self.selected_expirations3)

            self.data_feed3.data_updated.connect(self.on_data3)
            self.data_feed3.status_updated.connect(self.on_status)
            self.data_feed3.start()
            self.intraday_tab.set_sym3_label(symbol3)
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
    def stop_feed(self):
        # Auto-save before stopping
        if self.data_feed and self.heatmap.history:
            self._autosave()
            
        if self.data_feed:
            self.data_feed.stop()
            self.data_feed = None
        
        if self.data_feed2:
            self.data_feed2.stop()
            self.data_feed2 = None

        if self.data_feed3:
            self.data_feed3.stop()
            self.data_feed3 = None
            
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status.showMessage("Stopped")
    
    def _autosave_check(self):
        """Check if we need to auto-save (called every 5 minutes)"""
        if not self.heatmap.history:
            return
        
        current_date = datetime.now().date()
        
        # Save if we have data and either:
        # 1. First save of the day, or
        # 2. Date has changed (new day)
        if self.last_save_date is None or current_date != self.last_save_date:
            self._autosave()
    
    def _autosave(self):
        """Save current history to file"""
        if not self.heatmap.history:
            return
        
        symbol = self.symbol_input.text().strip().upper()
        if not symbol:
            return
        
        if self.heatmap.save_history_to_file(symbol):
            self.last_save_date = datetime.now().date()
            self.status.showMessage(f"Auto-saved history for {symbol}", 3000)
    
    def _check_market_hours(self):
        """Check if we should auto-start or auto-stop based on market hours"""
        if not self.auto_start_check.isChecked():
            return
        
        # Get current time in Eastern Time
        if HAS_PYTZ:
            et_tz = pytz.timezone('US/Eastern')
            now_et = datetime.now(et_tz)
        else:
            # Fallback to local time if pytz not available
            now_et = datetime.now()
        
        current_time = (now_et.hour, now_et.minute)
        current_date = now_et.date()
        
        # Check if it's a weekday (Monday=0, Sunday=6)
        if now_et.weekday() >= 5:  # Saturday or Sunday
            return
        
        # Market start time
        market_start = SchwabConfig.MARKET_START_TIME
        market_end = SchwabConfig.MARKET_END_TIME
        
        # Check if we're in market hours
        is_market_hours = (market_start[0], market_start[1]) <= current_time <= (market_end[0], market_end[1])
        
        # Auto-start logic
        if is_market_hours and not self.data_feed and not self.auto_started:
            print(f"\n{'='*60}")
            print(f"AUTO-START: Market hours detected at {now_et.strftime('%H:%M:%S ET')}")
            print(f"{'='*60}")
            
            # Set default parameters
            self.symbol_input.setText(SchwabConfig.AUTO_START_SYMBOL)
            self.interval_combo.setCurrentText(f"{SchwabConfig.AUTO_START_INTERVAL}s")
            self.strikes_combo.setCurrentText(str(SchwabConfig.AUTO_START_STRIKES))
            # Symbol 2 uses whatever the user has entered; expirations auto-load in start_feed
            
            # Start the feed
            self.start_feed()
            self.auto_started = True
            self.status.showMessage(f"Auto-started at {now_et.strftime('%H:%M ET')}", 10000)
        
        # Auto-stop logic
        elif not is_market_hours and self.data_feed and self.auto_started:
            print(f"\n{'='*60}")
            print(f"AUTO-STOP: Market hours ended at {now_et.strftime('%H:%M:%S ET')}")
            print(f"{'='*60}")
            
            self.stop_feed()
            self.status.showMessage(f"Auto-stopped at {now_et.strftime('%H:%M ET')}", 10000)
        
        # Reset auto_started flag at midnight (for next trading day)
        if current_time < (market_start[0], market_start[1]) and self.auto_started:
            # Check if we've crossed midnight (new day)
            if not hasattr(self, '_last_check_date') or self._last_check_date != current_date:
                self.auto_started = False
                print(f"Reset auto-start flag for new trading day: {current_date}")
        
        self._last_check_date = current_date
    
    def _toggle_auto_start(self, enabled: bool):
        """Toggle auto-start feature on/off"""
        if enabled:
            self.status.showMessage("Auto-start enabled - will start/stop during market hours", 5000)
            # Check immediately in case we're in market hours
            QTimer.singleShot(1000, self._check_market_hours)

    def _set_intraday_sym_count(self, count: int):
        """Handle symbol count toggle (1/2/3) for Intraday Heatmap tab."""
        self._intraday_sym_count = count
        for i, btn in enumerate(self._sym_count_btns):
            btn.setChecked((i + 1) == count)
        for idx in range(1, 4):
            self.intraday_tab.set_symbol_visible(idx, idx <= count)

    def _toggle_net_vol_gex(self, visible: bool):
        """Show/hide the Net Vol GEX bottom row on the Intraday Heatmap tab."""
        self.intraday_tab.set_net_vol_gex_visible(visible)

    def _toggle_auto_start_off_message(self):
        self.status.showMessage("Auto-start disabled", 3000)
    
    def _load_history_dialog(self):
        """Show dialog to load history from previous days"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QPushButton, QRadioButton, QButtonGroup
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Load History")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        # Info label
        info = QLabel(
            f"Load saved history from previous days.\n"
            f"History directory: {SchwabConfig.HISTORY_DIR}\n"
            f"Days retained: {SchwabConfig.HISTORY_DAYS_TO_KEEP}"
        )
        layout.addWidget(info)
        
        # Symbol (use current symbol)
        symbol = self.symbol_input.text().strip().upper()
        symbol_label = QLabel(f"Symbol: <b>{symbol if symbol else 'Not set'}</b>")
        layout.addWidget(symbol_label)
        
        # Load mode selection
        mode_group = QButtonGroup(dialog)
        
        single_day_radio = QRadioButton("Load single day")
        single_day_radio.setChecked(True)
        mode_group.addButton(single_day_radio)
        layout.addWidget(single_day_radio)
        
        multi_day_radio = QRadioButton("Load multiple days")
        mode_group.addButton(multi_day_radio)
        layout.addWidget(multi_day_radio)
        
        # Days back selector
        days_layout = QHBoxLayout()
        days_layout.addWidget(QLabel("Days back:"))
        days_spin = QSpinBox()
        days_spin.setMinimum(0)
        days_spin.setMaximum(SchwabConfig.HISTORY_DAYS_TO_KEEP)
        days_spin.setValue(1)
        days_spin.setToolTip("0 = today, 1 = yesterday, etc.")
        days_layout.addWidget(days_spin)
        days_layout.addStretch()
        layout.addLayout(days_layout)
        
        # Number of days for multi-day mode
        multi_days_layout = QHBoxLayout()
        multi_days_layout.addWidget(QLabel("Number of days:"))
        multi_days_spin = QSpinBox()
        multi_days_spin.setMinimum(1)
        multi_days_spin.setMaximum(min(30, SchwabConfig.HISTORY_DAYS_TO_KEEP))
        multi_days_spin.setValue(5)
        multi_days_spin.setEnabled(False)
        multi_days_layout.addWidget(multi_days_spin)
        multi_days_layout.addStretch()
        layout.addLayout(multi_days_layout)
        
        # Enable/disable controls based on mode
        def on_mode_changed():
            is_multi = multi_day_radio.isChecked()
            days_spin.setEnabled(not is_multi)
            multi_days_spin.setEnabled(is_multi)
        
        single_day_radio.toggled.connect(on_mode_changed)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_load = QPushButton("Load")
        btn_cancel = QPushButton("Cancel")
        btn_layout.addWidget(btn_load)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        btn_cancel.clicked.connect(dialog.reject)
        
        def on_load():
            if not symbol:
                QMessageBox.warning(dialog, "Error", "Please enter a symbol first")
                return
            
            if single_day_radio.isChecked():
                # Single day load
                target_date = datetime.now().date() - timedelta(days=days_spin.value())
                if self.heatmap.load_history_from_file(symbol, target_date):
                    self.status.showMessage(f"Loaded history for {symbol} from {target_date}", 5000)
                    dialog.accept()
                else:
                    QMessageBox.warning(dialog, "Error", f"No history found for {symbol} on {target_date}")
            else:
                # Multi-day load
                days_to_load = multi_days_spin.value()
                if self.heatmap.load_multi_day_history(symbol, days_to_load):
                    self.status.showMessage(f"Loaded {days_to_load} days of history for {symbol}", 5000)
                    dialog.accept()
                else:
                    QMessageBox.warning(dialog, "Error", f"No history found for {symbol}")
        
        btn_load.clicked.connect(on_load)
        
        dialog.exec()
    
    def _clear_all_history(self):
        """Clear history from all widgets"""
        self.intraday_tab.clear_all()
        self.top5_view.clear_history()
        self.gex_grid.clear_history()
    
    def _export_csv(self):
        """Export intraday heatmap history to CSV — supports all 3 panels."""
        from PyQt6.QtWidgets import (QFileDialog, QDialog, QVBoxLayout, QLabel,
                                     QRadioButton, QButtonGroup, QPushButton,
                                     QHBoxLayout, QCheckBox, QGroupBox)

        # Collect available panels (only those that have data)
        panel_info = [
            (1, self.intraday_tab.heatmap1,
             self.symbol_input.text().strip().upper() or "P1"),
            (2, self.intraday_tab.heatmap2,
             self.symbol2_input.text().strip().upper() or "P2"),
            (3, self.intraday_tab.heatmap3,
             self.symbol3_input.text().strip().upper() or "P3"),
        ]
        available = [(n, hm, sym) for n, hm, sym in panel_info if hm.history]

        if not available:
            QMessageBox.warning(self, "No Data", "No history data to export.")
            return

        # ── Build dialog ─────────────────────────────────────────────
        dialog = QDialog(self)
        dialog.setWindowTitle("Export Heatmap History")
        dialog.setMinimumWidth(380)
        layout = QVBoxLayout(dialog)

        # Export mode (current session vs all saved files)
        layout.addWidget(QLabel("<b>Export source:</b>"))
        mode_group = QButtonGroup(dialog)
        current_radio = QRadioButton("Current session only (data in memory)")
        current_radio.setChecked(True)
        mode_group.addButton(current_radio)
        layout.addWidget(current_radio)

        all_radio = QRadioButton("All saved history files (on disk)")
        mode_group.addButton(all_radio)
        layout.addWidget(all_radio)

        layout.addSpacing(8)

        # Panel selection checkboxes
        layout.addWidget(QLabel("<b>Panels to export:</b>"))
        panel_checks = []
        for n, hm, sym in available:
            chk = QCheckBox(f"Panel {n}  —  {sym}  ({len(hm.history)} records in memory)")
            chk.setChecked(True)
            layout.addWidget(chk)
            panel_checks.append((n, hm, sym, chk))

        layout.addSpacing(8)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_export = QPushButton("Export")
        btn_cancel = QPushButton("Cancel")
        btn_layout.addWidget(btn_export)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        btn_cancel.clicked.connect(dialog.reject)

        def on_export():
            dialog.accept()
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            exported = []
            errors = []

            for n, hm, sym, chk in panel_checks:
                if not chk.isChecked():
                    continue

                if current_radio.isChecked():
                    default_name = f"gex_history_{sym}_{timestamp}.csv"
                    filepath, _ = QFileDialog.getSaveFileName(
                        self,
                        f"Export Panel {n} ({sym}) — Current Session",
                        default_name,
                        "CSV Files (*.csv);;All Files (*)"
                    )
                    if filepath:
                        if hm.export_to_csv(filepath):
                            exported.append(f"Panel {n} ({sym}): {len(hm.history)} records → {filepath}")
                        else:
                            errors.append(f"Panel {n} ({sym}): export failed")
                else:
                    default_name = f"gex_all_history_{sym}.csv"
                    filepath, _ = QFileDialog.getSaveFileName(
                        self,
                        f"Export Panel {n} ({sym}) — All Saved History",
                        default_name,
                        "CSV Files (*.csv);;All Files (*)"
                    )
                    if filepath:
                        records = self._export_all_history_to_csv(filepath, sym)
                        if records > 0:
                            exported.append(f"Panel {n} ({sym}): {records} records → {filepath}")
                        else:
                            errors.append(f"Panel {n} ({sym}): no saved history found")

            if exported:
                msg = "Export complete:\n\n" + "\n".join(exported)
                if errors:
                    msg += "\n\nWarnings:\n" + "\n".join(errors)
                QMessageBox.information(self, "Export Complete", msg)
            elif errors:
                QMessageBox.warning(self, "Export Failed", "\n".join(errors))

        btn_export.clicked.connect(on_export)
        dialog.exec()

    def _export_all_history_to_csv(self, filepath: str, symbol: str) -> int:
        """
        Export all saved history files for a symbol to a single CSV.
        
        Returns:
            Number of records exported
        """
        try:
            if not os.path.exists(SchwabConfig.HISTORY_DIR):
                print(f"History directory not found: {SchwabConfig.HISTORY_DIR}")
                return 0
            
            # Find all history files for this symbol
            all_history = []
            files_found = 0
            
            for filename in sorted(os.listdir(SchwabConfig.HISTORY_DIR)):
                if filename.startswith(f"{symbol}_") and filename.endswith('.pkl'):
                    try:
                        filepath_pkl = os.path.join(SchwabConfig.HISTORY_DIR, filename)
                        with open(filepath_pkl, 'rb') as f:
                            history_data = pickle.load(f)
                            all_history.extend(history_data['history'])
                            files_found += 1
                            print(f"  Loaded {len(history_data['history'])} records from {filename}")
                    except Exception as e:
                        print(f"  Error loading {filename}: {e}")
            
            if not all_history:
                print(f"No history files found for {symbol}")
                return 0
            
            # Sort by timestamp
            all_history.sort(key=lambda x: x['timestamp'])
            
            print(f"Exporting {len(all_history)} records from {files_found} files...")
            
            # Write to CSV
            import csv
            with open(filepath, 'w', newline='') as f:
                writer = csv.writer(f)
                
                # Write header
                header = ['timestamp', 'symbol', 'price', 'atm']
                
                # Get all unique strikes from first entry
                if all_history:
                    first = all_history[0]
                    if 'strikes' in first:
                        strikes = first['strikes']
                        for strike in strikes:
                            header.append(f'GEX_{strike}')
                
                writer.writerow(header)
                
                # Write data rows
                for entry in all_history:
                    row = [
                        entry['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                        entry.get('symbol', symbol),
                        entry.get('price', ''),
                        entry.get('atm', ''),
                    ]
                    
                    if 'gex' in entry:
                        row.extend(entry['gex'])
                    
                    writer.writerow(row)
            
            print(f"✓ Export complete: {len(all_history)} records")
            return len(all_history)
            
        except Exception as e:
            print(f"Error exporting all history: {e}")
            return 0
        
    def _on_auth_required(self, auth_url: str):
        """Handle Schwab OAuth flow"""
        import urllib.parse
        
        # Open browser for authentication
        import webbrowser
        webbrowser.open(auth_url)
        
        # Show dialog to get the authorization code
        from PyQt6.QtWidgets import QInputDialog
        
        code, ok = QInputDialog.getText(
            self,
            "Schwab Authentication",
            "After logging in, you'll be redirected to a URL like:\n"
            "https://127.0.0.1/?code=XXXXX&session=...\n\n"
            "Paste the ENTIRE redirect URL here:",
            QLineEdit.EchoMode.Normal
        )
        
        if ok and code:
            # Extract the code from the URL
            try:
                if 'code=' in code:
                    # Parse from full URL
                    parsed = urllib.parse.urlparse(code)
                    params = urllib.parse.parse_qs(parsed.query)
                    auth_code = params.get('code', [''])[0]
                else:
                    # User pasted just the code
                    auth_code = code
                    
                # URL decode the code (handles %40 -> @, etc.)
                auth_code = urllib.parse.unquote(auth_code)
                
                if auth_code and self.data_feed.exchange_code(auth_code):
                    QMessageBox.information(self, "Success", "Authentication successful!")
                    self.data_feed.start()
                else:
                    QMessageBox.warning(self, "Error", "Authentication failed. Please try again.")
                    self.btn_start.setEnabled(True)
                    self.btn_stop.setEnabled(False)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to parse code: {e}")
                self.btn_start.setEnabled(True)
                self.btn_stop.setEnabled(False)
        else:
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
        
    def on_data(self, data: dict):
        self.stats = self.heatmap.update_data(data)
        self.top5_view.update_data(data)
        # Grid widget does NOT auto-update - it's manual refresh only
        self.intraday_tab.update_sym_stats(1, self.stats)
        self.intraday_tab.update_nvg(1, data)

    def on_data2(self, data: dict):
        stats2 = self.intraday_tab.heatmap2.update_data(data)
        self.intraday_tab.update_sym_stats(2, stats2)
        self.intraday_tab.update_nvg(2, data)

    def on_data3(self, data: dict):
        stats3 = self.intraday_tab.heatmap3.update_data(data)
        self.intraday_tab.update_sym_stats(3, stats3)
        self.intraday_tab.update_nvg(3, data)
        
    def on_status(self, msg: str):
        self.status.showMessage(msg)
        
    def _on_tab_changed(self, index: int):
        """Show main controls only on Intraday Heatmap (0) and Top 5 (1) tabs."""
        self.controls_frame.setVisible(index in (0, 1))

    def closeEvent(self, event):
        self.stop_feed()
        event.accept()


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def main():
    print("=" * 60)
    print("  GEX Heatmap - Schwab API v6.2 (Multi-Panel Export + Grid Auto-Refresh)")
    print("=" * 60)
    print()
    print("FEATURES:")
    print("  ✓ Actual GEX magnitude (no normalization)")
    print("  ✓ Fixed Y-axis scale (±1% of current price)")
    print("  ✓ Automatic daily history saving")
    print("  ✓ Load single or multi-day history")
    print("  ✓ Export current or all saved history")
    print("  ✓ Auto-start/stop during market hours")
    print("  ✓ Top 5 selection by magnitude")
    print()
    print("Supported symbols:")
    print("  Futures: ES, NQ, GC")
    print("  Index/ETF: SPX, SPY, QQQ")
    print()
    print("History persistence:")
    print(f"  Directory: {SchwabConfig.HISTORY_DIR}")
    print(f"  Tokens:    {os.path.join(SchwabConfig.HISTORY_DIR, 'schwab_tokens.json')}")
    print(f"  Retention: {SchwabConfig.HISTORY_DAYS_TO_KEEP} days")
    print(f"  Auto-save: Every 5 minutes + on stop")
    print()
    print("Auto-start settings:")
    print(f"  Enabled: {SchwabConfig.AUTO_START_ENABLED}")
    print(f"  Market hours: {SchwabConfig.MARKET_START_TIME[0]:02d}:{SchwabConfig.MARKET_START_TIME[1]:02d} - "
          f"{SchwabConfig.MARKET_END_TIME[0]:02d}:{SchwabConfig.MARKET_END_TIME[1]:02d} ET")
    print(f"  Default symbol: {SchwabConfig.AUTO_START_SYMBOL}")
    print(f"  Default interval: {SchwabConfig.AUTO_START_INTERVAL}s")
    print()
    print("Configuration:")
    print("  - Multi-expiration aggregation (up to 10)")
    print("  - Total strikes: 30, 50, 75, 100 (including ATM)")
    print("  - Update intervals: 30 sec, 1 min, 2 min, 5 min")
    print()
    print("Colors: Deep Red (max negative) → Black (zero) → Deep Green (max positive)")
    print()
    
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
