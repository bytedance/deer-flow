---
name: wencai
description: "Query Chinese A-share market data using pywencai library with natural language queries. Use when users need to: (1) Query real-time stock prices, financial indicators, or technical analysis data for A-share stocks, (2) Search for stocks by conditions (e.g., 市盈率小于20的科技股, 昨日涨幅前10), (3) Get sector/industry information, (4) Query indices, funds, convertible bonds, or other financial instruments, (5) Analyze financial statements or technical indicators. Triggers on mentions of: A股, 同花顺, 问财,wencai, pywencai, A股, Chinese stocks, or natural language stock queries in Chinese."
---

# Wencai - A股市场数据查询

## Overview

Query Chinese A-share market data using the pywencai library. Supports natural language queries for real-time prices, financial indicators, technical analysis, and sector information.

## Quick Start

Basic usage pattern:

```python
import pywencai

# Simple query
result = pywencai.get(query='昨日涨幅前10', cookie='your_cookie_here')
print(result)
```

**Critical requirement:** Cookie parameter is mandatory. Users must provide their cookie from https://www.iwencai.com/

## Environment Setup

Before first use, verify dependencies:

```bash
python scripts/check_environment.py
```

Required:
- Node.js v16+ (pywencai executes JS code internally)
- pywencai package: `pip install pywencai`

## Cookie Authentication

**Every query requires a valid cookie parameter.**

Guide users to obtain cookie:
1. Visit https://www.iwencai.com/ and login
2. Open browser DevTools (F12)
3. Go to Network tab
4. Copy the Cookie header value from any request

Store cookie securely (environment variable or config file recommended).

## Common Query Patterns

### Market Screening
```python
# By valuation
pywencai.get(query='市盈率小于20且市值大于50亿', cookie=cookie)

# By performance
pywencai.get(query='近5日涨幅超过20%', cookie=cookie)

# By sector
pywencai.get(query='新能源汽车板块', cookie=cookie)

# By technical indicators
pywencai.get(query='MACD金叉', cookie=cookie)
```

### Advanced Multi-Condition Screening
```python
# Complex technical analysis (verified working example)
query = """
涨幅大于1%，大单金额大于5000万，10日内ma10金叉ma60，
月macd大于0，流通市值大于50亿，收盘价大于ma10，ma10向上角度大于40度
""".replace("\n", "").strip()

result = pywencai.get(
    query=query,
    cookie=cookie,
    loop=True,      # Get all pages
    perpage=100,    # Max 100 per page
    log=True        # Show debug logs
)

if result is not None:
    print(f"Found {len(result)} stocks")
    print(result.head())
```

### Sorted Results
```python
pywencai.get(
    query='科技股',
    sort_key='涨跌幅',
    sort_order='desc',
    cookie=cookie
)
```

### Multiple Pages
```python
# Get all data
pywencai.get(query='A股', loop=True, cookie=cookie)

# Get first 3 pages
pywencai.get(query='A股', loop=3, cookie=cookie)
```

### Non-Stock Queries
```python
# Indices
pywencai.get(query='上证指数', query_type='zhishu', cookie=cookie)

# Funds
pywencai.get(query='科技类基金', query_type='fund', cookie=cookie)

# Convertible bonds
pywencai.get(query='可转债', query_type='conbond', cookie=cookie)
```

## Return Values

- **List queries** → `pandas.DataFrame`
- **Detail queries** → `dict` (contains text and DataFrames)
- Use `no_detail=True` to always return DataFrame or None

## Best Practices

1. **Low frequency usage** - Avoid high-frequency calls to prevent blocking
2. **Cookie management** - Store cookie securely, refresh when expired
3. **Error handling** - Wrap calls in try-except for network/auth errors
4. **Rate limiting** - Use `sleep` parameter for batch queries
5. **Data validation** - Check if result is None or empty DataFrame

## Detailed References

- **API parameters**: See [api_reference.md](references/api_reference.md) for complete parameter documentation
- **Query examples**: See [query_examples.md](references/query_examples.md) for comprehensive query patterns

## Troubleshooting

**"Cookie required" error**: User must provide valid cookie parameter

**"Node.js not found"**: Install Node.js v16+ from https://nodejs.org/

**Empty results**: Query may be too restrictive or cookie expired

**Rate limiting**: Reduce query frequency or add `sleep` parameter
