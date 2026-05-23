# data-analysis skill 优化建议

> 技能评估时间：2026-05-23
> 评估文件：SKILL.md、scripts/analyze.py、scripts/header_processor.py

## 背景

- **目标框架**：DeerFlow（沙箱环境）
- **适用场景**：银行数据（收单商户统计、月报等金融报表）
- **存储路径**：`/mnt/user-data/uploads/`（DeerFlow 环境路径，合理）

---

## 优化项

### 1. 多级表头处理流程缺失（高优先级）

**问题**：SKILL.md 没有提及 `header_processor.py` 的存在。银行数据（如收单商户统计表）常含多级合并表头，skill 会自动展平但用户不知情。

**建议**：在 "Core Capabilities" 中增加：

```markdown
### Multi-level Header Handling

Bank data often contains merged/multi-row headers. Excel files are automatically flattened using `openpyxl` before DuckDB loading. This is transparent — simply upload your file and query.
```

---

### 2. 缺少中文文件名/路径处理说明（中优先级）

**问题**：示例文件如 `27000099_202510_元_收单商户统计表.xlsx` 包含中文、括号、空格，SKILL.md 没说明如何引用。

**建议**：在 "Table Naming Rules" 补充：

```markdown
- **Chinese characters**: Column names with Chinese characters are accessible using double quotes: `"填报机构_机构名称"`
- **Special characters in file names**: Paths with spaces or special characters should be quoted: `/mnt/user-data/uploads/"my file.xlsx"`
```

---

### 3. 示例场景单一（低优先级）

**问题**：只有"销售数据"完整示例，银行用户无法参考。

**建议**：增加银行场景示例：

```bash
# 分析收单商户行业分布（2025年10月）
python /mnt/skills/public/data-analysis/scripts/analyze.py \
  --files /mnt/user-data/uploads/27000099_202510_元_收单商户统计表.xlsx \
  --action query \
  --sql "SELECT \"填报机构_机构名称\" as 机构, SUM(\"收单商户数_活跃商户\") as 活跃商户 FROM \"统计数据\" GROUP BY 机构 ORDER BY 活跃商户 DESC"
```

---

### 4. describe 与实际功能命名差异（低优先级）

**问题**：
- "generate statistics" — 实际是描述性统计
- "pivot tables" — 需用 CASE WHEN，无原生 pivot

**建议**：将 "generate statistics" → "descriptive statistics"，"pivot tables" → "pivot-style analysis (CASE WHEN)"

---

### 5. 缺少常见问题排查章节（低优先级）

**建议**：增加 "Troubleshooting"：

```markdown
## Troubleshooting

- **"Table not found"**: 使用 `--action inspect` 确认准确表名，含空格的表名需双引号：`"Sheet Name"`
- **"No such column"**: 列名含空格或特殊字符需双引号：`"Column Name"`
- **文件加载慢**: 首次加载后自动缓存，后续查询使用缓存数据库
```

---

### 6. 缓存路径说明（已过时）

**问题**：文档说 `/mnt/user-data/workspace/.data-analysis-cache/`，实际是 `~/.data-analysis-cache/`。

**建议**：更新为与 DeerFlow 环境一致的路径，或说明缓存路径由系统管理无需用户关注。

---

## 不需要修改的部分

以下原 review 提到的项，在 DeerFlow + 银行数据场景下无需修改：

- 示例路径 `/mnt/user-data/uploads/` 是正确的（DeerFlow 环境路径）
- 路径硬编码问题不成立
- Workflow 步骤与环境描述是合理的

---

## 优先级排序

| 优先级 | 问题 | 工作量 |
|--------|------|--------|
| 高 | 1. 多级表头处理说明 | 小 |
| 中 | 2. 中文/特殊字符处理 | 小 |
| 低 | 3. 增加银行场景示例 | 中 |
| 低 | 4. 描述文案优化 | 极小 |
| 低 | 5. 故障排查章节 | 小 |
| 低 | 6. 缓存路径说明 | 极小 |