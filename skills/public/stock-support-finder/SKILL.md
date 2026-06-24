---
name: stock-support-finder
description: Use this skill when the user provides a US stock ticker and wants to find support and resistance levels, check entry conditions (MA, RSI), and get a suggested stop-loss and risk/reward ratio. Outputs a structured trading report based on the last 6 months of daily price data.
---

# Stock Support & Resistance Finder

## Overview

This skill analyzes a stock's price history to identify support and resistance levels using swing-point detection and price clustering. It also checks entry conditions (MA50, RSI) and suggests stop-loss levels based on the nearest support.

## Core Capabilities

- Detect swing lows (support) and swing highs (resistance) from daily OHLC data
- Cluster nearby price levels into meaningful zones with touch counts
- Compute MA50, MA200, and RSI(14)
- Check the three entry conditions from the rules-based model
- Suggest stop-loss (support × 0.99) and check risk/reward ratio

## Usage

```bash
python /mnt/skills/public/stock-support-finder/scripts/find_support.py MSFT
```

With options:
```bash
python /mnt/skills/public/stock-support-finder/scripts/find_support.py MSFT \
  --months 6 \
  --window 5 \
  --tolerance 1.5 \
  --top 5
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ticker` | required | US stock ticker (e.g. MSFT, AAPL, NVDA) |
| `--months` | 6 | Months of historical data to fetch |
| `--window` | 5 | Bars on each side for swing detection |
| `--tolerance` | 1.5 | % tolerance for clustering nearby levels |
| `--top` | 5 | Number of levels to display |

## Dependencies

```
yfinance
numpy
```

Install with:
```bash
pip install yfinance numpy
```

## Workflow

### Step 1: Run the script

When the user provides a ticker, run:

```bash
python /mnt/skills/public/stock-support-finder/scripts/find_support.py {TICKER}
```

### Step 2: Present the results

Report back:
1. Current price, MA50, MA200, RSI
2. Top support levels (price, touch count, strength, suggested stop-loss)
3. Top resistance levels (price, touch count, potential target)
4. Entry signal check (MA ✅/❌, RSI ✅/❌, MACD reminder)
5. If conditions are met: suggested stop, target, and R:R ratio

### Step 3: Remind the user

Always remind the user to:
- Confirm the MACD golden cross visually in Moomoo (the script cannot auto-detect it)
- Use the position size formula: shares = (portfolio × 2%) ÷ (entry − stop)
- Apply the 25% single-stock cap rule
