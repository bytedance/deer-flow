#!/usr/bin/env python3
"""Fetch A-share K-line data from akshare for Chan Theory analysis."""
import sys
import os
import pandas as pd
import akshare as ak

PERIODS = {
    "daily": "daily",
    "30": "30",
    "5": "5",
}

def fetch_stock(code, period, output_dir):
    """Download K-line data for a stock code and period."""
    try:
        symbol = code
        if period == "daily":
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
        else:
            df = ak.stock_zh_a_hist_min_em(symbol=symbol, period=period, adjust="qfq")
        
        if df is None or df.empty:
            print(f"Warning: No data for {code} at {period}")
            return None
        
        cols_map = {
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume",
            "时间": "date",
        }
        df = df.rename(columns=cols_map)
        
        needed = ["date", "open", "close", "high", "low"]
        df = df[[c for c in needed if c in df.columns]]
        df = df.sort_values("date").reset_index(drop=True)
        
        out = os.path.join(output_dir, f"{code}_{period}.csv")
        df.to_csv(out, index=False)
        print(f"Saved {len(df)} rows to {out}")
        return df
    except Exception as e:
        print(f"Error fetching {code} {period}: {e}")
        return None

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: fetch_data.py <stock_code> <output_dir>")
        sys.exit(1)
    code = sys.argv[1]
    out_dir = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    for p in ["daily", "30", "5"]:
        fetch_stock(code, p, out_dir)
    print("Done.")