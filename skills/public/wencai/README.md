# quant-skills

Quantitative finance skills for Claude Code.

## Available Skills

### Wencai Skill

A skill for querying Chinese A-share market data using the pywencai library with natural language queries.

#### Installation

```bash
# Install the skill
claude skill install wencai.skill

# Install Python dependencies
pip install pywencai

# Verify environment (requires Node.js v16+)
python wencai/scripts/check_environment.py
```

#### Quick Start

1. **Get your cookie** from https://www.iwencai.com/:
   - Login to the website
   - Open browser DevTools (F12) → Network tab
   - Copy the Cookie header value from any request

2. **Use in Claude Code**:
   ```python
   import pywencai

   # Query with natural language
   result = pywencai.get(
       query='昨日涨幅前10',
       cookie='your_cookie_here'
   )
   print(result)
   ```

3. **Or simply ask Claude**:
   - "帮我查询昨日涨幅前10的股票"
   - "查询市盈率小于20的科技股"
   - "获取新能源汽车板块的股票"
   - "找出MACD金叉的股票"

#### Features

- Natural language queries for A-share market data
- Real-time prices, financial indicators, technical analysis
- Support for stocks, indices, funds, convertible bonds
- Automatic cookie authentication guidance
- Environment validation and troubleshooting

#### Requirements

- **Node.js v16+** (pywencai executes JS internally)
- **Python package**: `pywencai`
- **Valid cookie** from https://www.iwencai.com/

#### Package Structure

```
wencai.skill (5.7KB zip archive)
└── wencai/
    ├── SKILL.md                      # Main documentation
    ├── scripts/
    │   └── check_environment.py      # Environment validation
    └── references/
        ├── api_reference.md          # Complete API documentation
        └── query_examples.md         # Query examples
```

#### Auto-Triggers

The skill automatically activates when you mention:
- A股, 同花顺, 问财, pywencai
- Chinese stock queries in natural language
- Financial indicators or technical analysis terms

---

## Development

Skills are created using the skill-creator workflow for Claude Code.

