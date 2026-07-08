# Data Cleaning Workflow

Use this workflow when handling `/clean`, `/清洗`, or any request to improve data
quality, standardize fields, remove duplicates, validate rules, or prepare data
for report/dashboard/modeling.

## Principle

Cleaning rules are business decisions. The Agent should guide the user to define
rules, infer safe defaults only when obvious, and clearly report every change.
Do not silently force cleaning assumptions.

Python scripts apply explicit rules. The Agent owns diagnosis, questioning,
rule design, and explanation.

## Required Steps

1. **Profile the data first**
   - Inspect table names, column names, types, sample values, row count, missing rate, duplicate candidates, date-like columns, money-like columns, ID-like columns.
   - Identify likely grain: order, user, event, product, transaction, daily aggregate, etc.
   - Identify candidate unique keys, including multi-column keys.

2. **Ask cleaning questions when rules are ambiguous**
   - What is the unique key? Can it be multiple columns?
   - For duplicate keys, keep latest, first, last, aggregate, or flag?
   - Which columns are dates, money, numeric, boolean, category, text, or PII?
   - How should missing values be handled by column?
   - What business ranges define invalid values?
   - Which fields must be logically consistent?
   - Are there cross-table rules, such as registration date <= first purchase date?

3. **Build a cleaning plan**
   - List proposed rules before applying them.
   - Mark rules as user-specified, inferred-safe, or needs confirmation.
   - Do not apply destructive changes without user confirmation unless explicitly requested.
   - Prefer writing to a new output table, e.g. `<table>_cleaned`.

4. **Apply configurable cleaning**
   - Use `scripts/data_cleaner.py table <table> --config <rules.json>`.
   - Use Python only to execute explicit rules and produce a cleaning report.
   - Preserve source table unless the user explicitly asks to overwrite.

5. **Validate after cleaning**
   - Compare before/after row counts, missing rates, duplicate counts, data types, rule violations, and outlier counts.
   - Report dropped/nullified/flagged rows.
   - If cleaning introduced new nulls through type conversion, surface them.

## Supported Cleaning Rule Types

- **Type and format conversion**: DATE, datetime, money with 2 decimals, numeric, integer, boolean, text.
- **Missing values**: drop, mean, median, mode, constant, or preserve.
- **Duplicate handling**: full-row duplicates, multi-column unique keys, keep first/last/latest.
- **Outlier handling**: business bounds, IQR, Z-score; flag, null, clip, or drop.
- **Normalization and standardization**: min-max and z-score.
- **Consistency and text cleaning**: strip, case normalization, special-character removal, controlled replacement.
- **Rule engine**: field logic checks such as `start_date <= end_date` or `paid_amount <= order_amount`.
- **Cross-table validation**: join by one or more keys and validate business logic.
- **Feature engineering and masking**: date parts, weekend flags, ratios, concatenated keys, phone/customer masking.

## Rule Config Example

```json
{
  "output_table": "orders_cleaned",
  "unique_key": ["order_id", "line_id"],
  "duplicate_keep": "latest",
  "duplicate_order_by": "updated_at",
  "type_conversions": [
    {"column": "order_date", "type": "date"},
    {"column": "paid_amount", "type": "money", "decimals": 2},
    {"column": "is_member", "type": "boolean", "true_values": ["是", "Y"], "false_values": ["否", "N"]}
  ],
  "missing_values": {
    "customer_level": {"strategy": "constant", "value": "unknown"},
    "age": {"strategy": "median"}
  },
  "outliers": [
    {"column": "age", "method": "bounds", "min": 0, "max": 150, "action": "null"},
    {"column": "paid_amount", "method": "iqr", "action": "flag"}
  ],
  "text_cleaning": [
    {"column": "province", "strip": true, "replace": {"省": ""}}
  ],
  "rules": [
    {"name": "register_before_purchase", "left": "register_date", "op": "<=", "right": "first_purchase_date", "action": "flag"}
  ],
  "cross_table_rules": [
    {
      "name": "user_register_before_first_purchase",
      "table": "first_purchases",
      "key": ["user_id"],
      "left": "register_date",
      "op": "<=",
      "right": "first_purchase_date"
    }
  ],
  "derived_features": [
    {"name": "order_month", "method": "date_part", "source": "order_date", "part": "month"},
    {"name": "amount_per_item", "method": "ratio", "numerator": "paid_amount", "denominator": "quantity", "decimals": 2}
  ],
  "masking": [
    {"column": "phone", "method": "middle", "keep_start": 3, "keep_end": 4}
  ],
  "report_path": "outputs/reports/orders_cleaning_report.json"
}
```

## Agent Question Checklist

Ask only questions that materially affect the cleaning result:

- “这张表的一行代表什么？订单、用户、事件还是汇总行？”
- “唯一键是哪几个字段？重复时保留最新还是按业务聚合？”
- “这些日期字段是否只保留日期，不保留时分秒？”
- “金额字段是否统一为两位小数？负数是否允许？”
- “缺失值是删除、填补、保留，还是单独标记？”
- “哪些异常是业务异常需要保留，哪些是脏数据需要修正？”
- “是否需要跨表校验？例如用户注册日期早于首次购买日期。”

## Output Requirements

The Agent should return:

- Cleaning plan.
- Cleaned table name.
- Before/after quality summary.
- Rule execution report.
- Remaining risks and unresolved questions.
- Suggested next analysis step.
