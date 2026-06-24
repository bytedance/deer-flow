#!/usr/bin/env python3
"""
Daily Stock Report — reads watchlist.txt, runs AI analysis for each stock,
generates a PDF report, sends macOS notification, and emails the PDF.
"""

import os
import sys
import smtplib
import subprocess
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from io import StringIO

# ── Path setup ──────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR  = os.path.dirname(SCRIPT_DIR)
WATCHLIST  = os.path.join(SKILL_DIR, "watchlist.txt")
REPORT_DIR = os.path.join(SKILL_DIR, "reports")
os.makedirs(REPORT_DIR, exist_ok=True)
sys.path.insert(0, SCRIPT_DIR)

try:
    from fpdf import FPDF
except ImportError:
    print("Missing dependency. Run: pip3 install fpdf2")
    sys.exit(1)

try:
    import yfinance as yf
    import anthropic
except ImportError:
    print("Missing dependency. Run: pip3 install yfinance anthropic")
    sys.exit(1)

from find_support import fetch_data, find_swing_lows, cluster_levels, compute_rsi, compute_ma
from ai_analysis  import fetch_news, analyze_with_claude

# ── Config (from environment variables) ─────────────────────────────────────
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
GMAIL_USER     = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_TO       = ["liangce364@gmail.com", "charlesliang07@outlook.com"]


# ── Load watchlist ───────────────────────────────────────────────────────────
def load_watchlist() -> list[str]:
    if not os.path.exists(WATCHLIST):
        print(f"Watchlist not found: {WATCHLIST}")
        sys.exit(1)
    with open(WATCHLIST) as f:
        return [line.strip().upper() for line in f if line.strip() and not line.startswith("#")]


# ── Analyse one stock ────────────────────────────────────────────────────────
def analyse_stock(ticker: str) -> dict:
    print(f"  Analysing {ticker}...")
    try:
        df = fetch_data(ticker, months=6)
        closes = list(df["Close"].values.flatten())
        price  = round(float(closes[-1]), 2)
        rsi    = compute_rsi(closes)
        ma50   = compute_ma(closes, 50)

        lows_raw  = list(df["Low"].values.flatten())
        lows      = find_swing_lows(lows_raw)
        supports  = [(p, c) for p, c in cluster_levels(lows) if p < price]
        nearest   = min((p for p, _ in supports), key=lambda p: price - p, default=None) if supports else None
        stop      = round(nearest * 0.99, 2) if nearest else None

        news   = fetch_news(ticker, max_items=8)
        ai     = analyze_with_claude(ticker, news, price, ma50, rsi)

        cond_ma  = bool(ma50 and price > ma50)
        cond_rsi = 35 <= rsi <= 65
        return {
            "ticker": ticker,
            "price":  price,
            "ma50":   ma50,
            "rsi":    rsi,
            "nearest_support": nearest,
            "stop":   stop,
            "cond_ma":  cond_ma,
            "cond_rsi": cond_rsi,
            "news_count": len(news),
            "ai": ai,
            "error": None,
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


# ── Build PDF ────────────────────────────────────────────────────────────────
class PDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(30, 58, 95)
        self.cell(0, 10, "Daily Stock Report", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 6, datetime.now().strftime("%Y-%m-%d  |  Generated at 9:00 AM AEST"),
                  align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)
        self.set_draw_color(200, 210, 220)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(160, 160, 160)
        self.cell(0, 6, "For educational purposes only. Not financial advice.", align="C")


def sentiment_label(s: str) -> str:
    return {"bullish": "BULLISH", "neutral": "NEUTRAL", "bearish": "BEARISH"}.get(s, s.upper())


def build_pdf(results: list[dict], path: str):
    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Summary table
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(30, 58, 95)
    pdf.cell(0, 7, "Portfolio Overview", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    col = [22, 24, 24, 24, 28, 36, 38]
    headers = ["Ticker", "Price", "MA50", "RSI", "Support", "Stop Loss", "AI Signal"]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(30, 58, 95)
    pdf.set_text_color(255, 255, 255)
    for w, h in zip(col, headers):
        pdf.cell(w, 7, h, border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for r in results:
        pdf.set_text_color(30, 30, 30)
        if r.get("error"):
            pdf.set_fill_color(255, 240, 240)
            vals = [r["ticker"], "ERROR", "-", "-", "-", "-", r["error"][:30]]
            fill = True
        else:
            ai = r.get("ai", {})
            sent = ai.get("sentiment", "neutral")
            fill_colors = {"bullish": (220, 252, 231), "neutral": (254, 249, 195), "bearish": (254, 226, 226)}
            pdf.set_fill_color(*fill_colors.get(sent, (245, 245, 245)))
            vals = [
                r["ticker"],
                f"${r['price']}",
                f"${r['ma50']}" if r["ma50"] else "N/A",
                str(r["rsi"]),
                f"${r['nearest_support']}" if r["nearest_support"] else "N/A",
                f"${r['stop']}" if r["stop"] else "N/A",
                sentiment_label(sent),
            ]
            fill = True
        for w, v in zip(col, vals):
            pdf.cell(w, 7, str(v), border=1, fill=fill, align="C")
        pdf.ln()

    pdf.ln(6)

    # Detail section per stock
    for r in results:
        if r.get("error"):
            continue
        ai = r.get("ai", {})
        sent = ai.get("sentiment", "neutral")
        conf = ai.get("confidence", 0)

        # Stock header
        pdf.set_fill_color(30, 58, 95)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 8, f"  {r['ticker']}   ${r['price']}   {sentiment_label(sent)}  (Confidence: {conf}/5)",
                 fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(30, 30, 30)
        pdf.ln(2)

        # Technical
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, "Technical Indicators", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8.5)
        pdf.cell(95, 6, f"  MA50: ${r['ma50']}  ({'Above' if r['cond_ma'] else 'Below'} - {'OK' if r['cond_ma'] else 'FAIL'})")
        pdf.cell(0,  6, f"RSI(14): {r['rsi']}  ({'In range' if r['cond_rsi'] else 'Out of range'})",
                 new_x="LMARGIN", new_y="NEXT")
        if r["nearest_support"]:
            pdf.cell(95, 6, f"  Nearest Support: ${r['nearest_support']}")
            pdf.cell(0,  6, f"Suggested Stop-Loss: ${r['stop']}  (1% below support)",
                     new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        # AI Analysis
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, "AI Analysis (Claude)", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8.5)
        summary = ai.get("summary", "")
        if summary:
            pdf.multi_cell(0, 6, f"  Summary: {summary}")

        factors = ai.get("key_factors", [])
        if factors:
            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(0, 5, "  Positive Factors:", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 8)
            for f in factors:
                pdf.multi_cell(0, 5, f"    + {f}")

        risks = ai.get("risk_factors", [])
        if risks:
            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(0, 5, "  Risk Factors:", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 8)
            for risk in risks:
                pdf.multi_cell(0, 5, f"    - {risk}")

        # Verdict
        action = ai.get("action", "")
        cond_count = sum([r["cond_ma"], r["cond_rsi"]])
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 9)
        verdict = "CONSIDER ENTRY (confirm MACD in Moomoo)" if (cond_count == 2 and sent == "bullish") \
             else "WATCH - partial conditions met" if cond_count == 1 \
             else "AVOID - conditions not met"
        pdf.cell(0, 6, f"  Recommendation: {verdict}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

    pdf.output(path)
    print(f"  PDF saved: {path}")


# ── macOS notification ───────────────────────────────────────────────────────
def send_notification(title: str, body: str):
    script = f'display notification "{body}" with title "{title}" sound name "default"'
    subprocess.run(["osascript", "-e", script], capture_output=True)


# ── Email ────────────────────────────────────────────────────────────────────
def send_email(pdf_path: str, results: list[dict]):
    if not GMAIL_USER or not GMAIL_APP_PASS:
        print("  Email skipped — set GMAIL_USER and GMAIL_APP_PASSWORD to enable.")
        return

    date_str = datetime.now().strftime("%Y-%m-%d")
    subject  = f"Daily Stock Report — {date_str}"

    # Plain-text summary for email body
    lines = [f"Daily Stock Report — {date_str}\n"]
    for r in results:
        if r.get("error"):
            lines.append(f"{r['ticker']}: ERROR - {r['error']}")
            continue
        ai   = r.get("ai", {})
        sent = ai.get("sentiment", "?")
        icon = {"bullish": "🟢", "neutral": "🟡", "bearish": "🔴"}.get(sent, "⚪")
        conds = f"MA50:{'✅' if r['cond_ma'] else '❌'} RSI:{'✅' if r['cond_rsi'] else '❌'}"
        lines.append(f"{icon} {r['ticker']:5s}  ${r['price']}  {sent.upper():8s}  {conds}")
        if ai.get("summary"):
            lines.append(f"       {ai['summary']}")
    lines.append("\nSee attached PDF for full analysis.")
    lines.append("For educational purposes only. Not financial advice.")
    body_text = "\n".join(lines)

    msg = MIMEMultipart()
    msg["From"]    = GMAIL_USER
    msg["To"]      = ", ".join(EMAIL_TO)
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    # Attach PDF
    with open(pdf_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(pdf_path)}")
    msg.attach(part)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_USER, EMAIL_TO, msg.as_string())
        print(f"  Email sent to: {', '.join(EMAIL_TO)}")
    except Exception as e:
        print(f"  Email failed: {e}")


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'='*50}")
    print(f"  Daily Stock Report — {date_str}")
    print(f"{'='*50}\n")

    tickers = load_watchlist()
    print(f"Watchlist: {', '.join(tickers)}\n")

    results = [analyse_stock(t) for t in tickers]

    # PDF
    pdf_path = os.path.join(REPORT_DIR, f"report_{date_str}.pdf")
    print("\nGenerating PDF...")
    build_pdf(results, pdf_path)

    # macOS notification
    ok    = [r["ticker"] for r in results if not r.get("error") and r.get("ai", {}).get("sentiment") == "bullish"]
    total = len(results)
    notif_body = f"{total} stocks analysed. Bullish: {', '.join(ok) if ok else 'None'}"
    send_notification("Daily Stock Report Ready", notif_body)
    print(f"\n  Notification sent")

    # Email
    print("Sending email...")
    send_email(pdf_path, results)

    print(f"\nDone. Report saved to:\n  {pdf_path}\n")


if __name__ == "__main__":
    main()
