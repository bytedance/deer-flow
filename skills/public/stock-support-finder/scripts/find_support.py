#!/usr/bin/env python3
"""
Stock Support & Resistance Level Finder
Fetches daily OHLC data, detects swing lows/highs, clusters them into
meaningful support/resistance zones, and outputs a trading report.
"""

import argparse
import sys
from datetime import datetime, timedelta

try:
    import yfinance as yf
    import numpy as np
except ImportError:
    print("Missing dependencies. Run: pip install yfinance numpy")
    sys.exit(1)


def fetch_data(ticker: str, months: int = 6):
    end = datetime.today()
    start = end - timedelta(days=months * 30)
    df = yf.download(ticker, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"),
                     auto_adjust=True, progress=False)
    if df.empty:
        print(f"❌ No data found for '{ticker}'. Check the ticker symbol.")
        sys.exit(1)
    # Flatten MultiIndex columns if present
    if isinstance(df.columns, type(df.columns)) and hasattr(df.columns, 'levels'):
        df.columns = df.columns.get_level_values(0)
    return df


def find_swing_lows(closes, window: int = 5):
    """Local minima: lower than `window` bars on each side."""
    lows = []
    arr = list(closes)
    for i in range(window, len(arr) - window):
        segment = arr[i - window: i + window + 1]
        if arr[i] == min(segment):
            lows.append((i, arr[i]))
    return lows


def find_swing_highs(closes, window: int = 5):
    """Local maxima: higher than `window` bars on each side."""
    highs = []
    arr = list(closes)
    for i in range(window, len(arr) - window):
        segment = arr[i - window: i + window + 1]
        if arr[i] == max(segment):
            highs.append((i, arr[i]))
    return highs


def cluster_levels(points, tolerance_pct: float = 0.015):
    """
    Group price points within `tolerance_pct` of each other into one zone.
    Returns list of (avg_price, touch_count) sorted by touch count desc.
    """
    if not points:
        return []
    prices = sorted([p for _, p in points])
    clusters = []
    current = [prices[0]]
    for p in prices[1:]:
        if (p - current[0]) / current[0] <= tolerance_pct:
            current.append(p)
        else:
            clusters.append(current)
            current = [p]
    clusters.append(current)
    result = [(round(sum(c) / len(c), 2), len(c)) for c in clusters]
    return sorted(result, key=lambda x: x[1], reverse=True)


def compute_rsi(closes, period: int = 14):
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [abs(min(d, 0)) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def compute_ma(closes, period: int):
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 2)


def bar(value, max_val, width=20, char="█"):
    filled = int(round(value / max_val * width)) if max_val > 0 else 0
    return char * filled + "░" * (width - filled)


def main():
    parser = argparse.ArgumentParser(description="Find support/resistance levels for a stock.")
    parser.add_argument("ticker", help="Stock ticker symbol, e.g. MSFT")
    parser.add_argument("--months", type=int, default=6, help="Months of data to analyze (default: 6)")
    parser.add_argument("--window", type=int, default=5, help="Swing detection window in bars (default: 5)")
    parser.add_argument("--tolerance", type=float, default=1.5, help="Cluster tolerance %% (default: 1.5)")
    parser.add_argument("--top", type=int, default=5, help="Number of levels to show (default: 5)")
    args = parser.parse_args()

    ticker = args.ticker.upper()
    print(f"\n{'='*58}")
    print(f"  📊 Support/Resistance Finder — {ticker}")
    print(f"  Data: past {args.months} months  |  {datetime.today().strftime('%Y-%m-%d')}")
    print(f"{'='*58}\n")

    print("⏳ Fetching price data...")
    df = fetch_data(ticker, args.months)
    closes = list(df["Close"].values.flatten())
    highs_raw = list(df["High"].values.flatten())
    lows_raw = list(df["Low"].values.flatten())
    current_price = round(float(closes[-1]), 2)
    total_bars = len(closes)

    print(f"✅ Loaded {total_bars} trading days\n")

    # Technical indicators
    rsi = compute_rsi(closes)
    ma50 = compute_ma(closes, 50)
    ma200 = compute_ma(closes, 200)
    price_vs_ma50 = "上方 ✅" if ma50 and current_price > ma50 else "下方 ❌"
    price_vs_ma200 = "上方 ✅" if ma200 and current_price > ma200 else "下方 ❌"

    # RSI label
    if rsi < 30:
        rsi_label = "超卖 🔵 (潜在买入区)"
    elif rsi < 40:
        rsi_label = "偏弱 (观察)"
    elif rsi < 60:
        rsi_label = "中性"
    elif rsi < 70:
        rsi_label = "偏强 (谨慎追高)"
    else:
        rsi_label = "超买 🔴 (风险高)"

    print("─" * 58)
    print("  当前技术指标")
    print("─" * 58)
    print(f"  当前价格  : ${current_price}")
    print(f"  MA50      : ${ma50 or 'N/A'}  ({price_vs_ma50})")
    print(f"  MA200     : ${ma200 or 'N/A'}  ({price_vs_ma200})")
    print(f"  RSI(14)   : {rsi}  —  {rsi_label}")
    print()

    # Detect swing points — use Low for support, High for resistance (intraday wicks)
    swing_lows = find_swing_lows(lows_raw, args.window)
    swing_highs = find_swing_highs(highs_raw, args.window)
    support_clusters = cluster_levels(swing_lows, args.tolerance / 100)
    resistance_clusters = cluster_levels(swing_highs, args.tolerance / 100)

    # Split strictly below / above current price
    supports = [(p, c) for p, c in support_clusters if p < current_price]
    resistances = [(p, c) for p, c in resistance_clusters if p > current_price]

    max_touches = max([c for _, c in support_clusters + resistance_clusters], default=1)

    print("─" * 58)
    print("  支撑位 (Supports) — 价格下方")
    print("─" * 58)
    if not supports:
        print("  未检测到明显支撑位（可增加数据月份）")
    for rank, (price, touches) in enumerate(supports[:args.top], 1):
        distance = round((current_price - price) / current_price * 100, 1)
        stop = round(price * 0.99, 2)
        strength = "强" if touches >= 3 else "中" if touches == 2 else "弱"
        b = bar(touches, max_touches)
        print(f"  #{rank}  ${price:<8}  触及{touches}次 [{strength}]  {b}")
        print(f"       距当前价 -{distance}%  |  建议止损: ${stop}")
        print()

    print("─" * 58)
    print("  阻力位 (Resistances) — 价格上方")
    print("─" * 58)
    if not resistances:
        print("  未检测到明显阻力位")
    for rank, (price, touches) in enumerate(resistances[:args.top], 1):
        distance = round((price - current_price) / current_price * 100, 1)
        strength = "强" if touches >= 3 else "中" if touches == 2 else "弱"
        b = bar(touches, max_touches)
        print(f"  #{rank}  ${price:<8}  触及{touches}次 [{strength}]  {b}")
        print(f"       距当前价 +{distance}%")
        print()

    # Entry signal summary
    print("─" * 58)
    print("  入场信号检查（规则化模型）")
    print("─" * 58)
    cond_ma = ma50 and current_price > ma50
    cond_rsi = 35 <= rsi <= 65
    all_pass = cond_ma and cond_rsi
    print(f"  价格在 MA50 上方 : {'✅' if cond_ma else '❌'}")
    print(f"  RSI 在 35–65    : {'✅' if cond_rsi else '❌'} (当前 {rsi})")
    print(f"  MACD 金叉       : ⚠️  请在 Moomoo 图表上手动确认")
    print()
    if all_pass:
        # Nearest = closest to current price, not strongest (most-touched)
        nearest_support = min((p for p, _ in supports), key=lambda p: current_price - p, default=None)
        nearest_resistance = min((p for p, _ in resistances), key=lambda p: p - current_price, default=None)
        if nearest_support and nearest_resistance:
            target = nearest_resistance
            stop = round(nearest_support * 0.99, 2)
            risk = round(current_price - stop, 2)
            reward = round(target - current_price, 2)
            rr = round(reward / risk, 1) if risk > 0 else 0
            print(f"  🟡 MA和RSI条件满足，等待 MACD 金叉确认")
            print(f"     参考止损: ${stop}  (最近支撑 ${nearest_support} 下方1%)")
            print(f"     参考目标: ${target}  (最近阻力)")
            print(f"     盈亏比  : {rr}:1  {'✅' if rr >= 2 else '❌ (不足2:1，不入场)'}")
        else:
            print("  🟡 基础条件满足，但找不到足够支撑/阻力参考位")
            nearest_support = None
    else:
        print("  🔴 当前不满足入场条件，继续观察")

    print()
    print("─" * 58)
    print("  ⚠️  免责声明")
    print("─" * 58)
    print("  此工具仅供学习和辅助分析，不构成投资建议。")
    print("  所有交易决策由您自己负责，请结合完整图表判断。")
    print(f"{'='*58}\n")


if __name__ == "__main__":
    main()
