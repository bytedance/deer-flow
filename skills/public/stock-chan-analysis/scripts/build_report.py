#!/usr/bin/env python3
"""Build interactive HTML report from chan analysis results."""
import sys, os, json

LT = chr(60)
GT = chr(62)
SL = chr(47)
QQ = chr(34)

def H(name, attrs=None, content=None, void=False):
    """Safely build an HTML element. attrs is dict, content is string or list of strings."""
    a = ''
    if attrs:
        for k, v in attrs.items():
            if isinstance(v, list):
                v = ' '.join(v)
            a += f' {k}={QQ}{v}{QQ}'
    if void:
        return f'{LT}{name}{a}{GT}'
    inner = ''
    if content is not None:
        inner = ''.join(content) if isinstance(content, list) else str(content)
    return f'{LT}{name}{a}{GT}{inner}{LT}{SL}{name}{GT}'

def text(s):
    return str(s)

CSS = """*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:#0d1117;color:#c9d1d9}
.header{padding:20px 30px;background:#161b22;border-bottom:1px solid #30363d}
.header h1{font-size:22px;color:#58a6ff}
.header p{font-size:13px;color:#8b949e;margin-top:4px}
.tabs{display:flex;gap:2px;padding:10px 30px;background:#161b22}
.tab{padding:8px 20px;cursor:pointer;border-radius:6px 6px 0 0;background:#21262d;color:#8b949e;font-size:14px;border:1px solid transparent}
.tab.active{background:#0d1117;color:#58a6ff;border-color:#30363d;border-bottom-color:#0d1117}
.tab:hover:not(.active){color:#c9d1d9}
.chart-container{width:100%;height:calc(100vh - 260px);position:relative}
#chart{width:100%;height:100%}
.summary{padding:15px 30px;background:#161b22;border-top:1px solid #30363d;font-size:13px;display:flex;gap:30px;flex-wrap:wrap}
.summary-block h4{color:#8b949e;font-weight:400;margin-bottom:4px}
.summary-block .val{font-size:18px;font-weight:700}
.val.bullish{color:#3fb950}.val.bearish{color:#f85149}
.legend{display:flex;gap:16px;align-items:center;font-size:12px;color:#8b949e;margin-left:auto}
.legend span::before{content:"*";display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:4px;vertical-align:middle}
.legend .b1::before{background:#3fb950}.legend .b2::before{background:#2ea043}.legend .b3::before{background:#1f6feb}
.legend .s1::before{background:#f85149}.legend .s2::before{background:#da3633}.legend .s3::before{background:#ff7b72}
.tooltip{position:fixed;background:#21262d;border:1px solid #30363d;border-radius:8px;padding:12px 16px;font-size:13px;pointer-events:none;z-index:9999;display:none;max-width:280px;box-shadow:0 8px 24px rgba(0,0,0,.4)}
.tooltip h3{font-size:14px;margin-bottom:4px}.tooltip .tt-price{font-size:18px;font-weight:700}
.tooltip .tt-row{display:flex;justify-content:space-between;margin-top:4px;color:#8b949e}
"""
print("Part1 done: helpers + CSS")

# Load JS template from pre-encoded base64
import base64 as _b64
_JS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_js_core_b64.txt')
with open(_JS_PATH, 'r') as _f:
    JS_CORE = _b64.b64decode(_f.read().strip()).decode('utf-8')

def _build_head(stock_code):
    title_text = 'Chan Analysis - ' + stock_code
    doctype = '<!DOCTYPE html>'
    parts = [
        doctype,
        H('html', {'lang': 'en'}, [
            H('head', content=[
                H('meta', {'charset': 'UTF-8'}, void=True),
                H('meta', {'name': 'viewport', 'content': 'width=device-width,initial-scale=1.0'}, void=True),
                H('title', content=title_text),
                H('style', content=CSS),
            ]),
            '__BODY__',
        ]),
    ]
    return '\n'.join(parts)

def _build_body(stock_code, date_str):
    header = H('div', {'class': 'header'}, [
        H('h1', content=stock_code + ' Chan Analysis'),
        H('p', content='MTF Chan Theory: Bi, ZhongShu, Buy Sell Points  |  Generated: ' + date_str),
    ])
    tabs = H('div', {'class': 'tabs'}, [
        H('div', {'class': 'tab active', 'data-period': 'daily', 'onclick': 'switchPeriod("daily")'}, 'Daily'),
        H('div', {'class': 'tab', 'data-period': '30min', 'onclick': 'switchPeriod("30min")'}, '30min'),
        H('div', {'class': 'tab', 'data-period': '5min', 'onclick': 'switchPeriod("5min")'}, '5min'),
    ])
    chart_ct = H('div', {'class': 'chart-container'}, H('div', {'id': 'chart'}))
    summary = H('div', {'class': 'summary'}, [
        H('div', {'class': 'summary-block'}, [H('h4', content='Buy Signals'), H('div', {'class': 'val bullish', 'id': 'sum-buy'}, '0')]),
        H('div', {'class': 'summary-block'}, [H('h4', content='Sell Signals'), H('div', {'class': 'val bearish', 'id': 'sum-sell'}, '0')]),
        H('div', {'class': 'summary-block'}, [H('h4', content='Bi'), H('div', {'class': 'val', 'id': 'sum-bi'}, '0')]),
        H('div', {'class': 'summary-block'}, [H('h4', content='ZhongShu'), H('div', {'class': 'val', 'id': 'sum-zs'}, '0')]),
        H('div', {'class': 'summary-block'}, [H('h4', content='K-lines'), H('div', {'class': 'val', 'id': 'sum-kl'}, '0')]),
        H('div', {'class': 'legend'}, [
            H('span', {'class': 'b1'}, '1Buy'), H('span', {'class': 'b2'}, '2Buy'), H('span', {'class': 'b3'}, '3Buy'),
            H('span', {'class': 's1'}, '1Sell'), H('span', {'class': 's2'}, '2Sell'), H('span', {'class': 's3'}, '3Sell'),
        ]),
    ])
    tooltip = H('div', {'class': 'tooltip', 'id': 'tooltip'})
    script_lib = H('script', {'src': 'https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js'}, '')
    return '\n'.join([header, tabs, chart_ct, summary, tooltip, script_lib])

def build_report(stock_code, data_dir, output_path):
    """Load analysis JSON, generate interactive HTML report."""
    all_data = {}
    for p in ['daily', '30min', '5min']:
        jp = os.path.join(data_dir, f'{stock_code}_{p}.json')
        if os.path.exists(jp):
            with open(jp, 'r', encoding='utf-8') as f:
                all_data[p] = json.load(f)
    if not all_data:
        print('ERROR: No analysis data found in', data_dir)
        sys.exit(1)

    from datetime import datetime
    date_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    body_html = _build_body(stock_code, date_str)
    js_inline = JS_CORE.replace('__DATA_PLACEHOLDER__', json.dumps(all_data, ensure_ascii=False))
    script_tag = H('script', content=js_inline)

    full_body = body_html.strip() + '\n' + script_tag
    full_html = _build_head(stock_code).replace('__BODY__', full_body)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(full_html)
    print(f'Report saved to: {output_path}')
    return output_path

if __name__ == '__main__':
    if len(sys.argv) < 4:
        print('Usage: python build_report.py <stock_code> <data_dir> <output_html>')
        sys.exit(1)
    build_report(sys.argv[1], sys.argv[2], sys.argv[3])
