# Chan Theory (缠论) Reference

## Core Concepts

### 1. K-Line Containment (包含关系)
Two consecutive K-lines where one's range fully contains the other. Direction determined by comparing with the previous processed K-line:
- Upward: if current high > previous high, take max(highs) and max(lows)
- Downward: if current low < previous low, take min(highs) and min(lows)  

### 2. Fractals (分型)
- **Top Fractal**: middle K-line has higher high than both adjacent K-lines
- **Bottom Fractal**: middle K-line has lower low than both adjacent K-lines
- Fractal validity requires non-overlapping time ranges

### 3. Bi (笔) - Stroke
Connects a top fractal to a bottom fractal (or vice versa). Requirements:
- Alternating top/bottom
- At least 5 K-lines between the two fractals
- Price range must not fully contain a sub-segment

### 4. ZhongShu (中枢) - Pivot Center
Formed by 3+ consecutive and overlapping Bi segments. Key parameters:
- **ZG** (中枢高): lowest high among the overlapping Bi
- **ZD** (中枢低): highest low among the overlapping Bi

### 5. Divergence (背驰)
- **Top Divergence**: price makes higher high but MACD histogram is lower (less positive)
- **Bottom Divergence**: price makes lower low but MACD histogram is higher (less negative)

### 6. Buy/Sell Signals (买卖点)

| Signal | Condition |
|--------|-----------|
| 一买 (1st Buy) | Bottom divergence at new low — trend reversal |
| 二买 (2nd Buy) | Pullback to zhongshu after 一买 confirmed |
| 三买 (3rd Buy) | Breakout above zhongshu, pullback stays above ZG |
| 一卖 (1st Sell) | Top divergence at new high — trend reversal |
| 二卖 (2nd Sell) | Rally back to zhongshu after 一卖 confirmed |
| 三卖 (3rd Sell) | Breakdown below zhongshu, rally stays below ZD |

## Multi-Timeframe Analysis
- **Daily**: primary trend direction, major zhongshu
- **30-min**: intermediate structure, secondary zhongshu
- **5-min**: entry/exit precision, minor zhongshu

Signals confirmed across multiple timeframes carry higher weight.
