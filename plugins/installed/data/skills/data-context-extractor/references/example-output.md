# Example: Generated Skill

This is an example of what a generated skill looks like after the bootstrap process. This example is for a fictional e-commerce company called "ShopCo" using Snowflake.

---

## Example SKILL.md

```markdown
---
name: shopco-data-analyst
description: "ShopCo data analysis skill for Snowflake. Provides context for querying e-commerce data including customer, order, and product analytics. Use when analyzing ShopCo data for: (1) Revenue and order metrics, (2) Customer behavior and retention, (3) Product performance, or any data questions requiring ShopCo-specific context."
---

# ShopCo Data Analysis

## SQL Dialect: Snowflake

- **Table references**: `SHOPCO_DW.SCHEMA.TABLE` or with quotes for case-sensitive: `"Column_Name"`
- **Safe division**: `DIV0(a, b)` returns 0, `DIV0NULL(a, b)` returns NULL
- **Date functions**:
  - `DATE_TRUNC('MONTH', date_col)`
  - `DATEADD(DAY, -1, date_col)`
  - `DATEDIFF(DAY, start_date, end_date)`
- **Column exclusion**: `SELECT * EXCLUDE (column_to_exclude)`

---

## Entity Disambiguation

**"Customer" can mean:**
- **User**: A login account that can browse and save items (CORE.DIM_USERS: user_id)
- **Customer**: A user who has made at least one purchase (CORE.DIM_CUSTOMERS: customer_id)
- **Account**: A billing entity, can have multiple users in B2B (CORE.DIM_ACCOUNTS: account_id)

**Relationships:**
- User → Customer: 1:1 (customer_id = user_id for purchasers)
- Account → User: 1:many (join on account_id)

---

## Business Terminology

| Term | Definition | Notes |
|------|------------|-------|
| GMV | Gross Merchandise Value - total order value before returns/discounts | Use for top-line reporting |
| NMV | Net Merchandise Value - GMV minus returns and discounts | Use for actual revenue |
| AOV | Average Order Value - NMV / order count | Exclude $0 orders |
| LTV | Lifetime Value - total NMV per customer since first order | Rolling calc, updates daily |
| CAC | Customer Acquisition Cost - marketing spend / new customers | By cohort month |

---

## Standard Filters

Always apply these filters unless explicitly told otherwise:

```sql
-- Exclude test and internal orders
WHERE order_status != 'TEST'
  AND customer_type != 'INTERNAL'
  AND is_employee_order = FALSE

-- Exclude cancelled orders for revenue metrics
  AND order_status NOT IN ('CANCELLED', 'FRAUDULENT')
```

---

## Key Metrics

### Gross Merchandise Value (GMV)
- **Definition**: Total value of all orders placed
- **Formula**: `SUM(order_total_gross)`
- **Source**: `CORE.FCT_ORDERS.order_total_gross`
- **Time grain**: Daily, aggregated to weekly/monthly
- **Caveats**: Includes orders that may later be cancelled or returned

### Net Revenue
- **Definition**: Actual revenue after returns and discounts
- **Formula**: `SUM(order_total_gross - return_amount - discount_amount)`
- **Source**: `CORE.FCT_ORDERS`
- **Caveats**: Returns can occur up to 90 days post-order; use settled_revenue for finalized numbers

---

## Knowledge Base Navigation

| Domain | Reference File | Use For |
|--------|----------------|---------|
| Orders | `references/orders.md` | Order tables, GMV/NMV calculations |
| Customers | `references/customers.md` | User/customer entities, LTV, cohorts |
| Products | `references/products.md` | Catalog, inventory, categories |

---

## Common Query Patterns

### Daily GMV by Channel
```sql
SELECT
    DATE_TRUNC('DAY', order_timestamp) AS order_date,
    channel,
    SUM(order_total_gross) AS gmv,
    COUNT(DISTINCT order_id) AS order_count
FROM SHOPCO_DW.CORE.FCT_ORDERS
WHERE order_status NOT IN ('TEST', 'CANCELLED', 'FRAUDULENT')
  AND order_timestamp >= DATEADD(DAY, -30, CURRENT_DATE())
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC
```

### Customer Cohort Retention
```sql
WITH cohorts AS (
    SELECT
        customer_id,
        DATE_TRUNC('MONTH', first_order_date) AS cohort_month
    FROM SHOPCO_DW.CORE.DIM_CUSTOMERS
)
SELECT
    c.cohort_month,
    DATEDIFF(MONTH, c.cohort_month, DATE_TRUNC('MONTH', o.order_timestamp)) AS months_since_first,
    COUNT(DISTINCT c.customer_id) AS active_customers
FROM cohorts c
JOIN SHOPCO_DW.CORE.FCT_ORDERS o ON c.customer_id = o.customer_id
WHERE o.order_status NOT IN ('TEST', 'CANCELLED')
GROUP BY 1, 2
ORDER BY 1, 2
```
```

---

## Example references/orders.md

```markdown
# Orders Tables

Order and transaction data for ShopCo.

---

## Key Tables

### FCT_ORDERS
**Location**: `SHOPCO_DW.CORE.FCT_ORDERS`
**Description**: Fact table of all orders. One row per order.
**Primary Key**: `order_id`
**Update Frequency**: Hourly (15 min lag)
**Partitioned By**: `order_date`

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| **order_id** | VARCHAR | Unique order identifier | |
| **customer_id** | VARCHAR | FK to DIM_CUSTOMERS | NULL for guest checkout |
| **order_timestamp** | TIMESTAMP_NTZ | When order was placed | UTC |
| **order_date** | DATE | Date portion of order_timestamp | Partition column |
| **order_status** | VARCHAR | Current status | PENDING, SHIPPED, DELIVERED, CANCELLED, RETURNED |
| **channel** | VARCHAR | Acquisition channel | WEB, APP, MARKETPLACE |
| **order_total_gross** | DECIMAL(12,2) | Pre-discount total | |
| **discount_amount** | DECIMAL(12,2) | Total discounts applied | |
| **return_amount** | DECIMAL(12,2) | Value of returned items | Updates async |

**Relationships**:
- Joins to `DIM_CUSTOMERS` on `customer_id`
- Parent of `FCT_ORDER_ITEMS` via `order_id`

---

## Sample Queries

### Orders with Returns Rate
```sql
SELECT
    DATE_TRUNC('WEEK', order_date) AS week,
    COUNT(*) AS total_orders,
    SUM(CASE WHEN return_amount > 0 THEN 1 ELSE 0 END) AS orders_with_returns,
    DIV0(SUM(CASE WHEN return_amount > 0 THEN 1 ELSE 0 END), COUNT(*)) AS return_rate
FROM SHOPCO_DW.CORE.FCT_ORDERS
WHERE order_status NOT IN ('TEST', 'CANCELLED')
  AND order_date >= DATEADD(MONTH, -3, CURRENT_DATE())
GROUP BY 1
ORDER BY 1
```
```

---

This example demonstrates:
- Complete frontmatter with triggering description
- Dialect-specific SQL notes
- Clear entity disambiguation
- Terminology glossary
- Standard filters as copy-paste SQL
- Metric definitions with formulas
- Navigation to reference files
- Real, runnable query examples
