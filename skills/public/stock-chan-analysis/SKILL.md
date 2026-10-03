---
name: stock-chan-analysis
description: >-
  Perform Chan Theory (缠论) multi-timeframe structural analysis on A-share stocks.
  Generates interactive HTML reports with TradingView charts showing Bi (笔), ZhongShu (中枢),
  and 1st/2nd/3rd buy/sell points. Use this skill whenever the user asks about stock
  technical analysis, 缠论, Chan theory, A-share chart analysis, pivot/中枢 analysis, or
  wants to analyze a Chinese stock for buy/sell signals. Also trigger for requests like
  "analyze this stock", "看看这支股票", "缠论分析", "帮我分析股票结构", or when the user
  provides an A-share stock code and wants structural analysis.
---

# Stock Chan Theory Analysis

## Workflow

### Step 1: Get Stock Code
Ask the user for A-share stock code (6-digit, e.g. 000001).

### Step 2: Fetch Market Data
python scripts/fetch_data.py <code> <out_dir>
Produces: daily CSV, 30-min CSV, 5-min CSV.

### Step 3: Run Chan Analysis
python scripts/chan_core.py <csv> <json_out>
Outputs: chart_data, fractals, bi, zhongshu, divergences, points.

### Step 4: Generate HTML Report
python scripts/build_report.py <code> <data_dir> <output_html>

### Step 5: Present Results
Use present_files. User opens HTML in browser.
## Report Features
- Three tabs: Daily / 30min / 5min
- TradingView candlestick chart with zoom/pan
- Bi lines: green=up, red=down
- ZhongShu zones: semi-transparent rectangles
- Buy points (green markers): 1buy / 2buy / 3buy
- Sell points (red markers): 1sell / 2sell / 3sell
- Click marker for detail popup (price, date, rationale)
- Summary panel across all timeframes

## Chan Theory Reference
For algorithm details, read `references/chan_rules.md`.