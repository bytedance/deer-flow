# DuckDB SQL 函数参考手册

> 本文档适用于 dify-csv-sql-query-plugin 项目，该项目使用 DuckDB 作为 SQL 引擎。
> 
> **使用提示**: 查询时表名固定为 `data`，例如 `SELECT * FROM data`。

## 目录

- [聚合函数](#聚合函数)
- [近似聚合函数](#近似聚合函数)
- [统计聚合函数](#统计聚合函数)
- [数值函数](#数值函数)
- [文本/字符串函数](#文本字符串函数)
- [日期函数](#日期函数)
- [时间函数](#时间函数)
- [时间戳函数](#时间戳函数)
- [时间间隔函数](#时间间隔函数)
- [窗口函数](#窗口函数)
- [列表函数](#列表函数)
- [数组函数](#数组函数)
- [Map函数](#map函数)
- [结构体函数](#结构体函数)
- [Union函数](#union函数)
- [位运算函数](#位运算函数)
- [Blob函数](#blob函数)
- [枚举函数](#枚举函数)
- [Lambda函数](#lambda函数)
- [工具函数](#工具函数)
- [日期格式函数](#日期格式函数)

---

## 聚合函数

### 通用聚合函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `any_value` | `any_value(arg)` | `arg`: 任意列或表达式 | 与arg相同 | 返回第一个非NULL值 | `any_value(name)` |
| `arg_max` | `arg_max(arg, val)` | `arg`: 要返回的表达式, `val`: 用于比较的值 | 与arg相同 | 找到val最大值所在的行，返回该行的arg | `arg_max(name, score)` |
| `arg_max` | `arg_max(arg, val, n)` | `arg`: 表达式, `val`: 比较值, `n`: 返回数量 | LIST | 返回val最大的前n行对应的arg列表 | `arg_max(name, score, 3)` |
| `arg_min` | `arg_min(arg, val)` | `arg`: 要返回的表达式, `val`: 用于比较的值 | 与arg相同 | 找到val最小值所在的行，返回该行的arg | `arg_min(name, score)` |
| `arg_min` | `arg_min(arg, val, n)` | `arg`: 表达式, `val`: 比较值, `n`: 返回数量 | LIST | 返回val最小的前n行对应的arg列表 | `arg_min(name, score, 3)` |
| `avg` | `avg(arg)` | `arg`: 数值列 | DOUBLE | 计算所有非NULL值的平均值 | `avg(price)` |
| `bit_and` | `bit_and(arg)` | `arg`: 整数列 | 与arg相同 | 返回所有值的按位与 | `bit_and(flags)` |
| `bit_or` | `bit_or(arg)` | `arg`: 整数列 | 与arg相同 | 返回所有值的按位或 | `bit_or(flags)` |
| `bit_xor` | `bit_xor(arg)` | `arg`: 整数列 | 与arg相同 | 返回所有值的按位异或 | `bit_xor(flags)` |
| `bool_and` | `bool_and(arg)` | `arg`: 布尔列 | BOOLEAN | 如果所有值为true则返回true | `bool_and(is_valid)` |
| `bool_or` | `bool_or(arg)` | `arg`: 布尔列 | BOOLEAN | 如果任一值为true则返回true | `bool_or(is_active)` |
| `count` | `count()` 或 `count(*)` | 无参数 | BIGINT | 返回总行数 | `count()` |
| `count` | `count(arg)` | `arg`: 任意列 | BIGINT | 返回arg不为NULL的行数 | `count(name)` |
| `countif` | `countif(arg)` | `arg`: 布尔表达式 | BIGINT | 返回arg为true的行数 | `countif(score > 60)` |
| `first` | `first(arg)` | `arg`: 任意列 | 与arg相同 | 返回第一个值（可为NULL） | `first(name)` |
| `last` | `last(arg)` | `arg`: 任意列 | 与arg相同 | 返回最后一个值 | `last(name)` |
| `list` | `list(arg)` | `arg`: 任意列 | LIST | 返回包含所有值的列表 | `list(name)` |
| `max` | `max(arg)` | `arg`: 可比较列 | 与arg相同 | 返回最大值 | `max(price)` |
| `max` | `max(arg, n)` | `arg`: 可比较列, `n`: 数量 | LIST | 返回最大的n个值组成的列表 | `max(price, 5)` |
| `min` | `min(arg)` | `arg`: 可比较列 | 与arg相同 | 返回最小值 | `min(price)` |
| `min` | `min(arg, n)` | `arg`: 可比较列, `n`: 数量 | LIST | 返回最小的n个值组成的列表 | `min(price, 5)` |
| `product` | `product(arg)` | `arg`: 数值列 | 与arg相同 | 计算所有非NULL值的乘积 | `product(factor)` |
| `string_agg` | `string_agg(arg, sep)` | `arg`: 字符串列, `sep`: 分隔符 | VARCHAR | 用分隔符连接所有字符串值 | `string_agg(name, ', ')` |
| `sum` | `sum(arg)` | `arg`: 数值列或布尔列 | 与arg相同 | 计算所有非NULL值的和（布尔值计为1） | `sum(amount)` |
| `favg` | `favg(arg)` | `arg`: 数值列 | DOUBLE | 使用Kahan Sum算法计算更精确的平均值 | `favg(price)` |
| `fsum` | `fsum(arg)` | `arg`: 数值列 | DOUBLE | 使用Kahan Sum算法计算更精确的和 | `fsum(amount)` |
| `geometric_mean` | `geometric_mean(arg)` | `arg`: 数值列 | DOUBLE | 计算几何平均值 | `geometric_mean(rate)` |
| `histogram` | `histogram(arg)` | `arg`: 任意列 | MAP | 返回键值对表示的直方图 | `histogram(category)` |
| `weighted_avg` | `weighted_avg(arg, weight)` | `arg`: 数值列, `weight`: 权重列 | DOUBLE | 计算加权平均值 | `weighted_avg(score, weight)` |

**别名说明**:
- `mean` → `avg`
- `arbitrary` → `first`
- `argmax` / `max_by` → `arg_max`
- `argmin` / `min_by` → `arg_min`
- `group_concat` / `listagg` → `string_agg`
- `sumkahan` / `kahan_sum` → `fsum`
- `geomean` → `geometric_mean`
- `wavg` → `weighted_avg`
- `array_agg` → `list`

---

## 近似聚合函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `approx_count_distinct` | `approx_count_distinct(x)` | `x`: 任意列 | BIGINT | 使用HyperLogLog计算近似不重复计数 | `approx_count_distinct(user_id)` |
| `approx_quantile` | `approx_quantile(x, pos)` | `x`: 数值列, `pos`: 分位数位置(0-1) | DOUBLE | 使用T-Digest计算近似分位数 | `approx_quantile(price, 0.5)` |
| `approx_top_k` | `approx_top_k(arg, k)` | `arg`: 任意列, `k`: 返回数量 | LIST | 计算出现频率最高的k个值的近似列表 | `approx_top_k(category, 5)` |
| `reservoir_quantile` | `reservoir_quantile(x, quantile, sample_size)` | `x`: 数值列, `quantile`: 分位数, `sample_size`: 采样大小(默认8192) | DOUBLE | 使用蓄水池采样计算近似分位数 | `reservoir_quantile(price, 0.5, 10000)` |

---

## 统计聚合函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 |
|------|------|----------|----------|------|
| `corr` | `corr(y, x)` | `y`, `x`: 数值列 | DOUBLE | 相关系数 |
| `covar_pop` | `covar_pop(y, x)` | `y`, `x`: 数值列 | DOUBLE | 总体协方差（无偏校正） |
| `covar_samp` | `covar_samp(y, x)` | `y`, `x`: 数值列 | DOUBLE | 样本协方差（有Bessel偏校正） |
| `entropy` | `entropy(x)` | `x`: 任意列 | DOUBLE | 计数输入值的log-2熵 |
| `kurtosis` | `kurtosis(x)` | `x`: 数值列 | DOUBLE | 样本超额峰度（Fisher定义，有偏校正） |
| `kurtosis_pop` | `kurtosis_pop(x)` | `x`: 数值列 | DOUBLE | 总体超额峰度（无偏校正） |
| `mad` | `mad(x)` | `x`: 数值列 | DOUBLE | 中位数绝对偏差 |
| `median` | `median(x)` | `x`: 数值列 | 与x相同 | 中位数 |
| `mode` | `mode(x)` | `x`: 任意列 | 与x相同 | 众数（最频繁的值） |
| `quantile_cont` | `quantile_cont(x, pos)` | `x`: 数值列, `pos`: 分位数位置(0-1) | DOUBLE | 连续分位数（插值计算） |
| `quantile_disc` | `quantile_disc(x, pos)` | `x`: 数值列, `pos`: 分位数位置(0-1) | 与x相同 | 离散分位数 |
| `regr_avgx` | `regr_avgx(y, x)` | `y`, `x`: 数值列 | DOUBLE | 非NULL对的独立变量平均值 |
| `regr_avgy` | `regr_avgy(y, x)` | `y`, `x`: 数值列 | DOUBLE | 非NULL对的因变量平均值 |
| `regr_count` | `regr_count(y, x)` | `y`, `x`: 数值列 | BIGINT | 非NULL对的数量 |
| `regr_intercept` | `regr_intercept(y, x)` | `y`, `x`: 数值列 | DOUBLE | 线性回归截距 |
| `regr_r2` | `regr_r2(y, x)` | `y`, `x`: 数值列 | DOUBLE | 决定系数R² |
| `regr_slope` | `regr_slope(y, x)` | `y`, `x`: 数值列 | DOUBLE | 线性回归斜率 |
| `regr_sxx` | `regr_sxx(y, x)` | `y`, `x`: 数值列 | DOUBLE | 独立变量平方和 |
| `regr_sxy` | `regr_sxy(y, x)` | `y`, `x`: 数值列 | DOUBLE | 独立变量与因变量乘积和 |
| `regr_syy` | `regr_syy(y, x)` | `y`, `x`: 数值列 | DOUBLE | 因变量平方和 |
| `skewness` | `skewness(x)` | `x`: 数值列 | DOUBLE | 偏度 |
| `stddev_pop` | `stddev_pop(x)` | `x`: 数值列 | DOUBLE | 总体标准差 |
| `stddev_samp` | `stddev_samp(x)` | `x`: 数值列 | DOUBLE | 样本标准差 |
| `var_pop` | `var_pop(x)` | `x`: 数值列 | DOUBLE | 总体方差 |
| `var_samp` | `var_samp(x)` | `x`: 数值列 | DOUBLE | 样本方差 |

**别名**: `stddev` → `stddev_samp`, `variance` → `var_samp`

---

## 数值函数

### 数值操作符

| 操作符 | 描述 | 示例 | 结果 |
|--------|------|------|------|
| `+` | 加法 | `2 + 3` | `5` |
| `-` | 减法 | `2 - 3` | `-1` |
| `*` | 乘法 | `2 * 3` | `6` |
| `/` | 浮点除法 | `5 / 2` | `2.5` |
| `//` | 整数除法 | `5 // 2` | `2` |
| `%` | 取模 | `5 % 4` | `1` |
| `**` 或 `^` | 幂运算 | `3 ** 4` | `81` |

### 位运算操作符

| 操作符 | 描述 | 示例 | 结果 |
|--------|------|------|------|
| `&` | 按位与 | `91 & 15` | `11` |
| `\|` | 按位或 | `32 \| 3` | `35` |
| `<<` | 左移 | `1 << 4` | `16` |
| `>>` | 右移 | `8 >> 2` | `2` |
| `~` | 按位取反 | `~15` | `-16` |
| `!` | 阶乘（后缀） | `4!` | `24` |

### 数值函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `abs` | `abs(x)` | `x`: 数值 | 与x相同 | 绝对值 | `abs(-17.4)` → `17.4` |
| `ceil` | `ceil(x)` | `x`: 数值 | 与x相同 | 向上取整 | `ceil(17.4)` → `18` |
| `floor` | `floor(x)` | `x`: 数值 | 与x相同 | 向下取整 | `floor(17.4)` → `17` |
| `round` | `round(v, s)` | `v`: 数值, `s`: 小数位数 | NUMERIC | 四舍五入到s位小数 | `round(42.4332, 2)` → `42.43` |
| `round_even` | `round_even(v, s)` | `v`: 数值, `s`: 小数位数 | NUMERIC | 银行家舍入（四舍六入五取偶） | `round_even(24.5, 0)` → `24.0` |
| `trunc` | `trunc(x)` | `x`: 数值 | 与x相同 | 截断（向零取整） | `trunc(17.4)` → `17` |
| `sqrt` | `sqrt(x)` | `x`: 非负数值 | DOUBLE | 平方根 | `sqrt(9)` → `3` |
| `cbrt` | `cbrt(x)` | `x`: 数值 | DOUBLE | 立方根 | `cbrt(8)` → `2` |
| `pow` | `pow(x, y)` | `x`: 底数, `y`: 指数 | DOUBLE | x的y次方 | `pow(2, 3)` → `8` |
| `exp` | `exp(x)` | `x`: 数值 | DOUBLE | e的x次方 | `exp(0.693)` → `2` |
| `ln` | `ln(x)` | `x`: 正数 | DOUBLE | 自然对数 | `ln(2)` → `0.693` |
| `log` | `log(x)` | `x`: 正数 | DOUBLE | 以10为底的对数 | `log(100)` → `2` |
| `log2` | `log2(x)` | `x`: 正数 | DOUBLE | 以2为底的对数 | `log2(8)` → `3` |
| `gcd` | `gcd(x, y)` | `x`, `y`: 整数 | INTEGER | 最大公约数 | `gcd(42, 57)` → `3` |
| `lcm` | `lcm(x, y)` | `x`, `y`: 整数 | INTEGER | 最小公倍数 | `lcm(42, 57)` → `798` |
| `factorial` | `factorial(x)` | `x`: 非负整数 | BIGINT | 阶乘 | `factorial(4)` → `24` |
| `sign` | `sign(x)` | `x`: 数值 | INTEGER | 符号（-1, 0, 1） | `sign(-349)` → `-1` |
| `pi` | `pi()` | 无参数 | DOUBLE | π值 | `pi()` → `3.14159...` |
| `random` | `random()` | 无参数 | DOUBLE | 0.0到1.0之间的随机数 | `random()` |
| `setseed` | `setseed(x)` | `x`: 种子值(0-1) | 无 | 设置随机数种子 | `setseed(0.42)` |

### 三角函数

| 函数 | 语法 | 参数说明 | 描述 | 示例 |
|------|------|----------|------|------|
| `sin` | `sin(x)` | `x`: 弧度 | 正弦 | `sin(pi() / 6)` |
| `cos` | `cos(x)` | `x`: 弧度 | 余弦 | `cos(0)` → `1` |
| `tan` | `tan(x)` | `x`: 弧度 | 正切 | `tan(pi() / 4)` → `1` |
| `asin` | `asin(x)` | `x`: -1到1 | 反正弦 | `asin(0.5)` |
| `acos` | `acos(x)` | `x`: -1到1 | 反余弦 | `acos(0.5)` |
| `atan` | `atan(x)` | `x`: 任意数 | 反正切 | `atan(1)` |
| `atan2` | `atan2(y, x)` | `y`, `x`: 任意数 | 两参数反正切 | `atan2(0.5, 0.5)` |
| `sinh` | `sinh(x)` | `x`: 数值 | 双曲正弦 | `sinh(0.5)` |
| `cosh` | `cosh(x)` | `x`: 数值 | 双曲余弦 | `cosh(0.5)` |
| `tanh` | `tanh(x)` | `x`: 数值 | 双曲正切 | `tanh(0.5)` |
| `asinh` | `asinh(x)` | `x`: 数值 | 反双曲正弦 | `asinh(0.5)` |
| `acosh` | `acosh(x)` | `x`: ≥1 | 反双曲余弦 | `acosh(1.5)` |
| `atanh` | `atanh(x)` | `x`: -1到1(不含) | 反双曲正切 | `atanh(0.5)` |
| `degrees` | `degrees(x)` | `x`: 弧度 | 弧度转角度 | `degrees(pi())` → `180` |
| `radians` | `radians(x)` | `x`: 角度 | 角度转弧度 | `radians(90)` |

### 特殊函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `fdiv` | `fdiv(x, y)` | `x`, `y`: 数值 | DOUBLE | 整数除法，返回DOUBLE | `fdiv(5, 2)` → `2.0` |
| `fmod` | `fmod(x, y)` | `x`, `y`: 数值 | DOUBLE | 取模，返回DOUBLE | `fmod(5, 2)` → `1.0` |
| `even` | `even(x)` | `x`: 数值 | 与x相同 | 向远离零的方向舍入到最近的偶数 | `even(2.9)` → `4` |
| `bit_count` | `bit_count(x)` | `x`: 整数 | INTEGER | 返回设置的位数 | `bit_count(31)` → `5` |
| `xor` | `xor(x, y)` | `x`, `y`: 整数 | INTEGER | 按位异或 | `xor(17, 5)` → `20` |
| `nextafter` | `nextafter(x, y)` | `x`, `y`: 浮点数 | DOUBLE | 返回x朝向y方向的下一个浮点数 | `nextafter(1::float, 2::float)` |
| `isfinite` | `isfinite(x)` | `x`: 浮点数 | BOOLEAN | 是否为有限浮点数 | `isfinite(1.0)` → `true` |
| `isinf` | `isinf(x)` | `x`: 浮点数 | BOOLEAN | 是否为无限浮点数 | `isinf('inf'::float)` → `true` |
| `isnan` | `isnan(x)` | `x`: 浮点数 | BOOLEAN | 是否为NaN | `isnan('NaN'::float)` → `true` |
| `greatest` | `greatest(x1, x2, ...)` | 多个数值 | 与输入相同 | 选择最大值 | `greatest(3, 2, 4, 4)` → `4` |
| `least` | `least(x1, x2, ...)` | 多个数值 | 与输入相同 | 选择最小值 | `least(3, 2, 4, 4)` → `2` |
| `gamma` | `gamma(x)` | `x`: 正数 | DOUBLE | 伽马函数 | `gamma(5.5)` |
| `lgamma` | `lgamma(x)` | `x`: 正数 | DOUBLE | 伽马函数的对数 | `lgamma(5.5)` |

**别名**: `ceiling` → `ceil`, `power` → `pow`, `log10` → `log`

---

## 文本/字符串函数

### 字符串操作符

| 操作符 | 描述 | 示例 | 结果 |
|--------|------|------|------|
| `string[index]` | 提取单个字符（1-based索引） | `'DuckDB'[4]` | `k` |
| `string[begin:end]` | Python风格切片 | `'DuckDB'[:4]` | `Duck` |
| `\|\|` | 连接字符串/列表/blob | `'Duck' \|\| 'DB'` | `DuckDB` |
| `LIKE` | 模式匹配（%和_通配符） | `'hello' LIKE '%lo'` | `true` |
| `SIMILAR TO` | 正则表达式匹配 | `'hello' SIMILAR TO 'h.*o'` | `true` |
| `^@` | 前缀匹配（starts_with别名） | `'hello' ^@ 'hel'` | `true` |

### 提取函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `left` | `left(string, count)` | `string`: 字符串, `count`: 字符数 | VARCHAR | 返回最左边count个字符 | `left('DuckDB', 4)` → `Duck` |
| `right` | `right(string, count)` | `string`: 字符串, `count`: 字符数 | VARCHAR | 返回最右边count个字符 | `right('DuckDB', 2)` → `DB` |
| `substring` | `substring(string, start[, length])` | `string`: 字符串, `start`: 起始位置(1-based), `length`: 长度 | VARCHAR | 提取子串 | `substring('DuckDB', 2, 3)` → `uck` |
| `array_extract` | `array_extract(string, index)` | `string`: 字符串, `index`: 位置(1-based) | VARCHAR | 提取指定位置字符 | `array_extract('DuckDB', 1)` → `D` |
| `array_slice` | `array_slice(string, begin, end)` | `string`: 字符串, `begin`: 起始, `end`: 结束 | VARCHAR | Python风格切片 | `array_slice('DuckDB', 2, 4)` → `uck` |

### 大小写转换

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `lower` | `lower(string)` | `string`: 字符串 | VARCHAR | 转换为小写 | `lower('DuckDB')` → `duckdb` |
| `upper` | `upper(string)` | `string`: 字符串 | VARCHAR | 转换为大写 | `upper('duckdb')` → `DUCKDB` |

**别名**: `lcase` → `lower`, `ucase` → `upper`

### 搜索函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `contains` | `contains(string, search_string)` | `string`: 源字符串, `search_string`: 搜索字符串 | BOOLEAN | 检查是否包含子串 | `contains('DuckDB', 'Duck')` → `true` |
| `starts_with` | `starts_with(string, search_string)` | `string`: 源字符串, `search_string`: 前缀 | BOOLEAN | 检查是否以指定字符串开头 | `starts_with('DuckDB', 'Duck')` → `true` |
| `ends_with` | `ends_with(string, search_string)` | `string`: 源字符串, `search_string`: 后缀 | BOOLEAN | 检查是否以指定字符串结尾 | `ends_with('DuckDB', 'DB')` → `true` |
| `instr` | `instr(string, search_string)` | `string`: 源字符串, `search_string`: 搜索字符串 | INTEGER | 返回子串首次出现位置（1-based，0表示未找到） | `instr('DuckDB', 'DB')` → `5` |
| `position` | `position(search_string IN string)` | 同上 | INTEGER | instr的SQL标准语法 | `position('DB' IN 'DuckDB')` → `5` |

**别名**: `prefix` → `starts_with`, `suffix` → `ends_with`, `strpos` → `instr`

### 填充与修剪

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `lpad` | `lpad(string, count, character)` | `string`: 字符串, `count`: 总长度, `character`: 填充字符 | VARCHAR | 左填充到count个字符 | `lpad('hello', 8, '0')` → `000hello` |
| `rpad` | `rpad(string, count, character)` | `string`: 字符串, `count`: 总长度, `character`: 填充字符 | VARCHAR | 右填充到count个字符 | `rpad('hello', 8, '0')` → `hello000` |
| `ltrim` | `ltrim(string[, characters])` | `string`: 字符串, `characters`: 要删除的字符(默认空格) | VARCHAR | 从左侧删除指定字符 | `ltrim('  hello  ')` → `hello  ` |
| `rtrim` | `rtrim(string[, characters])` | `string`: 字符串, `characters`: 要删除的字符(默认空格) | VARCHAR | 从右侧删除指定字符 | `rtrim('  hello  ')` → `  hello` |
| `trim` | `trim(string[, characters])` | `string`: 字符串, `characters`: 要删除的字符(默认空格) | VARCHAR | 从两端删除指定字符 | `trim('  hello  ')` → `hello` |

### 分割与连接

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `concat` | `concat(value, ...)` | 多个字符串或列表 | 与输入相同 | 连接多个值，跳过NULL | `concat('Hello', ' ', 'World')` → `Hello World` |
| `concat_ws` | `concat_ws(separator, string, ...)` | `separator`: 分隔符, 多个字符串 | VARCHAR | 用分隔符连接，跳过NULL | `concat_ws('-', 'a', 'b', 'c')` → `a-b-c` |
| `string_split` | `string_split(string, separator)` | `string`: 字符串, `separator`: 分隔符 | LIST | 按分隔符分割字符串 | `string_split('a,b,c', ',')` → `['a', 'b', 'c']` |
| `split_part` | `split_part(string, separator, index)` | `string`: 字符串, `separator`: 分隔符, `index`: 位置(1-based) | VARCHAR | 返回指定位置的分割部分 | `split_part('a,b,c', ',', 2)` → `b` |
| `string_split_regex` | `string_split_regex(string, regex[, options])` | `string`: 字符串, `regex`: 正则表达式, `options`: 可选选项 | LIST | 按正则分割字符串 | `string_split_regex('a1b2c', '[0-9]')` |

### 长度与测量

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `length` | `length(string)` | `string`: 字符串 | INTEGER | 字符数 | `length('DuckDB')` → `6` |
| `strlen` | `strlen(string)` | `string`: 字符串 | INTEGER | 字节数 | `strlen('你好')` → `6` |
| `bit_length` | `bit_length(string)` | `string`: 字符串 | INTEGER | 位数 | `bit_length('A')` → `8` |
| `length_grapheme` | `length_grapheme(string)` | `string`: 字符串 | INTEGER | 字素簇数量 | `length_grapheme('👨‍👩‍👧‍👦')` → `1` |
| `octet_length` | `octet_length(string)` | `string`: 字符串 | INTEGER | 字节数 | `octet_length('hello')` → `5` |

### 正则表达式

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `regexp_matches` | `regexp_matches(string, regex[, options])` | `string`: 字符串, `regex`: 正则表达式, `options`: 可选选项 | BOOLEAN | 检查是否包含正则匹配 | `regexp_matches('hello', 'l+')` → `true` |
| `regexp_full_match` | `regexp_full_match(string, regex[, options])` | 同上 | BOOLEAN | 检查整个字符串是否匹配 | `regexp_full_match('hello', 'h.*o')` → `true` |
| `regexp_extract` | `regexp_extract(string, regex[, group][, options])` | `string`: 字符串, `regex`: 正则, `group`: 捕获组编号 | VARCHAR | 提取正则捕获组 | `regexp_extract('abc123', '[0-9]+')` → `123` |
| `regexp_extract_all` | `regexp_extract_all(string, regex[, group][, options])` | 同上 | LIST | 返回所有非重叠匹配 | `regexp_extract_all('a1b2c3', '[0-9]')` → `['1', '2', '3']` |
| `regexp_replace` | `regexp_replace(string, regex, replacement[, options])` | `string`: 字符串, `regex`: 正则, `replacement`: 替换字符串 | VARCHAR | 替换正则匹配 | `regexp_replace('hello', 'l', 'L')` → `heLlo` |
| `regexp_escape` | `regexp_escape(string)` | `string`: 字符串 | VARCHAR | 转义正则特殊字符 | `regexp_escape('a.b')` → `a\\.b` |

### 编码与哈希

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `hex` | `hex(string)` | `string`: 字符串或blob | VARCHAR | 十六进制表示 | `hex('AB')` → `4142` |
| `bin` | `bin(string)` | `string`: 字符串 | VARCHAR | 二进制表示 | `bin('A')` → `01000001` |
| `to_base64` | `to_base64(blob)` | `blob`: 二进制数据 | VARCHAR | Base64编码 | `to_base64('hello'::BLOB)` |
| `from_base64` | `from_base64(string)` | `string`: Base64字符串 | BLOB | Base64解码 | `from_base64('aGVsbG8=')` |
| `md5` | `md5(string)` | `string`: 字符串 | VARCHAR(32) | MD5哈希 | `md5('abc')` |
| `sha1` | `sha1(string)` | `string`: 字符串 | VARCHAR(40) | SHA-1哈希 | `sha1('abc')` |
| `sha256` | `sha256(string)` | `string`: 字符串 | VARCHAR(64) | SHA-256哈希 | `sha256('abc')` |

### 其他字符串函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `replace` | `replace(string, source, target)` | `string`: 字符串, `source`: 被替换子串, `target`: 替换字符串 | VARCHAR | 替换所有出现的子串 | `replace('hello', 'l', 'L')` → `heLLo` |
| `translate` | `translate(string, from, to)` | `string`: 字符串, `from`: 源字符集, `to`: 目标字符集 | VARCHAR | 逐字符替换 | `translate('hello', 'el', 'ip')` → `hippo` |
| `repeat` | `repeat(string, count)` | `string`: 字符串, `count`: 重复次数 | VARCHAR | 重复字符串 | `repeat('ab', 3)` → `ababab` |
| `reverse` | `reverse(string)` | `string`: 字符串 | VARCHAR | 反转字符串 | `reverse('hello')` → `olleh` |
| `strip_accents` | `strip_accents(string)` | `string`: 字符串 | VARCHAR | 删除重音符号 | `strip_accents('café')` → `cafe` |
| `chr` | `chr(code_point)` | `code_point`: Unicode码点 | VARCHAR | 从码点返回字符 | `chr(65)` → `A` |
| `ascii` | `ascii(string)` | `string`: 字符串 | INTEGER | 第一个字符的Unicode码点 | `ascii('A')` → `65` |
| `unicode` | `unicode(string)` | `string`: 字符串 | INTEGER | 同ascii | `unicode('A')` → `65` |
| `format` | `format(format, ...)` | `format`: 格式字符串, 参数 | VARCHAR | fmt语法格式化 | `format('Hello {}', 'World')` |
| `printf` | `printf(format, ...)` | `format`: 格式字符串, 参数 | VARCHAR | printf语法格式化 | `printf('Hello %s', 'World')` |
| `url_encode` | `url_encode(string)` | `string`: 字符串 | VARCHAR | URL编码 | `url_encode('hello world')` |
| `url_decode` | `url_decode(string)` | `string`: URL编码字符串 | VARCHAR | URL解码 | `url_decode('hello%20world')` |

**别名**: `substr` → `substring`, `char_length` / `character_length` → `length`

---

## 日期函数

### 日期操作符

| 操作符 | 描述 | 示例 | 结果 |
|--------|------|------|------|
| `+` | 添加天数（整数）或间隔 | `DATE '1992-03-22' + 5` | `1992-03-27` |
| `+` | 添加间隔 | `DATE '1992-03-22' + INTERVAL 5 DAY` | `1992-03-27 00:00:00` |
| `-` | 日期相减（返回天数） | `DATE '1992-03-27' - DATE '1992-03-22'` | `5` |
| `-` | 减去间隔 | `DATE '1992-03-27' - INTERVAL 5 DAY` | `1992-03-22` |

### 日期函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `date_add` | `date_add(date, interval)` | `date`: 日期, `interval`: 间隔 | DATETIME | 添加间隔到日期 | `date_add(DATE '1992-09-15', INTERVAL 2 MONTH)` → `1992-11-15` |
| `date_diff` | `date_diff(part, startdate, enddate)` | `part`: 日期部分, `startdate`: 开始日期, `enddate`: 结束日期 | INTEGER | 返回两个日期之间的part边界数 | `date_diff('month', DATE '1992-09-15', DATE '1992-11-14')` → `2` |
| `date_part` | `date_part(part, date)` | `part`: 日期部分, `date`: 日期 | INTEGER | 获取日期的子字段 | `date_part('year', DATE '1992-09-20')` → `1992` |
| `date_sub` | `date_sub(part, startdate, enddate)` | 同date_diff | INTEGER | 返回有符号间隔长度 | `date_sub('month', DATE '1992-09-15', DATE '1992-11-14')` → `1` |
| `date_trunc` | `date_trunc(part, date)` | `part`: 精度, `date`: 日期 | DATE | 截断到指定精度 | `date_trunc('month', DATE '1992-03-07')` → `1992-03-01` |
| `dayname` | `dayname(date)` | `date`: 日期 | VARCHAR | 返回星期名称（英文） | `dayname(DATE '1992-09-20')` → `Sunday` |
| `extract` | `extract(part FROM date)` | `part`: 日期部分, `date`: 日期 | INTEGER | 从日期提取子字段 | `extract('year' FROM DATE '1992-09-20')` → `1992` |
| `isfinite` | `isfinite(date)` | `date`: 日期 | BOOLEAN | 检查日期是否有限 | `isfinite(DATE '1992-03-07')` → `true` |
| `isinf` | `isinf(date)` | `date`: 日期 | BOOLEAN | 检查日期是否无限 | `isinf(DATE '-infinity')` → `true` |
| `julian` | `julian(date)` | `date`: 日期 | DOUBLE | 提取儒略日 | `julian(DATE '1992-09-20')` → `2448886.0` |
| `last_day` | `last_day(date)` | `date`: 日期 | DATE | 返回月份的最后一天 | `last_day(DATE '1992-09-20')` → `1992-09-30` |
| `make_date` | `make_date(year, month, day)` | `year`: 年, `month`: 月, `day`: 日 | DATE | 从指定部分创建日期 | `make_date(1992, 9, 20)` → `1992-09-20` |
| `monthname` | `monthname(date)` | `date`: 日期 | VARCHAR | 返回月份名称（英文） | `monthname(DATE '1992-09-20')` → `September` |
| `strftime` | `strftime(date, format)` | `date`: 日期, `format`: 格式字符串 | VARCHAR | 按格式转换日期为字符串 | `strftime(DATE '1992-01-01', '%Y-%m-%d')` → `1992-01-01` |
| `time_bucket` | `time_bucket(bucket_width, date[, offset])` | `bucket_width`: 桶宽度, `date`: 日期, `offset`: 偏移量 | DATE | 截断到指定宽度的网格 | `time_bucket(INTERVAL '2 months', DATE '1992-04-20')` |
| `today` | `today()` | 无参数 | DATE | 当前日期（本地时区） | `today()` |
| `greatest` | `greatest(date, date)` | 两个日期 | DATE | 返回较晚的日期 | `greatest(DATE '1992-09-20', DATE '1992-03-07')` |
| `least` | `least(date, date)` | 两个日期 | DATE | 返回较早的日期 | `least(DATE '1992-09-20', DATE '1992-03-07')` |

**别名**: `datediff` → `date_diff`, `datepart` → `date_part`, `datesub` → `date_sub`, `datetrunc` → `date_trunc`, `current_date` → `today`

### 有效的日期部分

`century`, `day`, `decade`, `epoch`, `era`, `hour`, `isodow`, `isoyear`, `julian`, `microseconds`, `millennium`, `milliseconds`, `minute`, `month`, `quarter`, `second`, `timezone`, `timezone_hour`, `timezone_minute`, `week`, `year`, `dayofweek`, `dayofyear`

---

## 时间函数

### 时间操作符

| 操作符 | 描述 | 示例 | 结果 |
|--------|------|------|------|
| `+` | 添加间隔 | `TIME '01:02:03' + INTERVAL 5 HOUR` | `06:02:03` |
| `-` | 减去间隔 | `TIME '06:02:03' - INTERVAL 5 HOUR` | `01:02:03` |

### 时间函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `date_diff` | `date_diff(part, starttime, endtime)` | `part`: 时间部分, `starttime`: 开始时间, `endtime`: 结束时间 | INTEGER | 返回两个时间之间的part边界数 | `date_diff('hour', TIME '01:02:03', TIME '06:01:03')` → `5` |
| `date_part` | `date_part(part, time)` | `part`: 时间部分, `time`: 时间 | INTEGER | 获取时间的子字段 | `date_part('minute', TIME '14:21:13')` → `21` |
| `date_sub` | `date_sub(part, starttime, endtime)` | 同上 | INTEGER | 返回有符号间隔长度 | `date_sub('hour', TIME '01:02:03', TIME '06:01:03')` → `4` |
| `extract` | `extract(part FROM time)` | `part`: 时间部分, `time`: 时间 | INTEGER | 从时间提取子字段 | `extract('hour' FROM TIME '14:21:13')` → `14` |
| `get_current_time` | `get_current_time()` | 无参数 | TIMETZ | 当前时间（本地时区） | `get_current_time()` |
| `make_time` | `make_time(hour, minute, second)` | `hour`: 小时, `minute`: 分钟, `second`: 秒 | TIME | 从指定部分创建时间 | `make_time(13, 34, 27.123456)` → `13:34:27.123456` |

**别名**: `datediff` → `date_diff`, `datepart` → `date_part`, `datesub` → `date_sub`, `current_time` → `get_current_time`

**有效的时间部分**: `epoch`, `hours`, `minutes`, `seconds`, `milliseconds`, `microseconds`

---

## 时间戳函数

### 时间戳操作符

| 操作符 | 描述 | 示例 | 结果 |
|--------|------|------|------|
| `+` | 添加间隔 | `TIMESTAMP '1992-03-22 01:02:03' + INTERVAL 5 DAY` | `1992-03-27 01:02:03` |
| `-` | 时间戳相减 | `TIMESTAMP '1992-03-27' - TIMESTAMP '1992-03-22'` | `5 days` |
| `-` | 减去间隔 | `TIMESTAMP '1992-03-27 01:02:03' - INTERVAL 5 DAY` | `1992-03-22 01:02:03` |

### 时间戳函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `age` | `age(timestamp, timestamp)` | 两个时间戳 | INTERVAL | 返回两个时间戳之间的时间差 | `age(TIMESTAMP '2001-04-10', TIMESTAMP '1992-09-20')` → `8 years 6 months 20 days` |
| `age` | `age(timestamp)` | 一个时间戳 | INTERVAL | 从当前日期减去时间戳 | `age(TIMESTAMP '1992-09-20')` |
| `ago` | `ago(interval)` | `interval`: 间隔 | TIMESTAMP | 从当前时间戳减去间隔 | `ago(INTERVAL 1 HOUR)` |
| `century` | `century(timestamp)` | `timestamp`: 时间戳 | INTEGER | 提取世纪 | `century(TIMESTAMP '1992-03-22')` → `20` |
| `current_localtimestamp` | `current_localtimestamp()` | 无参数 | TIMESTAMP | 当前时间戳（事务开始时） | `current_localtimestamp()` |
| `date_diff` | `date_diff(part, start, end)` | `part`: 部分, `start`: 开始, `end`: 结束 | INTEGER | 返回两个时间戳之间的part边界数 | `date_diff('hour', TIMESTAMP '1992-09-30 23:59:59', TIMESTAMP '1992-10-01 01:58:00')` → `2` |
| `date_part` | `date_part(part, timestamp)` | `part`: 部分, `timestamp`: 时间戳 | INTEGER | 获取子字段 | `date_part('minute', TIMESTAMP '1992-09-20 20:38:40')` → `38` |
| `date_part` | `date_part([part, ...], timestamp)` | 多个部分, 时间戳 | STRUCT | 获取多个子字段作为结构体 | `date_part(['year', 'month'], TIMESTAMP '1992-09-20')` |
| `date_sub` | `date_sub(part, start, end)` | 同上 | INTEGER | 返回有符号间隔长度 | `date_sub('hour', TIMESTAMP '1992-09-30 23:59:59', TIMESTAMP '1992-10-01 01:58:00')` → `1` |
| `date_trunc` | `date_trunc(part, timestamp)` | `part`: 精度, `timestamp`: 时间戳 | TIMESTAMP | 截断到指定精度 | `date_trunc('hour', TIMESTAMP '1992-09-20 20:38:40')` → `1992-09-20 20:00:00` |
| `dayname` | `dayname(timestamp)` | `timestamp`: 时间戳 | VARCHAR | 返回星期名称（英文） | `dayname(TIMESTAMP '1992-03-22')` → `Sunday` |
| `epoch` | `epoch(timestamp)` | `timestamp`: 时间戳 | DOUBLE | 返回自纪元以来的秒数 | `epoch(TIMESTAMP '2022-11-07 08:43:04')` |
| `epoch_ms` | `epoch_ms(timestamp)` | `timestamp`: 时间戳 | BIGINT | 返回自纪元以来的毫秒数 | `epoch_ms(TIMESTAMP '2021-08-03 11:59:44.123456')` |
| `epoch_us` | `epoch_us(timestamp)` | `timestamp`: 时间戳 | BIGINT | 返回自纪元以来的微秒数 | `epoch_us(TIMESTAMP '2021-08-03 11:59:44.123456')` |
| `epoch_ns` | `epoch_ns(timestamp)` | `timestamp`: 时间戳 | BIGINT | 返回自纪元以来的纳秒数 | `epoch_ns(TIMESTAMP '2021-08-03 11:59:44.123456')` |
| `extract` | `extract(part FROM timestamp)` | `part`: 部分, `timestamp`: 时间戳 | INTEGER | 从时间戳提取子字段 | `extract('hour' FROM TIMESTAMP '1992-09-20 20:38:48')` → `20` |
| `isfinite` | `isfinite(timestamp)` | `timestamp`: 时间戳 | BOOLEAN | 检查时间戳是否有限 | `isfinite(TIMESTAMP '1992-03-07')` → `true` |
| `isinf` | `isinf(timestamp)` | `timestamp`: 时间戳 | BOOLEAN | 检查时间戳是否无限 | `isinf(TIMESTAMP '-infinity')` → `true` |
| `julian` | `julian(timestamp)` | `timestamp`: 时间戳 | DOUBLE | 提取儒略日 | `julian(TIMESTAMP '1992-03-22 01:02:03')` |
| `last_day` | `last_day(timestamp)` | `timestamp`: 时间戳 | DATE | 返回月份的最后一天 | `last_day(TIMESTAMP '1992-03-22 01:02:03')` → `1992-03-31` |
| `make_timestamp` | `make_timestamp(year, month, day, hour, minute, second)` | 年、月、日、时、分、秒 | TIMESTAMP | 从指定部分创建时间戳 | `make_timestamp(1992, 9, 20, 13, 34, 27.123456)` |
| `make_timestamp` | `make_timestamp(microseconds)` | 微秒 | TIMESTAMP | 从微秒创建时间戳 | `make_timestamp(1667810584123456)` |
| `make_timestamp_ms` | `make_timestamp_ms(milliseconds)` | 毫秒 | TIMESTAMP | 从毫秒创建时间戳 | `make_timestamp_ms(1667810584123)` |
| `make_timestamp_ns` | `make_timestamp_ns(nanoseconds)` | 纳秒 | TIMESTAMP | 从纳秒创建时间戳 | `make_timestamp_ns(1667810584123456789)` |
| `monthname` | `monthname(timestamp)` | `timestamp`: 时间戳 | VARCHAR | 返回月份名称（英文） | `monthname(TIMESTAMP '1992-09-20')` → `September` |
| `strftime` | `strftime(timestamp, format)` | `timestamp`: 时间戳, `format`: 格式字符串 | VARCHAR | 按格式转换为字符串 | `strftime(TIMESTAMP '1992-01-01 20:38:40', '%Y-%m-%d %H:%M:%S')` |
| `strptime` | `strptime(text, format)` | `text`: 字符串, `format`: 格式字符串 | TIMESTAMP | 按格式解析为时间戳 | `strptime('1992-01-01', '%Y-%m-%d')` |
| `strptime` | `strptime(text, format-list)` | `text`: 字符串, `format-list`: 格式字符串列表 | TIMESTAMP | 尝试多个格式直到成功 | `strptime('4/15/2023', ['%d/%m/%Y', '%m/%d/%Y'])` |
| `try_strptime` | `try_strptime(text, format)` | 同上 | TIMESTAMP | 解析失败时返回NULL | `try_strptime('invalid', '%Y-%m-%d')` → `NULL` |
| `time_bucket` | `time_bucket(bucket_width, timestamp[, offset])` | `bucket_width`: 桶宽度, `timestamp`: 时间戳, `offset`: 偏移量 | TIMESTAMP | 截断到指定宽度的网格 | `time_bucket(INTERVAL '10 minutes', TIMESTAMP '1992-04-20 15:26:00')` |

### 时间戳表函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `generate_series` | `generate_series(start, stop, step)` | `start`: 开始时间戳, `stop`: 结束时间戳, `step`: 间隔 | TABLE | 生成时间戳序列（闭区间） | `generate_series(TIMESTAMP '2001-04-10', TIMESTAMP '2001-04-11', INTERVAL 30 MINUTE)` |
| `range` | `range(start, stop, step)` | 同上 | TABLE | 生成时间戳序列（左闭右开） | `range(TIMESTAMP '2001-04-10', TIMESTAMP '2001-04-11', INTERVAL 30 MINUTE)` |

---

## 时间间隔函数

### 间隔操作符

| 操作符 | 描述 | 示例 | 结果 |
|--------|------|------|------|
| `+` | 间隔相加 | `INTERVAL 1 HOUR + INTERVAL 5 HOUR` | `INTERVAL 6 HOUR` |
| `+` | 添加到日期 | `DATE '1992-03-22' + INTERVAL 5 DAY` | `1992-03-27 00:00:00` |
| `-` | 间隔相减 | `INTERVAL 5 HOUR - INTERVAL 1 HOUR` | `INTERVAL 4 HOUR` |

### 间隔函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `date_part` | `date_part(part, interval)` | `part`: 部分, `interval`: 间隔 | INTEGER | 提取日期部分组件 | `date_part('year', INTERVAL '14 months')` → `1` |
| `epoch` | `epoch(interval)` | `interval`: 间隔 | DOUBLE | 获取总秒数 | `epoch(INTERVAL 5 HOUR)` → `18000.0` |
| `to_centuries` | `to_centuries(integer)` | 整数 | INTERVAL | 构造世纪间隔 | `to_centuries(5)` → `INTERVAL 500 YEAR` |
| `to_days` | `to_days(integer)` | 整数 | INTERVAL | 构造天间隔 | `to_days(5)` → `INTERVAL 5 DAY` |
| `to_decades` | `to_decades(integer)` | 整数 | INTERVAL | 构造十年间隔 | `to_decades(5)` → `INTERVAL 50 YEAR` |
| `to_hours` | `to_hours(integer)` | 整数 | INTERVAL | 构造小时间隔 | `to_hours(5)` → `INTERVAL 5 HOUR` |
| `to_microseconds` | `to_microseconds(integer)` | 整数 | INTERVAL | 构造微秒间隔 | `to_microseconds(5)` → `INTERVAL 5 MICROSECOND` |
| `to_millennia` | `to_millennia(integer)` | 整数 | INTERVAL | 构造千年间隔 | `to_millennia(5)` → `INTERVAL 5000 YEAR` |
| `to_milliseconds` | `to_milliseconds(integer)` | 整数 | INTERVAL | 构造毫秒间隔 | `to_milliseconds(5)` → `INTERVAL 5 MILLISECOND` |
| `to_minutes` | `to_minutes(integer)` | 整数 | INTERVAL | 构造分钟间隔 | `to_minutes(5)` → `INTERVAL 5 MINUTE` |
| `to_months` | `to_months(integer)` | 整数 | INTERVAL | 构造月间隔 | `to_months(5)` → `INTERVAL 5 MONTH` |
| `to_quarters` | `to_quarters(integer)` | 整数 | INTERVAL | 构造季度间隔 | `to_quarters(5)` → `INTERVAL 1 YEAR 3 MONTHS` |
| `to_seconds` | `to_seconds(integer)` | 整数 | INTERVAL | 构造秒间隔 | `to_seconds(5)` → `INTERVAL 5 SECOND` |
| `to_weeks` | `to_weeks(integer)` | 整数 | INTERVAL | 构造周间隔 | `to_weeks(5)` → `INTERVAL 35 DAY` |
| `to_years` | `to_years(integer)` | 整数 | INTERVAL | 构造年间隔 | `to_years(5)` → `INTERVAL 5 YEAR` |

---

## 窗口函数

### 通用窗口函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 |
|------|------|----------|----------|------|
| `row_number` | `row_number() OVER ([PARTITION BY ...] [ORDER BY ...])` | 窗口子句 | BIGINT | 分区内的行号（从1开始） |
| `rank` | `rank() OVER ([PARTITION BY ...] ORDER BY ...)` | 窗口子句 | BIGINT | 有间隙的排名 |
| `dense_rank` | `dense_rank() OVER ([PARTITION BY ...] ORDER BY ...)` | 窗口子句 | BIGINT | 无间隙的排名 |
| `percent_rank` | `percent_rank() OVER ([PARTITION BY ...] ORDER BY ...)` | 窗口子句 | DOUBLE | 相对排名：(rank() - 1) / (总行数 - 1) |
| `cume_dist` | `cume_dist() OVER ([PARTITION BY ...] ORDER BY ...)` | 窗口子句 | DOUBLE | 累积分布 |
| `ntile` | `ntile(num_buckets) OVER ([PARTITION BY ...] ORDER BY ...)` | `num_buckets`: 桶数 | BIGINT | 将分区划分为指定数量的桶 |
| `lag` | `lag(expr[, offset[, default]]) OVER ([PARTITION BY ...] ORDER BY ...)` | `expr`: 表达式, `offset`: 偏移量(默认1), `default`: 默认值 | 与expr相同 | 当前行之前offset行的expr值 |
| `lead` | `lead(expr[, offset[, default]]) OVER ([PARTITION BY ...] ORDER BY ...)` | 同上 | 与expr相同 | 当前行之后offset行的expr值 |
| `first_value` | `first_value(expr) OVER ([PARTITION BY ...] ORDER BY ... [frame_clause])` | `expr`: 表达式 | 与expr相同 | 窗口框架第一行的expr值 |
| `last_value` | `last_value(expr) OVER ([PARTITION BY ...] ORDER BY ... [frame_clause])` | `expr`: 表达式 | 与expr相同 | 窗口框架最后一行的expr值 |
| `nth_value` | `nth_value(expr, n) OVER ([PARTITION BY ...] ORDER BY ... [frame_clause])` | `expr`: 表达式, `n`: 位置 | 与expr相同 | 窗口框架第n行的expr值 |
| `fill` | `fill(expr) OVER (ORDER BY ...)` | `expr`: 表达式 | 与expr相同 | 使用线性插值填充NULL值 |

### 窗口框架语法

```sql
ROWS|RANGE|GROUPS BETWEEN 
    UNBOUNDED PRECEDING | n PRECEDING | CURRENT ROW | n FOLLOWING | UNBOUNDED FOLLOWING
AND 
    UNBOUNDED PRECEDING | n PRECEDING | CURRENT ROW | n FOLLOWING | UNBOUNDED FOLLOWING
```

### 示例

```sql
-- 行号
SELECT name, score, 
       row_number() OVER (ORDER BY score DESC) as rank
FROM data;

-- 分区排名
SELECT category, name, score,
       rank() OVER (PARTITION BY category ORDER BY score DESC) as category_rank
FROM data;

-- 移动平均
SELECT date, value,
       avg(value) OVER (ORDER BY date ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) as moving_avg
FROM data;
```

---

## 列表函数

### 列表操作符

| 操作符 | 描述 | 示例 | 结果 |
|--------|------|------|------|
| `list[index]` | 提取元素（1-based） | `[4, 5, 6][3]` | `6` |
| `list[begin:end:step]` | 切片 | `[4, 5, 6][2:]` | `[5, 6]` |
| `\|\|` | 连接列表 | `[1, 2] \|\| [3, 4]` | `[1, 2, 3, 4]` |
| `&&` | 是否有共同元素 | `[1, 2] && [2, 3]` | `true` |
| `<@` / `@>` | 是否全部包含 | `[1, 2] <@ [1, 2, 3]` | `true` |
| `<->` | 欧氏距离 | `[1, 0] <-> [0, 1]` | `1.414...` |
| `<=>` | 余弦距离 | `[1, 1] <=> [1, 0]` | `0.29...` |

### 列表创建与生成

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `list_value` | `list_value(arg, ...)` | 任意多个参数 | LIST | 创建包含参数值的列表 | `list_value(1, 2, 3)` → `[1, 2, 3]` |
| `range` | `range(start[, stop][, step])` | `start`: 起始, `stop`: 结束, `step`: 步长 | LIST | 生成序列（左闭右开） | `range(1, 5)` → `[1, 2, 3, 4]` |
| `generate_series` | `generate_series(start[, stop][, step])` | 同上 | LIST | 生成序列（闭区间） | `generate_series(1, 5)` → `[1, 2, 3, 4, 5]` |

### 列表提取与切片

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `list_extract` | `list_extract(list, index)` | `list`: 列表, `index`: 位置(1-based) | 元素类型 | 提取指定位置元素 | `list_extract([1, 2, 3], 2)` → `2` |
| `list_slice` | `list_slice(list, begin, end[, step])` | `list`: 列表, `begin`: 起始, `end`: 结束, `step`: 步长 | LIST | 提取子列表 | `list_slice([1, 2, 3, 4, 5], 2, 4)` → `[2, 3, 4]` |
| `list_position` | `list_position(list, element)` | `list`: 列表, `element`: 元素 | INTEGER | 返回元素索引（未找到返回NULL） | `list_position([1, 2, 3], 2)` → `2` |
| `length` | `length(list)` | `list`: 列表 | INTEGER | 返回列表长度 | `length([1, 2, 3])` → `3` |

### 列表修改

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `list_append` | `list_append(list, element)` | `list`: 列表, `element`: 元素 | LIST | 追加元素到列表末尾 | `list_append([1, 2], 3)` → `[1, 2, 3]` |
| `list_prepend` | `list_prepend(element, list)` | `element`: 元素, `list`: 列表 | LIST | 在列表开头添加元素 | `list_prepend(0, [1, 2])` → `[0, 1, 2]` |
| `list_concat` | `list_concat(list_1, ..., list_n)` | 多个列表 | LIST | 连接多个列表 | `list_concat([1], [2], [3])` → `[1, 2, 3]` |
| `list_reverse` | `list_reverse(list)` | `list`: 列表 | LIST | 反转列表 | `list_reverse([1, 2, 3])` → `[3, 2, 1]` |
| `list_resize` | `list_resize(list, size[, value])` | `list`: 列表, `size`: 大小, `value`: 填充值 | LIST | 调整列表大小 | `list_resize([1, 2], 4, 0)` → `[1, 2, 0, 0]` |
| `array_pop_back` | `array_pop_back(list)` | `list`: 列表 | LIST | 返回去掉最后一个元素的列表 | `array_pop_back([1, 2, 3])` → `[1, 2]` |
| `array_pop_front` | `array_pop_front(list)` | `list`: 列表 | LIST | 返回去掉第一个元素的列表 | `array_pop_front([1, 2, 3])` → `[2, 3]` |

### 列表排序

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `list_sort` | `list_sort(list[, col1][, col2])` | `list`: 列表, `col1`, `col2`: 排序选项 | LIST | 排序列表 | `list_sort([3, 1, 2])` → `[1, 2, 3]` |
| `list_reverse_sort` | `list_reverse_sort(list[, col1])` | 同上 | LIST | 逆序排序 | `list_reverse_sort([1, 2, 3])` → `[3, 2, 1]` |
| `list_grade_up` | `list_grade_up(list[, col1][, col2])` | 同上 | LIST | 返回排序后的索引 | `list_grade_up([3, 1, 2])` → `[2, 3, 1]` |

### 列表过滤与变换

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `list_filter` | `list_filter(list, lambda(x))` | `list`: 列表, `lambda`: 过滤函数 | LIST | 过滤列表元素 | `list_filter([1, 2, 3, 4], x -> x > 2)` → `[3, 4]` |
| `list_transform` | `list_transform(list, lambda(x))` | `list`: 列表, `lambda`: 变换函数 | LIST | 对每个元素应用函数 | `list_transform([1, 2, 3], x -> x * 2)` → `[2, 4, 6]` |
| `list_reduce` | `list_reduce(list, lambda(x, y)[, initial])` | `list`: 列表, `lambda`: 归约函数, `initial`: 初始值 | 标量 | 归约为单个值 | `list_reduce([1, 2, 3], x, y -> x + y)` → `6` |
| `list_select` | `list_select(value_list, index_list)` | `value_list`: 值列表, `index_list`: 索引列表 | LIST | 按索引选择元素 | `list_select([10, 20, 30], [1, 3])` → `[10, 30]` |
| `list_where` | `list_where(value_list, mask_list)` | `value_list`: 值列表, `mask_list`: 布尔掩码 | LIST | 按掩码过滤 | `list_where([1, 2, 3], [true, false, true])` → `[1, 3]` |

### 列表包含与集合操作

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `list_contains` | `list_contains(list, element)` | `list`: 列表, `element`: 元素 | BOOLEAN | 检查是否包含元素 | `list_contains([1, 2, 3], 2)` → `true` |
| `list_has_all` | `list_has_all(list1, list2)` | `list1`, `list2`: 列表 | BOOLEAN | list2的所有元素是否都在list1中 | `list_has_all([1, 2, 3], [1, 2])` → `true` |
| `list_has_any` | `list_has_any(list1, list2)` | `list1`, `list2`: 列表 | BOOLEAN | 两个列表是否有共同元素 | `list_has_any([1, 2], [2, 3])` → `true` |
| `list_distinct` | `list_distinct(list)` | `list`: 列表 | LIST | 去重 | `list_distinct([1, 2, 2, 3])` → `[1, 2, 3]` |
| `list_unique` | `list_unique(list)` | `list`: 列表 | INTEGER | 不重复元素计数 | `list_unique([1, 2, 2, 3])` → `3` |
| `list_intersect` | `list_intersect(list1, list2)` | `list1`, `list2`: 列表 | LIST | 交集 | `list_intersect([1, 2, 3], [2, 3, 4])` → `[2, 3]` |

### 列表聚合函数

| 函数 | 描述 | 示例 |
|------|------|------|
| `list_avg(list)` | 平均值 | `list_avg([1, 2, 3])` → `2` |
| `list_sum(list)` | 和 | `list_sum([1, 2, 3])` → `6` |
| `list_min(list)` | 最小值 | `list_min([1, 2, 3])` → `1` |
| `list_max(list)` | 最大值 | `list_max([1, 2, 3])` → `3` |
| `list_median(list)` | 中位数 | `list_median([1, 2, 3])` → `2` |
| `list_mode(list)` | 众数 | `list_mode([1, 1, 2, 3])` → `1` |
| `list_product(list)` | 乘积 | `list_product([2, 3, 4])` → `24` |
| `list_stddev_samp(list)` | 样本标准差 | - |
| `list_var_samp(list)` | 样本方差 | - |

### 列表向量函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `list_cosine_similarity` | `list_cosine_similarity(list1, list2)` | 两个等长列表 | DOUBLE | 余弦相似度 | `list_cosine_similarity([1, 0], [1, 1])` |
| `list_distance` | `list_distance(list1, list2)` | 两个等长列表 | DOUBLE | 欧氏距离 | `list_distance([1, 0], [0, 1])` → `1.414...` |
| `list_inner_product` | `list_inner_product(list1, list2)` | 两个等长列表 | DOUBLE | 内积 | `list_inner_product([1, 2], [3, 4])` → `11` |

### 其他列表函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `flatten` | `flatten(nested_list)` | `nested_list`: 嵌套列表 | LIST | 展平一层嵌套 | `flatten([[1, 2], [3, 4]])` → `[1, 2, 3, 4]` |
| `unnest` | `unnest(list)` | `list`: 列表 | TABLE | 展开列表为多行 | `unnest([1, 2, 3])` |
| `repeat` | `repeat(list, count)` | `list`: 列表, `count`: 次数 | LIST | 重复列表 | `repeat([1, 2], 3)` → `[1, 2, 1, 2, 1, 2]` |
| `list_zip` | `list_zip(list_1, ..., list_n[, truncate])` | 多个列表, `truncate`: 是否截断 | LIST | 拉链合并列表 | `list_zip([1, 2], ['a', 'b'])` → `[{1, 'a'}, {2, 'b'}]` |
| `array_to_string` | `array_to_string(list, delimiter)` | `list`: 列表, `delimiter`: 分隔符 | VARCHAR | 连接元素为字符串 | `array_to_string([1, 2, 3], '-')` → `1-2-3` |

---

## 数组函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `array_value` | `array_value(arg, ...)` | 任意多个参数 | ARRAY | 创建数组 | `array_value(1.0, 2.0, 3.0)` |
| `array_cosine_distance` | `array_cosine_distance(array1, array2)` | 两个等长数组 | FLOAT | 余弦距离 | `array_cosine_distance([1.0, 2.0], [3.0, 4.0])` |
| `array_cosine_similarity` | `array_cosine_similarity(array1, array2)` | 两个等长数组 | FLOAT | 余弦相似度 | `array_cosine_similarity([1.0, 2.0], [3.0, 4.0])` |
| `array_distance` | `array_distance(array1, array2)` | 两个等长数组 | FLOAT | 欧氏距离 | `array_distance([1.0, 2.0], [3.0, 4.0])` |
| `array_inner_product` | `array_inner_product(array1, array2)` | 两个等长数组 | FLOAT | 内积 | `array_inner_product([1.0, 2.0], [3.0, 4.0])` |
| `array_negative_inner_product` | `array_negative_inner_product(array1, array2)` | 两个等长数组 | FLOAT | 负内积 | `array_negative_inner_product([1.0, 2.0], [3.0, 4.0])` |
| `array_cross_product` | `array_cross_product(array1, array2)` | 两个长度为3的数组 | ARRAY[FLOAT] | 叉积 | `array_cross_product([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])` |

> **注意**: 所有LIST函数也适用于ARRAY类型。

---

## Map函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `map` | `map()` | 无参数 | MAP | 返回空Map | `map()` → `{}` |
| `cardinality` | `cardinality(map)` | `map`: Map | INTEGER | 返回Map大小 | `cardinality(map {'a': 1, 'b': 2})` → `2` |
| `element_at` | `element_at(map, key)` | `map`: Map, `key`: 键 | LIST | 返回键对应的值列表 | `element_at(map {'a': 1}, 'a')` → `[1]` |
| `map_extract` | `map_extract(map, key)` | 同上 | LIST | element_at的别名 | - |
| `map_extract_value` | `map_extract_value(map, key)` | `map`: Map, `key`: 键 | 值类型或NULL | 返回键对应的值或NULL | `map_extract_value(map {'a': 1}, 'a')` → `1` |
| `map[key]` | `map[key]` | 同上 | 值类型或NULL | 同上 | `map {'a': 1}['a']` → `1` |
| `map_contains` | `map_contains(map, key)` | `map`: Map, `key`: 键 | BOOLEAN | 检查是否包含键 | `map_contains(map {'a': 1}, 'a')` → `true` |
| `map_contains_value` | `map_contains_value(map, value)` | `map`: Map, `value`: 值 | BOOLEAN | 检查是否包含值 | `map_contains_value(map {'a': 1}, 1)` → `true` |
| `map_contains_entry` | `map_contains_entry(map, key, value)` | `map`: Map, `key`: 键, `value`: 值 | BOOLEAN | 检查是否包含键值对 | `map_contains_entry(map {'a': 1}, 'a', 1)` → `true` |
| `map_keys` | `map_keys(map)` | `map`: Map | LIST | 返回所有键的列表 | `map_keys(map {'a': 1, 'b': 2})` → `['a', 'b']` |
| `map_values` | `map_values(map)` | `map`: Map | LIST | 返回所有值的列表 | `map_values(map {'a': 1, 'b': 2})` → `[1, 2]` |
| `map_entries` | `map_entries(map)` | `map`: Map | LIST[STRUCT] | 返回struct(k, v)列表 | `map_entries(map {'a': 1})` → `[{'key': 'a', 'value': 1}]` |
| `map_from_entries` | `map_from_entries(entries)` | `entries`: STRUCT(k, v)数组 | MAP | 从条目创建Map | `map_from_entries([{'k': 'a', 'v': 1}])` → `{'a': 1}` |
| `map_concat` | `map_concat(map1, map2, ...)` | 多个Map | MAP | 合并多个Map（重复键取最后一个） | `map_concat(map {'a': 1}, map {'b': 2})` → `{'a': 1, 'b': 2}` |

---

## 结构体函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `row` | `row(value, ...)` | 多个值 | STRUCT | 创建无名结构体（元组） | `row(1, 'hello')` → `(1, hello)` |
| `struct_pack` | `struct_pack(name := value, ...)` | 命名参数 | STRUCT | 创建命名结构体 | `struct_pack(a := 1, b := 'hello')` → `{'a': 1, 'b': hello}` |
| `struct.entry` | `struct.entry` | 点表示法 | 字段类型 | 提取命名字段 | `({'a': 1, 'b': 2}).a` → `1` |
| `struct['entry']` | `struct['entry']` | 括号表示法 | 字段类型 | 提取命名字段 | `({'a': 1})['a']` → `1` |
| `struct[idx]` | `struct[idx]` | `idx`: 索引(1-based) | 字段类型 | 从元组提取字段 | `row(1, 2, 3)[2]` → `2` |
| `struct_extract` | `struct_extract(struct, 'entry')` | `struct`: 结构体, `'entry'`: 字段名 | 字段类型 | 提取命名字段 | `struct_extract({'a': 1}, 'a')` → `1` |
| `struct_extract` | `struct_extract(struct, idx)` | `struct`: 结构体, `idx`: 索引(1-based) | 字段类型 | 按索引提取字段 | `struct_extract(row(1, 2), 1)` → `1` |
| `struct_concat` | `struct_concat(struct1, struct2, ...)` | 多个结构体 | STRUCT | 合并多个结构体 | `struct_concat({'a': 1}, {'b': 2})` → `{'a': 1, 'b': 2}` |
| `struct_insert` | `struct_insert(struct, name := value, ...)` | 结构体和命名参数 | STRUCT | 添加字段 | `struct_insert({'a': 1}, b := 2)` → `{'a': 1, 'b': 2}` |
| `struct_update` | `struct_update(struct, name := value, ...)` | 结构体和命名参数 | STRUCT | 添加或更新字段 | `struct_update({'a': 1}, a := 2)` → `{'a': 2}` |
| `struct_contains` | `struct_contains(struct, entry)` | `struct`: 结构体, `entry`: 字段名或值 | BOOLEAN | 检查是否包含字段 | `struct_contains({'a': 1}, 'a')` → `true` |
| `struct_position` | `struct_position(struct, entry)` | 同上 | INTEGER | 返回字段索引 | `struct_position({'a': 1, 'b': 2}, 'b')` → `2` |

**别名**: `struct_has` → `struct_contains`, `struct_indexof` → `struct_position`

---

## Union函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `union_value` | `union_value(tag := value)` | 命名参数（tag成为变量名） | UNION | 创建单成员Union | `union_value(k := 'hello')` |
| `union.tag` | `union.tag` | 点表示法 | 值类型 | 提取指定标签的值 | `(union_value(k := 'hello')).k` |
| `union_extract` | `union_extract(union, 'tag')` | `union`: Union值, `'tag'`: 标签名 | 值类型或NULL | 提取指定标签的值 | `union_extract(s, 'k')` |
| `union_tag` | `union_tag(union)` | `union`: Union值 | ENUM | 获取当前选中的标签 | `union_tag(union_value(k := 'foo'))` → `'k'` |

---

## 位运算函数

### 位运算操作符

| 操作符 | 描述 | 示例 | 结果 |
|--------|------|------|------|
| `&` | 按位与 | `'10101'::BITSTRING & '10001'::BITSTRING` | `10001` |
| `\|` | 按位或 | `'1011'::BITSTRING \| '0001'::BITSTRING` | `1011` |
| `xor` | 按位异或 | `xor('101'::BITSTRING, '001'::BITSTRING)` | `100` |
| `~` | 按位取反 | `~('101'::BITSTRING)` | `010` |
| `<<` | 左移 | `'1001011'::BITSTRING << 3` | `1011000` |
| `>>` | 右移 | `'1001011'::BITSTRING >> 3` | `0001001` |

### 位串标量函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `bit_count` | `bit_count(bitstring)` | `bitstring`: 位串 | INTEGER | 返回设置的位数 | `bit_count('1101011'::BITSTRING)` → `5` |
| `bit_length` | `bit_length(bitstring)` | `bitstring`: 位串 | INTEGER | 返回位数 | `bit_length('1101011'::BITSTRING)` → `7` |
| `bit_position` | `bit_position(substring, bitstring)` | `substring`: 子位串, `bitstring`: 位串 | INTEGER | 返回子串首次出现的索引（1-based） | `bit_position('010'::BITSTRING, '1110101'::BITSTRING)` → `4` |
| `bitstring` | `bitstring(bitstring, length)` | `bitstring`: 位串, `length`: 长度 | BITSTRING | 返回指定长度的位串 | `bitstring('1010'::BITSTRING, 7)` → `0001010` |
| `get_bit` | `get_bit(bitstring, index)` | `bitstring`: 位串, `index`: 索引(0-based) | INTEGER | 提取第n位 | `get_bit('0110010'::BITSTRING, 2)` → `1` |
| `set_bit` | `set_bit(bitstring, index, new_value)` | `bitstring`: 位串, `index`: 索引, `new_value`: 新值(0或1) | BITSTRING | 设置第n位 | `set_bit('0110010'::BITSTRING, 2, 0)` → `0100010` |
| `octet_length` | `octet_length(bitstring)` | `bitstring`: 位串 | INTEGER | 返回字节数 | `octet_length('1101011'::BITSTRING)` → `1` |

### 位串聚合函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 |
|------|------|----------|----------|------|
| `bit_and` | `bit_and(arg)` | `arg`: 整数列 | INTEGER | 所有值的按位与 |
| `bit_or` | `bit_or(arg)` | `arg`: 整数列 | INTEGER | 所有值的按位或 |
| `bit_xor` | `bit_xor(arg)` | `arg`: 整数列 | INTEGER | 所有值的按位异或 |
| `bitstring_agg` | `bitstring_agg(arg)` 或 `bitstring_agg(arg, min, max)` | `arg`: 整数列, `min`, `max`: 范围 | BITSTRING | 返回每个位置对应的位串 |

---

## Blob函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `\|\|` | `blob1 \|\| blob2` | 两个blob | BLOB | 连接blob | `'hello'::BLOB \|\| 'world'::BLOB` |
| `encode` | `encode(string)` | `string`: 字符串 | BLOB | 字符串转BLOB | `encode('hello')` |
| `decode` | `decode(blob)` | `blob`: BLOB | VARCHAR | BLOB转VARCHAR | `decode('hello'::BLOB)` |
| `to_base64` | `to_base64(blob)` | `blob`: BLOB | VARCHAR | Base64编码 | `to_base64('hello'::BLOB)` |
| `from_base64` | `from_base64(string)` | `string`: Base64字符串 | BLOB | Base64解码 | `from_base64('aGVsbG8=')` |
| `hex` | `hex(blob)` | `blob`: BLOB | VARCHAR | 十六进制编码 | `hex('hello'::BLOB)` → `68656C6C6F` |
| `unhex` | `unhex(string)` | `string`: 十六进制字符串 | BLOB | 十六进制解码 | `unhex('68656C6C6F')` |
| `unbin` | `unbin(string)` | `string`: 二进制字符串 | BLOB | 二进制解码 | `unbin('01101000')` |
| `md5` | `md5(blob)` | `blob`: BLOB | VARCHAR(32) | MD5哈希 | `md5('hello'::BLOB)` |
| `sha1` | `sha1(blob)` | `blob`: BLOB | VARCHAR(40) | SHA-1哈希 | `sha1('hello'::BLOB)` |
| `sha256` | `sha256(blob)` | `blob`: BLOB | VARCHAR(64) | SHA-256哈希 | `sha256('hello'::BLOB)` |
| `octet_length` | `octet_length(blob)` | `blob`: BLOB | INTEGER | 字节数 | `octet_length('hello'::BLOB)` → `5` |
| `read_blob` | `read_blob(source)` | `source`: 文件路径或glob | BLOB | 读取文件为BLOB | `read_blob('data.bin')` |
| `repeat` | `repeat(blob, count)` | `blob`: BLOB, `count`: 次数 | BLOB | 重复blob | `repeat('ab'::BLOB, 3)` |

**别名**: `base64` → `to_base64`, `to_hex` → `hex`, `from_binary` → `unbin`, `from_hex` → `unhex`

---

## 枚举函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `enum_code` | `enum_code(enum_value)` | `enum_value`: 枚举值 | INTEGER | 返回枚举值的数值 | `enum_code('happy'::mood)` → `2` |
| `enum_first` | `enum_first(enum)` | `enum`: 枚举类型（值被忽略） | ENUM | 返回枚举类型的第一个值 | `enum_first(NULL::mood)` → `sad` |
| `enum_last` | `enum_last(enum)` | `enum`: 枚举类型（值被忽略） | ENUM | 返回枚举类型的最后一个值 | `enum_last(NULL::mood)` → `anxious` |
| `enum_range` | `enum_range(enum)` | `enum`: 枚举类型（值被忽略） | ARRAY | 返回枚举类型的所有值 | `enum_range(NULL::mood)` → `[sad, ok, happy, anxious]` |
| `enum_range_boundary` | `enum_range_boundary(enum1, enum2)` | `enum1`, `enum2`: 枚举值或NULL | ARRAY | 返回两个枚举值之间的范围 | `enum_range_boundary(NULL, 'happy'::mood)` |

---

## Lambda函数

### Lambda语法

```sql
-- 新语法（推荐）
lambda x : x + 1
lambda x, y : x + y
lambda x, i : x > i  -- i是1-based索引

-- 旧语法（已弃用）
x -> x + 1
```

### Lambda函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `list_transform` | `list_transform(list, lambda(x))` | `list`: 列表, `lambda`: 变换函数 | LIST | 对每个元素应用函数 | `list_transform([1, 2, 3], x -> x * 2)` → `[2, 4, 6]` |
| `list_filter` | `list_filter(list, lambda(x))` | `list`: 列表, `lambda`: 过滤函数 | LIST | 过滤元素 | `list_filter([1, 2, 3, 4], x -> x > 2)` → `[3, 4]` |
| `list_reduce` | `list_reduce(list, lambda(x, y)[, initial])` | `list`: 列表, `lambda`: 归约函数, `initial`: 初始值 | 标量 | 归约为单个值 | `list_reduce([1, 2, 3], x, y -> x + y)` → `6` |

**别名**: `apply` / `array_apply` / `array_transform` / `list_apply` → `list_transform`, `array_filter` / `filter` → `list_filter`, `array_reduce` / `reduce` → `list_reduce`

---

## 工具函数

### 条件函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `coalesce` | `coalesce(expr, ...)` | 多个表达式 | 第一个非NULL类型 | 返回第一个非NULL值 | `coalesce(NULL, NULL, 'default')` → `default` |
| `ifnull` | `ifnull(expr, other)` | `expr`: 表达式, `other`: 替换值 | 与输入相同 | 两参数coalesce | `ifnull(NULL, 'default')` → `default` |
| `nullif` | `nullif(a, b)` | `a`, `b`: 值 | 与a相同 | a = b时返回NULL | `nullif(1, 1)` → `NULL` |
| `if` | `if(condition, true_value, false_value)` | 条件和两个返回值 | 与返回值相同 | 三元条件 | `if(1 > 0, 'yes', 'no')` → `yes` |
| `constant_or_null` | `constant_or_null(arg1, arg2)` | 两个值 | 与arg1相同或NULL | arg2为NULL时返回NULL | `constant_or_null(42, NULL)` → `NULL` |

### 系统信息函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `version` | `version()` | 无参数 | VARCHAR | 返回DuckDB版本 | `version()` |
| `current_database` | `current_database()` | 无参数 | VARCHAR | 返回当前数据库名 | `current_database()` → `memory` |
| `current_schema` | `current_schema()` | 无参数 | VARCHAR | 返回当前模式名 | `current_schema()` → `main` |
| `current_schemas` | `current_schemas(include_implicit)` | `include_implicit`: 是否包含隐式模式 | VARCHAR[] | 返回模式列表 | `current_schemas(true)` |
| `current_query` | `current_query()` | 无参数 | VARCHAR | 返回当前查询字符串 | `current_query()` |
| `txid_current` | `txid_current()` | 无参数 | BIGINT | 返回当前事务ID | `txid_current()` |

### UUID函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `uuid` | `uuid()` | 无参数 | UUID | 生成随机UUIDv4 | `uuid()` |
| `uuidv4` | `uuidv4()` | 无参数 | UUID | 生成随机UUIDv4 | `uuidv4()` |
| `uuidv7` | `uuidv7()` | 无参数 | UUID | 生成随机UUIDv7 | `uuidv7()` |
| `gen_random_uuid` | `gen_random_uuid()` | 无参数 | UUID | 生成随机UUIDv4 | `gen_random_uuid()` |
| `uuid_extract_timestamp` | `uuid_extract_timestamp(uuid)` | `uuid`: UUIDv7 | TIMESTAMPTZ | 从UUIDv7提取时间戳 | `uuid_extract_timestamp(uuidv7())` |
| `uuid_extract_version` | `uuid_extract_version(uuid)` | `uuid`: UUID | INTEGER | 提取UUID版本 | `uuid_extract_version(uuidv7())` → `7` |

### 类型检查函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `typeof` | `typeof(expression)` | 任意表达式 | VARCHAR | 返回数据类型名 | `typeof('hello')` → `VARCHAR` |
| `pg_typeof` | `pg_typeof(expression)` | 任意表达式 | VARCHAR | 返回数据类型名（PostgreSQL兼容） | `pg_typeof('hello')` → `varchar` |
| `can_cast_implicitly` | `can_cast_implicitly(source, target)` | 源值和目标值 | BOOLEAN | 检查是否可隐式转换 | `can_cast_implicitly(1::BIGINT, 1::SMALLINT)` |

### 哈希函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `hash` | `hash(value)` | 任意值 | UBIGINT | 返回哈希值 | `hash('duckdb')` |
| `md5` | `md5(string)` | 字符串 | VARCHAR(32) | MD5哈希 | `md5('abc')` |
| `md5_number` | `md5_number(string)` | 字符串 | UHUGEINT | MD5哈希（数值） | `md5_number('abc')` |
| `sha1` | `sha1(string)` | 字符串 | VARCHAR(40) | SHA-1哈希 | `sha1('abc')` |
| `sha256` | `sha256(string)` | 字符串 | VARCHAR(64) | SHA-256哈希 | `sha256('abc')` |

### 其他工具函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `alias` | `alias(column)` | 列 | VARCHAR | 返回列名 | `alias(col1)` → `col1` |
| `error` | `error(message)` | 错误消息字符串 | 抛出错误 | 抛出错误 | `error('Something went wrong')` |
| `stats` | `stats(expression)` | 表达式 | VARCHAR | 返回统计信息字符串 | `stats(column1)` |
| `read_text` | `read_text(source)` | 文件路径或glob | VARCHAR | 读取文件为文本 | `read_text('data.txt')` |
| `read_blob` | `read_blob(source)` | 文件路径或glob | BLOB | 读取文件为BLOB | `read_blob('data.bin')` |
| `getenv` | `getenv(var)` | 环境变量名 | VARCHAR | 返回环境变量值（仅CLI） | `getenv('HOME')` |
| `current_setting` | `current_setting('name')` | 配置名 | VARCHAR | 返回配置值 | `current_setting('access_mode')` |
| `equi_width_bins` | `equi_width_bins(min, max, count, nice)` | 最小值、最大值、桶数、是否优化 | DOUBLE[] | 返回等宽直方图边界 | `equi_width_bins(0, 10, 5, true)` |

### 表函数

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 | 示例 |
|------|------|----------|----------|------|------|
| `glob` | `glob(search_path)` | glob模式 | TABLE(file VARCHAR) | 返回匹配的文件名 | `glob('*.csv')` |
| `repeat_row` | `repeat_row(values..., num_rows)` | 值和行数 | TABLE | 返回重复行的表 | `repeat_row(1, 'a', num_rows := 3)` |
| `query` | `query(sql_string)` | SQL字符串（常量） | TABLE | 执行动态SQL | `query('SELECT 42')` |
| `query_table` | `query_table(table_name)` | 表名 | TABLE | 按名称返回表 | `query_table('my_table')` |

---

## 日期格式函数

### strftime / strptime

| 函数 | 语法 | 参数说明 | 返回类型 | 描述 |
|------|------|----------|----------|------|
| `strftime` | `strftime(timestamp, format)` | `timestamp`: 时间戳/日期, `format`: 格式字符串 | VARCHAR | 按格式转换为字符串 |
| `strptime` | `strptime(text, format)` | `text`: 字符串, `format`: 格式字符串 | TIMESTAMP | 按格式解析为时间戳 |
| `strptime` | `strptime(text, format_list)` | `text`: 字符串, `format_list`: 格式字符串列表 | TIMESTAMP | 尝试多个格式直到成功 |
| `try_strptime` | `try_strptime(text, format)` | 同上 | TIMESTAMP或NULL | 解析失败时返回NULL |

### 格式说明符

| 说明符 | 描述 | 示例 |
|--------|------|------|
| `%Y` | 四位年份 | `1992` |
| `%y` | 两位年份 | `92` |
| `%-y` | 两位年份（无前导零） | `92` |
| `%m` | 月（01-12） | `09` |
| `%-m` | 月（1-12） | `9` |
| `%d` | 日（01-31） | `20` |
| `%-d` | 日（1-31） | `20` |
| `%H` | 小时（00-23） | `14` |
| `%-H` | 小时（0-23） | `14` |
| `%I` | 小时（01-12） | `02` |
| `%-I` | 小时（1-12） | `2` |
| `%M` | 分钟（00-59） | `30` |
| `%-M` | 分钟（0-59） | `30` |
| `%S` | 秒（00-59） | `45` |
| `%-S` | 秒（0-59） | `45` |
| `%f` | 微秒 | `123456` |
| `%p` | AM/PM | `PM` |
| `%a` | 缩写星期名 | `Sun` |
| `%A` | 完整星期名 | `Sunday` |
| `%b` | 缩写月份名 | `Sep` |
| `%B` | 完整月份名 | `September` |
| `%u` | ISO周中的日（1-7） | `7` |
| `%w` | 周中的日（0-6，周日为0） | `0` |
| `%U` | 年中的周（周日开始） | `37` |
| `%W` | 年中的周（周一开始） | `37` |
| `%V` | ISO周数 | `38` |
| `%j` | 年中的日（001-366） | `263` |
| `%-j` | 年中的日（1-366） | `263` |
| `%z` | 时区偏移 | `+0800` |
| `%Z` | 时区名 | `CST` |
| `%%` | 百分号 | `%` |

---

## 使用示例

### 基本查询

```sql
-- 选择所有数据
SELECT * FROM data;

-- 条件过滤
SELECT * FROM data WHERE column1 > 100;

-- 排序和分页
SELECT * FROM data ORDER BY column1 DESC LIMIT 10 OFFSET 20;

-- 去重
SELECT DISTINCT category FROM data;
```

### 聚合查询

```sql
-- 基本聚合
SELECT 
    category,
    COUNT(*) as count,
    AVG(price) as avg_price,
    SUM(amount) as total,
    MAX(price) as max_price,
    MIN(price) as min_price
FROM data
GROUP BY category
HAVING COUNT(*) > 10;

-- 多维聚合
SELECT 
    category,
    region,
    SUM(sales) as total_sales
FROM data
GROUP BY ROLLUP(category, region);
```

### 字符串处理

```sql
-- 字符串操作
SELECT 
    UPPER(name) as upper_name,
    LOWER(name) as lower_name,
    CONCAT(first_name, ' ', last_name) as full_name,
    SUBSTRING(description, 1, 100) as short_desc,
    LENGTH(name) as name_length
FROM data;

-- 正则表达式
SELECT * FROM data 
WHERE email ~ '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$';

-- 字符串分割
SELECT 
    split_part(full_name, ' ', 1) as first_name,
    split_part(full_name, ' ', 2) as last_name
FROM data;
```

### 日期处理

```sql
-- 日期操作
SELECT 
    date_column,
    date_trunc('month', date_column) as month_start,
    last_day(date_column) as month_end,
    EXTRACT(YEAR FROM date_column) as year,
    EXTRACT(MONTH FROM date_column) as month,
    dayname(date_column) as weekday
FROM data;

-- 时间差
SELECT 
    start_date,
    end_date,
    date_diff('day', start_date, end_date) as days_diff,
    date_diff('month', start_date, end_date) as months_diff
FROM data;

-- 日期格式化
SELECT 
    strftime(date_column, '%Y-%m-%d') as formatted_date,
    strftime(timestamp_column, '%Y-%m-%d %H:%M:%S') as formatted_ts
FROM data;
```

### 窗口函数

```sql
-- 排名
SELECT 
    name,
    score,
    ROW_NUMBER() OVER (ORDER BY score DESC) as row_num,
    RANK() OVER (ORDER BY score DESC) as rank,
    DENSE_RANK() OVER (ORDER BY score DESC) as dense_rank
FROM data;

-- 分区排名
SELECT 
    category,
    name,
    score,
    ROW_NUMBER() OVER (PARTITION BY category ORDER BY score DESC) as category_rank
FROM data;

-- 移动平均
SELECT 
    date,
    value,
    AVG(value) OVER (
        ORDER BY date 
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    ) as moving_avg_3
FROM data;

-- 累计和
SELECT 
    date,
    amount,
    SUM(amount) OVER (ORDER BY date) as running_total
FROM data;

-- 前后值比较
SELECT 
    date,
    value,
    LAG(value, 1) OVER (ORDER BY date) as prev_value,
    LEAD(value, 1) OVER (ORDER BY date) as next_value
FROM data;
```

### 条件表达式

```sql
-- CASE WHEN
SELECT 
    name,
    score,
    CASE 
        WHEN score >= 90 THEN 'A'
        WHEN score >= 80 THEN 'B'
        WHEN score >= 70 THEN 'C'
        WHEN score >= 60 THEN 'D'
        ELSE 'F'
    END as grade
FROM data;

-- COALESCE处理NULL
SELECT 
    COALESCE(phone, email, 'N/A') as contact
FROM data;

-- NULLIF避免除零错误
SELECT 
    numerator / NULLIF(denominator, 0) as result
FROM data;
```

### CTE（公共表表达式）

```sql
-- 单个CTE
WITH monthly_stats AS (
    SELECT 
        date_trunc('month', date_column) as month,
        SUM(amount) as total
    FROM data
    GROUP BY 1
)
SELECT * FROM monthly_stats WHERE total > 1000;

-- 多个CTE
WITH 
high_value AS (
    SELECT * FROM data WHERE amount > 1000
),
monthly AS (
    SELECT 
        date_trunc('month', date_column) as month,
        SUM(amount) as total
    FROM high_value
    GROUP BY 1
)
SELECT * FROM monthly ORDER BY month;
```

### 列表操作

```sql
-- 创建列表
SELECT list_value(1, 2, 3, 4, 5);

-- 列表过滤
SELECT list_filter([1, 2, 3, 4, 5], x -> x > 2);

-- 列表变换
SELECT list_transform([1, 2, 3], x -> x * 2);

-- 列表归约
SELECT list_reduce([1, 2, 3, 4, 5], (acc, x) -> acc + x);

-- 列表排序
SELECT list_sort([3, 1, 4, 1, 5, 9, 2, 6]);
```

---

## 参考资料

- [DuckDB 官方文档](https://duckdb.org/docs/)
- [DuckDB 函数概览](https://duckdb.org/docs/sql/functions/overview)
- [DuckDB SQL 参考](https://duckdb.org/docs/sql/introduction)
