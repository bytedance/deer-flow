#!/usr/bin/env python3
"""
Chan Theory Multi-Timeframe Conjunctive Interpretation
Reads daily, 30min, and 5min analysis JSON files and produces
a structured multi-timeframe conjunctive report.
Usage: python interpret.py <stock_code> <data_dir>
"""

import json, os, sys
from datetime import datetime
from typing import Optional


def load_json(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _item_latest(items: list) -> Optional[dict]:
    return items[-1] if items else None


def _fmt(p, precision=2) -> str:
    if p is None:
        return "N/A"
    return f"{p:.{precision}f}"


class Interpreter:
    def __init__(self, label: str, data: dict):
        self.label = label
        self.klines = data.get("klines", [])
        self.bi = data.get("bi", [])
        self.zhongshu = data.get("zhongshu", [])
        self.signals = data.get("signals", {})
        self.divergences = data.get("divergences", [])

    @property
    def cp(self) -> Optional[float]:
        return self.klines[-1].get("close") if self.klines else None

    @property
    def trend(self) -> str:
        if not self.bi:
            return "UNKNOWN"
        return "UP" if self.bi[-1].get("direction") == "up" else "DOWN"

    @property
    def zs(self) -> Optional[dict]:
        return _item_latest(self.zhongshu)

    @property
    def zs_pos(self) -> str:
        zs = self.zs
        cp = self.cp
        if not zs or cp is None:
            return "N/A"
        zg, zd = zs.get("zg"), zs.get("zd")
        if zg is None or zd is None:
            return "unknown bounds"
        if cp > zg:
            ratio = (cp - zg) / zg * 100
            return f"above ZG ({_fmt(zg)}, +{_fmt(ratio)}pct)"
        elif cp < zd:
            ratio = (zd - cp) / zd * 100
            return f"below ZD ({_fmt(zd)}, -{_fmt(ratio)}pct)"
        return f"inside [{_fmt(zd)}, {_fmt(zg)}]"

    def sig(self, prefix: str) -> Optional[dict]:
        return _item_latest(self.signals.get(prefix, []))

    def summary(self) -> str:
        lines = [f"{self.label}: trend={self.trend}, price={_fmt(self.cp)}"]
        zs = self.zs
        if zs:
            lines.append(
                f"  Zhongshu: ZD={_fmt(zs.get('zd'))} ZG={_fmt(zs.get('zg'))} "
                f"({zs.get('start_date','?')} -> {zs.get('end_date','?')})"
            )
            lines.append(f"  Position: {self.zs_pos}")
        for p in ["buy1","buy2","buy3","sell1","sell2","sell3"]:
            s = self.sig(p)
            if s:
                lines.append(f"  Latest {p}: {s.get('date','?')} @ {_fmt(s.get('price'))}")
        return "\n".join(lines)


class Report:
    def __init__(self, code, d: Interpreter, m: Interpreter, s: Interpreter):
        self.code = code
        self.d = d
        self.m = m
        self.s = s

    def _trend_align(self) -> str:
        t = [self.d.trend, self.m.trend, self.s.trend]
        if all(x == "UP" for x in t):
            return "All three timeframes UP -- strong bullish consensus."
        elif all(x == "DOWN" for x in t):
            return "All three DOWN -- avoid longs."
        elif t[0] == "UP" and t[1] == "UP" and t[2] == "DOWN":
            return "Daily + 30min UP, 5min DOWN -- normal pullback within uptrend."
        elif t[0] == "DOWN" and t[1] == "DOWN" and t[2] == "UP":
            return "Daily + 30min DOWN, 5min UP -- bear-market bounce, do not chase."
        return f"Mixed: daily={t[0]}, 30min={t[1]}, 5min={t[2]}."

    def _zs_nest(self) -> str:
        mz, sz = self.m.zs, self.s.zs
        if not mz or not sz:
            return "Missing zhongshu data."
        mzg, mzd = mz.get("zg"), mz.get("zd")
        szg, szd = sz.get("zg"), sz.get("zd")
        if any(v is None for v in [mzg, mzd, szg, szd]):
            return "Incomplete zhongshu bounds."
        if szd > mzg:
            ratio = (szd - mzg) / mzg * 100
            return (
                f"5min zhongshu [{_fmt(szd)},{_fmt(szg)}] entirely ABOVE "
                f"30min zhongshu [{_fmt(mzd)},{_fmt(mzg)}] (+{_fmt(ratio)}pct). "
                f"Strong bullish nesting."
            )
        if szg < mzd:
            ratio = (mzd - szg) / mzg * 100
            return (
                f"5min zhongshu entirely BELOW 30min (-{_fmt(ratio)}pct). "
                f"Structure weakening."
            )
        if szd >= mzd and szg <= mzg:
            return (
                f"5min zhongshu nested INSIDE 30min zhongshu. "
                f"Classic consolidation pattern."
            )
        if szd < mzg and szg > mzg:
            return f"5min zhongshu straddles 30min ZG. Transition zone."
        return "Complex nesting -- monitor closely."

    def _buy3_resonance(self) -> str:
        b3 = self.m.sig("buy3")
        dz = self.d.zs
        if not b3 or not dz:
            return ""
        zg = dz.get("zg")
        if zg and b3.get("price", 0) > zg:
            ratio = (b3["price"] - zg) / zg * 100
            return (
                f"\n\nBUY3 RESONANCE: 30min buy3 at {_fmt(b3['price'])} "
                f"({b3.get('date','?')}) is {_fmt(ratio)}pct above daily ZG={_fmt(zg)}. "
                f"Minor-level buy3 above major-level zhongshu -- strong confirmation."
            )
        return ""

    def _signals_table(self) -> str:
        rows = []
        labels = [
            ("buy1","Buy L1"),("buy2","Buy L2"),("buy3","Buy L3"),
            ("sell1","Sell L1"),("sell2","Sell L2"),("sell3","Sell L3"),
        ]
        for prefix, label in labels:
            d_s = self.d.sig(prefix)
            m_s = self.m.sig(prefix)
            s_s = self.s.sig(prefix)
            d_t = f"{_fmt(d_s.get('price'))} ({str(d_s.get('date',''))[:10]})" if d_s else "-"
            m_t = f"{_fmt(m_s.get('price'))} ({str(m_s.get('date',''))[:10]})" if m_s else "-"
            s_t = f"{_fmt(s_s.get('price'))} ({str(s_s.get('date',''))[:10]})" if s_s else "-"
            rows.append(f"| {label} | {d_t} | {m_t} | {s_t} |")
        return "\n".join(rows)

    def _tactical(self) -> str:
        s_zs, m_zs = self.s.zs, self.m.zs
        cp = self.d.cp
        lines = ["### Tactical Reference", ""]
        lines.append("**Key Levels:**")
        if s_zs:
            lines.append(f"- 5min ZG (short resistance): {_fmt(s_zs.get('zg'))}")
            lines.append(f"- 5min ZD (short support): {_fmt(s_zs.get('zd'))}")
        if m_zs:
            lines.append(f"- 30min ZG (mid defense): {_fmt(m_zs.get('zg'))}")
            lines.append(f"- 30min ZD (hard stop): {_fmt(m_zs.get('zd'))}")
        lines.append(f"\nCurrent price: {_fmt(cp)}")

        if self.d.trend == "UP" and self.m.trend == "UP":
            lines.append("\n**Bullish framework:**")
            if s_zs:
                lines.append(f"- Entry zone: near 5min ZD ({_fmt(s_zs.get('zd'))})")
                lines.append(
                    f"- Add signal: break above 5min ZG ({_fmt(s_zs.get('zg'))}) with volume"
                )
            if m_zs:
                lines.append(f"- Stop: below 30min ZD ({_fmt(m_zs.get('zd'))})")
        elif self.d.trend == "DOWN":
            lines.append("\n**Bearish -- stay defensive:**")
            lines.append("- Wait for daily UP before new longs.")
            lines.append("- Use 30min sell signals for exits.")
        return "\n".join(lines)

    def generate(self) -> str:
        cp = self.d.cp
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"""## {self.code} Multi-Timeframe Chan Theory Analysis

> {now} | Price: {_fmt(cp)}

### 1. Structure Overview

{self.d.summary()}

{self.m.summary()}

{self.s.summary()}

### 2. Trend Alignment

{self._trend_align()}

### 3. Zhongshu Resonance

{self._zs_nest()}{self._buy3_resonance()}

### 4. Signal Matrix

| Signal | Daily | 30min | 5min |
|--------|-------|-------|------|
{self._signals_table()}

{self._tactical()}

---
*Generated by interpret.py -- Chan Theory multi-timeframe conjunctive analysis.*
"""


def main():
    if len(sys.argv) < 3:
        print("Usage: python interpret.py <stock_code> <data_dir>", file=sys.stderr)
        sys.exit(1)
    code = sys.argv[1]
    ddir = sys.argv[2]
    daily = Interpreter("Daily", load_json(os.path.join(ddir, f"{code}_daily.json")))
    min30 = Interpreter("30min", load_json(os.path.join(ddir, f"{code}_30min.json")))
    min5  = Interpreter("5min", load_json(os.path.join(ddir, f"{code}_5min.json")))
    print(Report(code, daily, min30, min5).generate())


if __name__ == "__main__":
    main()
