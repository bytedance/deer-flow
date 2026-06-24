#!/usr/bin/env python3
"""
Phase 3: AI-Driven Stock Analysis
Fetches recent news for a ticker, uses Claude to analyze sentiment,
then combines with technical signals for a final trading verdict.
"""

import argparse
import os
import sys
import json
from datetime import datetime

try:
    import yfinance as yf
except ImportError:
    print("Missing dependency. Run: pip3 install yfinance")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("Missing dependency. Run: pip3 install anthropic")
    sys.exit(1)

# Reuse technical analysis from find_support.py
sys.path.insert(0, os.path.dirname(__file__))
from find_support import fetch_data, find_swing_lows, cluster_levels, compute_rsi, compute_ma


def fetch_news(ticker: str, max_items: int = 8) -> list[dict]:
    stock = yf.Ticker(ticker)
    news = stock.news or []
    results = []
    for item in news[:max_items]:
        content = item.get("content", {})
        title = content.get("title") or item.get("title", "")
        summary = content.get("summary") or ""
        provider = content.get("provider", {}).get("displayName", "") or item.get("publisher", "")
        pub_date = content.get("pubDate", "") or ""
        if title:
            results.append({
                "title": title,
                "summary": summary[:300] if summary else "",
                "source": provider,
                "date": pub_date[:10] if pub_date else "",
            })
    return results


def analyze_with_claude(ticker: str, news_items: list[dict], current_price: float,
                         ma50: float, rsi: float) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set"}

    client = anthropic.Anthropic(api_key=api_key)

    news_text = ""
    for i, item in enumerate(news_items, 1):
        news_text += f"{i}. [{item['date']}] {item['title']}"
        if item["summary"]:
            news_text += f"\n   {item['summary']}"
        news_text += f"\n   来源: {item['source']}\n\n"

    if not news_text:
        news_text = "暂无最新新闻。"

    prompt = f"""你是一位专业的美股交易分析师。请分析以下信息并给出结构化评估。

股票代码: {ticker}
当前价格: ${current_price}
MA50: ${ma50 if ma50 else 'N/A'}
RSI(14): {rsi}
价格相对MA50: {'上方' if ma50 and current_price > ma50 else '下方'}

最新新闻:
{news_text}

请严格按以下 JSON 格式回复，不要有任何其他文字：
{{
  "sentiment": "bullish" 或 "neutral" 或 "bearish",
  "sentiment_cn": "看涨" 或 "中性" 或 "看跌",
  "confidence": 1到5的整数（5最高）,
  "key_factors": ["因素1", "因素2", "因素3"],
  "risk_factors": ["风险1", "风险2"],
  "summary": "一句话综合评估（中文，30字以内）",
  "action": "可考虑入场" 或 "继续观察" 或 "避免入场"
}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    # Extract JSON if wrapped in markdown
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def signal_bar(value: int, max_val: int = 5, width: int = 10) -> str:
    filled = round(value / max_val * width)
    return "█" * filled + "░" * (width - filled)


def main():
    parser = argparse.ArgumentParser(description="AI-powered stock analysis with news sentiment.")
    parser.add_argument("ticker", help="Stock ticker, e.g. MSFT")
    parser.add_argument("--months", type=int, default=6)
    args = parser.parse_args()

    ticker = args.ticker.upper()

    print(f"\n{'='*58}")
    print(f"  🤖 AI 综合分析报告 — {ticker}")
    print(f"  {datetime.today().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*58}\n")

    # --- Technical Analysis ---
    print("⏳ 获取价格数据...")
    df = fetch_data(ticker, args.months)
    closes = list(df["Close"].values.flatten())
    current_price = round(float(closes[-1]), 2)
    rsi = compute_rsi(closes)
    ma50 = compute_ma(closes, 50)

    lows_raw  = list(df["Low"].values.flatten())
    swing_lows = find_swing_lows(lows_raw)
    supports_below = [(p, c) for p, c in cluster_levels(swing_lows) if p < current_price]
    nearest_support = min((p for p, _ in supports_below), key=lambda p: current_price - p, default=None) if supports_below else None

    cond_ma = bool(ma50 and current_price > ma50)
    cond_rsi = 35 <= rsi <= 65
    tech_score = sum([cond_ma, cond_rsi])

    print("─" * 58)
    print("  📊 技术指标")
    print("─" * 58)
    print(f"  当前价格 : ${current_price}")
    print(f"  MA50     : ${ma50 or 'N/A'}  ({'上方 ✅' if cond_ma else '下方 ❌'})")
    print(f"  RSI(14)  : {rsi}  ({'✅ 35–65区间' if cond_rsi else '❌ 区间外'})")
    if nearest_support:
        stop = round(nearest_support * 0.99, 2)
        print(f"  最近支撑 : ${nearest_support}  →  建议止损 ${stop}")
    print()

    # --- News Fetch ---
    print("⏳ 抓取最新新闻...")
    news = fetch_news(ticker)
    print(f"✅ 找到 {len(news)} 条新闻\n")

    if news:
        print("─" * 58)
        print("  📰 最新新闻标题")
        print("─" * 58)
        for i, item in enumerate(news[:5], 1):
            print(f"  {i}. {item['title'][:60]}")
            if item["date"]:
                print(f"     {item['date']}  {item['source']}")
        print()

    # --- AI Analysis ---
    print("⏳ Claude 分析情绪中...")
    result = analyze_with_claude(ticker, news, current_price, ma50, rsi)

    if "error" in result:
        print(f"❌ AI 分析失败: {result['error']}")
        return

    print("─" * 58)
    print("  🧠 Claude AI 情绪分析")
    print("─" * 58)

    sentiment_icon = {"bullish": "🟢", "neutral": "🟡", "bearish": "🔴"}.get(result["sentiment"], "⚪")
    print(f"  情绪判断  : {sentiment_icon} {result['sentiment_cn']}（{result['sentiment']}）")
    print(f"  信心指数  : {signal_bar(result['confidence'])}  {result['confidence']}/5")
    print(f"  综合评估  : {result['summary']}")
    print()

    print("  利好因素:")
    for f in result.get("key_factors", []):
        print(f"    ✅ {f}")
    print()
    print("  风险因素:")
    for r in result.get("risk_factors", []):
        print(f"    ⚠️  {r}")
    print()

    # --- Combined Verdict ---
    print("─" * 58)
    print("  🎯 综合交易建议")
    print("─" * 58)

    ai_bullish = result["sentiment"] == "bullish"
    ai_action = result["action"]
    all_green = cond_ma and cond_rsi and ai_bullish

    print(f"  技术条件  : {'✅ 满足' if tech_score == 2 else '⚠️ 部分满足' if tech_score == 1 else '❌ 不满足'} ({tech_score}/2)")
    print(f"  MACD金叉  : ⚠️  请在 Moomoo 手动确认")
    print(f"  AI情绪    : {sentiment_icon} {result['sentiment_cn']}")
    print()

    if all_green:
        print(f"  → 🟢 {ai_action}")
        print(f"     技术 + AI 双重确认，等待 Moomoo 确认 MACD 金叉后可考虑入场")
        if nearest_support:
            stop = round(nearest_support * 0.99, 2)
            risk = round(current_price - stop, 2)
            target = round(current_price + risk * 2, 2)
            print(f"     止损参考: ${stop}  目标参考: ${target}  (2:1)")
    elif cond_ma and cond_rsi and not ai_bullish:
        print(f"  → 🟡 技术条件满足，但 AI 情绪{result['sentiment_cn']}，建议观望")
    else:
        print(f"  → 🔴 {ai_action}，当前不满足入场标准")

    print()
    print("─" * 58)
    print("  ⚠️  仅供学习参考，不构成投资建议")
    print(f"{'='*58}\n")


if __name__ == "__main__":
    main()
