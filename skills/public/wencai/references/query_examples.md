# Query Examples

## 基本查询

### 涨跌幅查询
```python
# 昨日涨幅前10
pywencai.get(query='昨日涨幅前10', cookie='xxx')

# 近5日涨幅超过20%
pywencai.get(query='近5日涨幅超过20%', cookie='xxx')

# 今日跌幅超过5%
pywencai.get(query='今日跌幅超过5%', cookie='xxx')
```

### 估值指标查询
```python
# 市盈率小于20
pywencai.get(query='市盈率小于20', cookie='xxx')

# 市净率小于2且市盈率小于30
pywencai.get(query='市净率小于2且市盈率小于30', cookie='xxx')

# 市值大于100亿
pywencai.get(query='市值大于100亿', cookie='xxx')
```

### 行业板块查询
```python
# 科技股
pywencai.get(query='科技股', cookie='xxx')

# 新能源汽车板块
pywencai.get(query='新能源汽车板块', cookie='xxx')

# 半导体行业龙头股
pywencai.get(query='半导体行业龙头股', cookie='xxx')
```

### 技术指标查询
```python
# MACD金叉
pywencai.get(query='MACD金叉', cookie='xxx')

# KDJ超卖
pywencai.get(query='KDJ超卖', cookie='xxx')

# 突破60日均线
pywencai.get(query='突破60日均线', cookie='xxx')
```

## 高级查询

### 排序查询
```python
# 按涨幅排序
pywencai.get(
    query='昨日涨幅',
    sort_key='涨跌幅',
    sort_order='desc',
    cookie='xxx'
)

# 按市值排序
pywencai.get(
    query='A股',
    sort_key='总市值',
    sort_order='desc',
    cookie='xxx'
)
```

### 分页查询
```python
# 获取第2页数据
pywencai.get(query='科技股', page=2, cookie='xxx')

# 每页50条
pywencai.get(query='科技股', perpage=50, cookie='xxx')

# 循环获取所有数据
pywencai.get(query='科技股', loop=True, cookie='xxx')

# 获取前3页数据
pywencai.get(query='科技股', loop=3, cookie='xxx')
```

### 多类型查询
```python
# 查询指数
pywencai.get(query='上证指数', query_type='zhishu', cookie='xxx')

# 查询基金
pywencai.get(query='科技类基金', query_type='fund', cookie='xxx')

# 查询港股
pywencai.get(query='腾讯控股', query_type='hkstock', cookie='xxx')

# 查询可转债
pywencai.get(query='可转债', query_type='conbond', cookie='xxx')
```

### 特定股票查询
```python
# 查询特定股票并置顶
pywencai.get(
    query='科技股',
    find=['600519', '000858'],
    cookie='xxx'
)
```

## 财务数据查询

### 盈利能力
```python
# ROE大于15%
pywencai.get(query='ROE大于15%', cookie='xxx')

# 净利润增长率大于30%
pywencai.get(query='净利润增长率大于30%', cookie='xxx')

# 毛利率大于50%
pywencai.get(query='毛利率大于50%', cookie='xxx')
```

### 成长性
```python
# 营收增长率大于20%
pywencai.get(query='营收增长率大于20%', cookie='xxx')

# 连续3年净利润增长
pywencai.get(query='连续3年净利润增长', cookie='xxx')
```

### 偿债能力
```python
# 资产负债率小于30%
pywencai.get(query='资产负债率小于30%', cookie='xxx')

# 流动比率大于2
pywencai.get(query='流动比率大于2', cookie='xxx')
```

## 组合条件查询

```python
# 复杂组合条件
pywencai.get(
    query='市盈率小于20且市净率小于2且ROE大于15%且市值大于50亿',
    sort_key='涨跌幅',
    sort_order='desc',
    loop=True,
    cookie='xxx'
)

# 技术面+基本面组合
pywencai.get(
    query='MACD金叉且市盈率小于30且近5日涨幅大于10%',
    cookie='xxx'
)
```

## 时间序列查询

```python
# 历史数据
pywencai.get(query='近3个月每日市盈率', pro=True, cookie='xxx')

# 特定日期
pywencai.get(query='2024年1月1日的涨幅', cookie='xxx')
```

## 完整实战示例

### 多条件技术面选股（已验证可运行）

```python
import pywencai

# -------------------------- 核心配置 --------------------------
# 1. 替换为你自己的问财Cookie（获取方式见SKILL.md）
COOKIE = "你的问财Cookie值"

# 2. 构造问财查询语句
QUERY = """
涨幅大于1%，大单金额大于5000万，10日内ma10金叉ma60，
月macd大于0，流通市值大于50亿，收盘价大于ma10，ma10向上角度大于40度
""".replace("\n", "").strip()  # 去除换行符，保证查询语句格式正确

# -------------------------- 执行查询 --------------------------
def get_wencai_data():
    try:
        # 调用pywencai.get方法查询数据
        result = pywencai.get(
            query=QUERY,          # 核心查询语句
            cookie=COOKIE,        # 必填：问财Cookie
            loop=True,            # 循环分页，返回全部结果（默认False仅返回第1页）
            perpage=100,          # 每页条数（最大100，问财限制）
            log=True,             # 打印日志（方便排查问题）
            query_type="stock",   # 查询类型：股票（默认值，可省略）
            # request_params={"proxies": {"http": "http://代理IP:端口"}}  # 可选：添加代理（如需）
        )
        return result
    except Exception as e:
        print(f"查询失败：{str(e)}")
        return None

# -------------------------- 结果处理 --------------------------
if __name__ == "__main__":
    data = get_wencai_data()
    if data is not None:
        print(f"查询结果共 {len(data)} 条")
        print("\n前5条数据：")
        print(data.head())

        # 可选：保存到CSV
        # data.to_csv('wencai_result.csv', index=False, encoding='utf-8-sig')
```

**查询条件说明：**
- `涨幅大于1%` - 当日涨幅筛选
- `大单金额大于5000万` - 资金流入筛选
- `10日内ma10金叉ma60` - 均线金叉信号
- `月macd大于0` - MACD月线多头
- `流通市值大于50亿` - 市值筛选
- `收盘价大于ma10` - 价格在均线之上
- `ma10向上角度大于40度` - 均线角度筛选

**参数说明：**
- `loop=True` - 自动翻页获取所有结果
- `perpage=100` - 每页最多100条（问财限制）
- `log=True` - 显示查询日志，便于调试
- `query_type="stock"` - 指定查询股票数据
