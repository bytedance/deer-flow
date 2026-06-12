# pywencai API Reference

## Installation

```bash
pip install pywencai
```

**Environment Requirements:**
- Node.js v16+ (required for executing JS code)
- Python 3.6+

## Core API: pywencai.get()

### Required Parameters

#### query (str)
查询问句，使用自然语言描述查询条件

Examples:
- "昨日涨幅前10的股票"
- "市盈率小于20的科技股"
- "退市股票"
- "近3个月每日市盈率"

#### cookie (str)
**必填参数**。从同花顺问财网站获取的 Cookie 值

获取方法：
1. 访问 https://www.iwencai.com/
2. 登录账号
3. 打开浏览器开发者工具 (F12)
4. 查看 Network 标签页中的请求头
5. 复制 Cookie 字段的完整值

### Optional Parameters

#### sort_key (str)
指定用于排序的字段，值为返回结果的列名

Example: `sort_key='退市@退市日期'`

#### sort_order (str)
排序规则
- `'asc'` - 升序
- `'desc'` - 降序

#### page (int)
查询的页号，默认为 1

#### perpage (int)
每页数据条数，默认值 100，最大值 100

#### loop (bool or int)
是否循环分页，返回多页合并数据
- `False` (默认) - 只返回单页
- `True` - 循环到最后一页，返回全部数据
- `n` (整数) - 循环请求 n 页，返回 n 页合并数据

#### query_type (str)
查询类型，默认为 `'stock'`

| 取值 | 含义 |
|------|------|
| stock | 股票 |
| zhishu | 指数 |
| fund | 基金 |
| hkstock | 港股 |
| usstock | 美股 |
| threeboard | 新三板 |
| conbond | 可转债 |
| insurance | 保险 |
| futures | 期货 |
| lccp | 理财 |
| foreign_exchange | 外汇 |

#### retry (int)
请求失败后的重试次数，默认为 10

#### sleep (int)
循环请求时，每次请求间隔秒数，默认为 0

#### log (bool)
是否在控制台打印日志，默认为 `False`

#### pro (bool)
是否使用付费版，默认为 `False`

**Note:** 使用付费版必须传入 cookie 参数

#### request_params (dict)
额外的 request 参数，默认为 `{}`

Example:
```python
request_params={'proxies': proxies}
```

#### no_detail (bool)
默认为 `False`。当为 `True` 时，查询详情类问题不再返回字典，而返回 `None`，保证查询结果类型一致为 `pd.DataFrame` 或 `None`

#### find (list)
默认为 `None`。可以传一个数组，例如 `['600519', '000010']`，数组内的对应标的会排列在 DataFrame 的最前面

**注意：**
1. 该参数只有结果为 DataFrame 时有效
2. 配置该参数后，loop 参数会失效，结果只会返回前 100 条

#### user_agent (str)
默认为 `None`。可以自己传 `user_agent`，不使用随机生成的 `user_agent`

## Return Values

### List Query (列表查询)
返回 `pandas.DataFrame` 对象

### Detail Query (详情查询)
返回字典，字典中可能包含若干个文本和 `DataFrame`

如果设置 `no_detail=True`，则返回 `None`
