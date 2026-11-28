#!/usr/bin/env python3
"""Chan Theory core analysis: containment, fractals, bi, zhongshu, divergences, points."""
import sys, os, json, math
import pandas as pd
import numpy as np

def load_csv(path):
    df = pd.read_csv(path)
    df["date"] = df["date"].astype(str)
    for c in ["open", "close", "high", "low"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "close", "high", "low"])
    return df.reset_index(drop=True)

# ---- Step 1: Containment processing ----
def process_containment(klines):
    """Merge contained K-lines per Chan Theory rules."""
    if len(klines) < 2:
        return klines
    result = [klines[0]]
    direction = None  # previous non-contained direction: up/down
    for i in range(1, len(klines)):
        prev = result[-1]
        cur = klines[i]
        if direction is None:
            result.append(cur)
            if cur["close"] != prev["close"]:
                direction = "up" if cur["close"] > prev["close"] else "down"
            continue
        # check containment
        contained = False
        if direction == "up":
            if cur["high"] <= prev["high"] and cur["low"] >= prev["low"]:
                contained = True
                # merge: take higher high and higher low
                merged = dict(prev)
                merged["high"] = max(prev["high"], cur["high"])
                merged["low"] = max(prev["low"], cur["low"])
                result[-1] = merged
        else:  # direction == down
            if cur["high"] <= prev["high"] and cur["low"] >= prev["low"]:
                contained = True
                merged = dict(prev)
                merged["high"] = min(prev["high"], cur["high"])
                merged["low"] = min(prev["low"], cur["low"])
                result[-1] = merged
        if not contained:
            result.append(cur)
            if cur["close"] != prev["close"]:
                direction = "up" if cur["close"] > prev["close"] else "down"
    return result

def merge_klines(klines):
    """Wrapper: apply containment merging then return merged klines."""
    return process_containment(klines)
# ---- Step 2: Fractal detection ----
def find_fractals(klines):
    """Find top and bottom fractals."""
    n = len(klines)
    tops, bottoms = [], []
    for i in range(1, n - 1):
        l, m, r = klines[i-1], klines[i], klines[i+1]
        if l["high"] < m["high"] and r["high"] < m["high"]:
            tops.append({"idx": i, "date": m["date"], "price": m["high"]})
        if l["low"] > m["low"] and r["low"] > m["low"]:
            bottoms.append({"idx": i, "date": m["date"], "price": m["low"]})
    return tops, bottoms

# ---- Step 3: Bi segment detection ----
def find_bi(klines, tops, bottoms):
    """Connect consecutive top-bottom pairs into Bi segments."""
    # merge sorted fractals
    all_fractals = []
    for t in tops:
        all_fractals.append({**t, "type": "top"})
    for b in bottoms:
        all_fractals.append({**b, "type": "bottom"})
    all_fractals.sort(key=lambda x: x["idx"])
    
    # find valid bi: at least 5 klines between two opposite fractals
    bi_list = []
    i = 0
    while i < len(all_fractals) - 1:
        a = all_fractals[i]
        b = all_fractals[i+1]
        if a["type"] != b["type"] and (b["idx"] - a["idx"]) >= 4:
            direction = "up" if a["type"] == "bottom" else "down"
            bi_list.append({
                "start_idx": a["idx"], "end_idx": b["idx"],
                "start_date": a["date"], "end_date": b["date"],
                "start_price": a["price"], "end_price": b["price"],
                "direction": direction,
            })
            i += 1
        i += 1
    return bi_list# ---- Step 4: ZhongShu detection ----
def find_zhongshu(klines, bi_list):
    """Find ZhongShu from overlapping adjacent Bi segments."""
    zhongshu_list = []
    i = 0
    while i < len(bi_list) - 2:
        b1 = bi_list[i]
        b2 = bi_list[i+1]
        b3 = bi_list[i+2]
        r1_low = min(b1["start_price"], b1["end_price"])
        r1_high = max(b1["start_price"], b1["end_price"])
        r2_low = min(b2["start_price"], b2["end_price"])
        r2_high = max(b2["start_price"], b2["end_price"])
        r3_low = min(b3["start_price"], b3["end_price"])
        r3_high = max(b3["start_price"], b3["end_price"])
        
        overlap_low = max(r1_low, r2_low, r3_low)
        overlap_high = min(r1_high, r2_high, r3_high)
        if overlap_low < overlap_high:
            zhongshu_list.append({
                "start_date": min(b1["start_date"], b2["start_date"], b3["start_date"]),
                "end_date": max(b1["end_date"], b2["end_date"], b3["end_date"]),
                "zg": overlap_high,
                "zd": overlap_low,
                "bi_start": b1["start_idx"],
                "bi_end": b3["end_idx"],
            })
            i += 1
        i += 1
    return zhongshu_list

# ---- Step 5: MACD divergence ----
def calc_macd(klines, fast=12, slow=26, signal=9):
    """Calculate MACD and detect divergences."""
    closes = np.array([k["close"] for k in klines])
    ema_fast = pd.Series(closes).ewm(span=fast, adjust=False).mean().values
    ema_slow = pd.Series(closes).ewm(span=slow, adjust=False).mean().values
    dif = ema_fast - ema_slow
    dea = pd.Series(dif).ewm(span=signal, adjust=False).mean().values
    macd_hist = 2 * (dif - dea)
    return {"dif": dif.tolist(), "dea": dea.tolist(), "hist": macd_hist.tolist()}

def find_divergences(klines, tops, bottoms):
    """Detect top/bottom divergences using MACD histogram."""
    macd = calc_macd(klines)
    divergences = []
    hist = macd["hist"]
    
    # top divergence: price higher high, hist lower high (less absolute)
    for i in range(1, len(tops)):
        f1, f2 = tops[i-1], tops[i]
        if f2["price"] > f1["price"] and abs(hist[f2["idx"]]) < abs(hist[f1["idx"]]):
            divergences.append({"type": "top_div", "idx": f2["idx"], "date": f2["date"]})
    
    # bottom divergence: price lower low, hist less negative
    for i in range(1, len(bottoms)):
        f1, f2 = bottoms[i-1], bottoms[i]
        if f2["price"] < f1["price"] and hist[f2["idx"]] > hist[f1["idx"]]:
            divergences.append({"type": "bottom_div", "idx": f2["idx"], "date": f2["date"]})
    return divergences

# ---- Step 6: Buy/Sell signals (一买/二买/三买 & 一卖/二卖/三卖) ----
def find_chan_signals(klines, bi_list, zhongshu_list, tops, bottoms, divergences):
    """
    Detect Chan-Theory buy/sell points:
    
    Buy signals:
      - 一买 (1st Buy): bottom divergence at a new low, trend reverse signal
      - 二买 (2nd Buy): pullback to zhongshu without breaking lower, after 一买 confirmed
      - 三买 (3rd Buy): breakout above zhongshu then pullback NOT falling back into zhongshu
    
    Sell signals:
      - 一卖 (1st Sell): top divergence at a new high
      - 二卖 (2nd Sell): rally back to zhongshu after 一卖
      - 三卖 (3rd Sell): breakdown below zhongshu then rally NOT re-entering zhongshu
    """
    signals = {"buy1": [], "buy2": [], "buy3": [], "sell1": [], "sell2": [], "sell3": []}
    
    # 一买: bottom divergence points
    for d in divergences:
        if d["type"] == "bottom_div":
            signals["buy1"].append({
                "idx": d["idx"], "date": d["date"],
                "label": "一买",
                "type": "buy",
                "price": klines[d["idx"]]["low"],
            })
    
    # 一卖: top divergence points
    for d in divergences:
        if d["type"] == "top_div":
            signals["sell1"].append({
                "idx": d["idx"], "date": d["date"],
                "label": "一卖",
                "type": "sell",
                "price": klines[d["idx"]]["high"],
            })
    
    if not zhongshu_list:
        return signals
    
    # 二买: after a 一买, price pulls back to zhongshu area (near zg/zd)
    for buy1 in signals["buy1"]:
        b1_idx = buy1["idx"]
        for zs in zhongshu_list:
            if zs["bi_start"] <= b1_idx <= zs["bi_end"]:
                zg, zd = zs["zg"], zs["zd"]
                break
        else:
            continue
        # look after 一买 for a pullback that touches zhongshu range
        for i in range(b1_idx + 3, len(klines)):
            low = klines[i]["low"]
            if low <= zg:
                # check this is a local bottom (fractal)
                for b in bottoms:
                    if b["idx"] == i:
                        signals["buy2"].append({
                            "idx": i, "date": klines[i]["date"],
                            "label": "二买",
                            "type": "buy",
                            "price": low,
                            "related_zs": {"zg": zg, "zd": zd},
                        })
                        break
                break
    
    # 二卖: after 一卖, price rallies back to zhongshu area
    for sell1 in signals["sell1"]:
        s1_idx = sell1["idx"]
        for zs in zhongshu_list:
            if zs["bi_start"] <= s1_idx <= zs["bi_end"]:
                zg, zd = zs["zg"], zs["zd"]
                break
        else:
            continue
        for i in range(s1_idx + 3, len(klines)):
            high = klines[i]["high"]
            if high >= zd:
                for t in tops:
                    if t["idx"] == i:
                        signals["sell2"].append({
                            "idx": i, "date": klines[i]["date"],
                            "label": "二卖",
                            "type": "sell",
                            "price": high,
                            "related_zs": {"zg": zg, "zd": zd},
                        })
                        break
                break
    
    # 三买: breakout above zhongshu then pullback stays above zg (third-type buy)
    for zs in zhongshu_list:
        zg, zd = zs["zg"], zs["zd"]
        zs_end = zs["bi_end"]
        # find breakout: price goes above zg after zhongshu ends
        breakout_idx = None
        for i in range(zs_end, len(klines)):
            if klines[i]["close"] > zg:
                breakout_idx = i
                break
        if breakout_idx is None:
            continue
        # find pullback that hits near zg but doesn't close below
        for i in range(breakout_idx + 2, len(klines)):
            low = klines[i]["low"]
            if low <= zg * 1.005 and low >= zg * 0.985:
                for b in bottoms:
                    if b["idx"] == i:
                        signals["buy3"].append({
                            "idx": i, "date": klines[i]["date"],
                            "label": "三买",
                            "type": "buy",
                            "price": low,
                            "related_zs": {"zg": zg, "zd": zd},
                        })
                        break
                break
    
    # 三卖: breakdown below zhongshu then rally doesn't re-enter
    for zs in zhongshu_list:
        zg, zd = zs["zg"], zs["zd"]
        zs_end = zs["bi_end"]
        breakdown_idx = None
        for i in range(zs_end, len(klines)):
            if klines[i]["close"] < zd:
                breakdown_idx = i
                break
        if breakdown_idx is None:
            continue
        for i in range(breakdown_idx + 2, len(klines)):
            high = klines[i]["high"]
            if high >= zd * 0.995 and high <= zd * 1.015:
                for t in tops:
                    if t["idx"] == i:
                        signals["sell3"].append({
                            "idx": i, "date": klines[i]["date"],
                            "label": "三卖",
                            "type": "sell",
                            "price": high,
                            "related_zs": {"zg": zg, "zd": zd},
                        })
                        break
                break
    
    return signals

# ---- Main pipeline ----
def analyze_klines(klines):
    """
    Full Chan-Theory analysis pipeline.
    Returns a dict with all results ready for chart rendering.
    """
    klines = merge_klines(klines)
    tops, bottoms = find_fractals(klines)
    bi_list = find_bi(klines, tops, bottoms)
    zhongshu_list = find_zhongshu(klines, bi_list)
    divs = find_divergences(klines, tops, bottoms)
    signals = find_chan_signals(klines, bi_list, zhongshu_list, tops, bottoms, divs)
    
    return {
        "klines": klines,
        "fractals": {"tops": tops, "bottoms": bottoms},
        "bi": bi_list,
        "zhongshu": zhongshu_list,
        "divergences": divs,
        "signals": signals,
    }

def export_to_json(result, output_path):
    """Serialize analysis result to JSON for frontend consumption."""
    import json
    def default_serializer(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        raise TypeError(f"Object of type {type(obj)} not serializable")
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=default_serializer)

# ---- CLI ----
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: chan_core.py <input_csv> <output_json> [period_name]", file=sys.stderr)
        sys.exit(1)
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    period = sys.argv[3] if len(sys.argv) > 3 else "unknown"
    
    df = load_csv(input_path)
    klines = df.to_dict(orient="records")
    for k in klines:
        k["period"] = period
    
    result = analyze_klines(klines)
    export_to_json(result, output_path)
    print(f"Analysis complete: {len(result['klines'])} klines, {len(result['bi'])} bi, {len(result['zhongshu'])} zhongshu, signals={dict((k,len(v)) for k,v in result['signals'].items())}")
