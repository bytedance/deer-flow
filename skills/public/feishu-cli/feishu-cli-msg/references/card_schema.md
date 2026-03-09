# 卡片消息构造指南

飞书卡片消息（interactive）是最灵活的消息类型，支持丰富的布局和交互组件。本文档是完整的构造参考。

## 三种发送方式

| 方式 | 适用场景 | 灵活性 |
|------|---------|--------|
| 完整 Card JSON | 代码动态生成卡片 | 最高 |
| template_id | 使用飞书卡片搭建工具创建的模板 | 中等（模板变量） |
| card_id | 引用已保存的卡片实例 | 最低（固定内容） |

**推荐**：Claude 构造消息时使用完整 Card JSON，最灵活且无需预先创建模板。

---

## Card JSON 结构

### v1 格式（推荐，兼容性好）

```json
{
  "header": {
    "template": "blue",
    "title": {"tag": "plain_text", "content": "卡片标题"}
  },
  "elements": [
    {"tag": "markdown", "content": "内容"},
    {"tag": "hr"},
    {"tag": "note", "elements": [{"tag": "plain_text", "content": "备注"}]}
  ]
}
```

### v2 格式（支持高级组件）

```json
{
  "schema": "2.0",
  "header": {
    "template": "blue",
    "title": {"tag": "plain_text", "content": "卡片标题"}
  },
  "body": {
    "direction": "vertical",
    "elements": [
      {"tag": "markdown", "content": "内容"}
    ]
  }
}
```

**v1 vs v2 区别**：

| 特性 | v1 | v2 |
|------|----|----|
| 顶层容器 | `elements` 数组 | `body.elements` |
| 表格组件 | 不支持 | `table` |
| 图表组件 | 不支持 | `chart` |
| 表单容器 | 不支持 | `form_container` |
| 多列布局 | `column_set`（有限） | `column_set`（完整） |

**选择建议**：简单通知用 v1；需要表格、图表、表单用 v2。

---

## header 配置

### 颜色模板

| template 值 | 色系 | 推荐场景 |
|-------------|------|---------|
| `blue` | 蓝色 | 通用通知、信息提示 |
| `wathet` | 浅蓝 | 轻量提示、次要通知 |
| `turquoise` | 青色 | 进行中、处理中状态 |
| `green` | 绿色 | 成功、完成、通过 |
| `yellow` | 黄色 | 注意、提醒 |
| `orange` | 橙色 | 警告、需关注 |
| `red` | 红色 | 错误、失败、紧急 |
| `carmine` | 深红 | 严重告警、危险 |
| `violet` | 紫罗兰 | 特殊标记 |
| `purple` | 紫色 | 自定义分类 |
| `indigo` | 靛蓝 | 深色主题 |
| `grey` | 灰色 | 已处理、归档、历史 |

### 语义化颜色速查

```
成功/完成 → green
通用通知 → blue
警告/注意 → orange
错误/紧急 → red
进行中   → turquoise
已处理   → grey
```

### header 完整结构

```json
{
  "header": {
    "template": "blue",
    "title": {
      "tag": "plain_text",
      "content": "卡片标题"
    },
    "subtitle": {
      "tag": "plain_text",
      "content": "副标题（可选）"
    }
  }
}
```

---

## 组件速查

### 内容组件

#### markdown（最常用）

```json
{
  "tag": "markdown",
  "content": "**加粗** *斜体* ~~删除线~~ `代码`\n[链接](url)\n<font color='green'>绿色</font>"
}
```

#### hr（分割线）

```json
{"tag": "hr"}
```

#### note（底部备注）

灰色小字，通常放在卡片底部。

```json
{
  "tag": "note",
  "elements": [
    {"tag": "plain_text", "content": "备注内容"}
  ]
}
```

note 的 elements 支持 `plain_text`、`lark_md`、`img` 类型。

#### img（图片）

```json
{
  "tag": "img",
  "img_key": "img_v2_xxx",
  "alt": {"tag": "plain_text", "content": "图片描述"},
  "mode": "fit_horizontal"
}
```

mode 可选值：`crop_center`（居中裁剪）、`fit_horizontal`（适应宽度）、`large`（大图）、`medium`（中图）、`small`（小图）、`tiny`（超小图）。

### 布局组件

#### div（文本块 + fields 多列）

基础文本块：

```json
{
  "tag": "div",
  "text": {"tag": "lark_md", "content": "一段文本"}
}
```

带 fields（多列布局）：

```json
{
  "tag": "div",
  "fields": [
    {"is_short": true, "text": {"tag": "lark_md", "content": "**标签1**\n值1"}},
    {"is_short": true, "text": {"tag": "lark_md", "content": "**标签2**\n值2"}},
    {"is_short": true, "text": {"tag": "lark_md", "content": "**标签3**\n值3"}},
    {"is_short": true, "text": {"tag": "lark_md", "content": "**标签4**\n值4"}}
  ]
}
```

- `is_short: true`：半宽排列（一行放两个）
- `is_short: false`：全宽排列（独占一行）

带 extra（右侧附加元素）：

```json
{
  "tag": "div",
  "text": {"tag": "lark_md", "content": "左侧文本"},
  "extra": {
    "tag": "button",
    "text": {"tag": "plain_text", "content": "操作"},
    "type": "primary",
    "url": "https://example.com"
  }
}
```

#### column_set（多列分栏，v2）

```json
{
  "tag": "column_set",
  "flex_mode": "none",
  "background_style": "default",
  "columns": [
    {
      "tag": "column",
      "width": "weighted",
      "weight": 1,
      "elements": [
        {"tag": "markdown", "content": "**左栏内容**\n详细描述..."}
      ]
    },
    {
      "tag": "column",
      "width": "weighted",
      "weight": 1,
      "elements": [
        {"tag": "markdown", "content": "**右栏内容**\n详细描述..."}
      ]
    }
  ]
}
```

`flex_mode` 可选值：`none`（不换行）、`flow`（自动换行）、`bisect`（二等分）、`trisect`（三等分）。

### 交互组件

#### action（按钮容器）

```json
{
  "tag": "action",
  "actions": [
    {
      "tag": "button",
      "text": {"tag": "plain_text", "content": "主要按钮"},
      "type": "primary",
      "url": "https://example.com"
    },
    {
      "tag": "button",
      "text": {"tag": "plain_text", "content": "危险按钮"},
      "type": "danger"
    },
    {
      "tag": "button",
      "text": {"tag": "plain_text", "content": "默认按钮"},
      "type": "default"
    }
  ]
}
```

按钮类型：
- `primary`：蓝色主按钮
- `danger`：红色危险按钮
- `default`：灰色普通按钮

**注意**：`url` 属性实现跳转链接，无需服务端支持；`value` 属性触发回调，需要应用服务端处理。CLI 场景下推荐使用 `url`。

#### select_static（下拉选择）

```json
{
  "tag": "select_static",
  "placeholder": {"tag": "plain_text", "content": "请选择"},
  "options": [
    {"text": {"tag": "plain_text", "content": "选项 1"}, "value": "opt1"},
    {"text": {"tag": "plain_text", "content": "选项 2"}, "value": "opt2"}
  ]
}
```

#### date_picker（日期选择）

```json
{
  "tag": "date_picker",
  "placeholder": {"tag": "plain_text", "content": "请选择日期"}
}
```

#### overflow（折叠菜单）

```json
{
  "tag": "overflow",
  "options": [
    {"text": {"tag": "plain_text", "content": "操作 1"}, "value": "action1"},
    {"text": {"tag": "plain_text", "content": "操作 2"}, "value": "action2"}
  ]
}
```

### v2 独有组件

#### table（表格，v2）

```json
{
  "tag": "table",
  "page_size": 5,
  "row_height": "low",
  "header_style": {"text_align": "center", "text_size": "normal", "background_style": "grey", "text_color": "default", "bold": true},
  "columns": [
    {"name": "name", "display_name": "姓名", "width": "auto", "data_type": "text"},
    {"name": "status", "display_name": "状态", "width": "auto", "data_type": "text"}
  ],
  "rows": [
    {"name": "张三", "status": "已完成"},
    {"name": "李四", "status": "进行中"}
  ]
}
```

#### chart（图表，v2）

```json
{
  "tag": "chart",
  "chart_spec": {
    "type": "bar",
    "title": {"text": "数据统计"},
    "data": {
      "values": [
        {"category": "A", "value": 10},
        {"category": "B", "value": 20}
      ]
    }
  }
}
```

---

## 卡片 Markdown 语法（lark_md）

卡片内的 `markdown` 组件使用 `lark_md` 语法，与标准 Markdown 有差异。

### 支持的语法

| 语法 | 效果 |
|------|------|
| `**文本**` | 加粗 |
| `*文本*` | 斜体 |
| `~~文本~~` | 删除线 |
| `` `代码` `` | 行内代码 |
| `[文本](url)` | 超链接 |
| `![描述](img_key)` | 图片（需要 img_key） |

### 特有语法

#### 彩色文字

```markdown
<font color='green'>成功</font>
<font color='red'>失败</font>
<font color='grey'>已处理</font>
```

仅支持 `green`、`red`、`grey` 三种颜色。

#### @用户

```markdown
<at id=ou_xxx></at>
<at id=all></at>
```

**注意**：卡片中 @用户的语法是 `<at id=xxx>`（无引号），而 text/post 消息中是 `<at user_id="xxx">`（有引号），两者不同。

### 不支持的语法

- 标题（`#`、`##` 等）
- 有序/无序列表（`-`、`1.`）→ 使用 `\n- ` 或 `\n1. ` 模拟
- 代码块（` ``` `）→ 卡片中显示效果有限
- 表格 → 使用 v2 的 `table` 组件代替

---

## 完整卡片模板

### 模板 1：简单通知

适用于部署通知、任务完成等简单场景。

```json
{
  "header": {
    "template": "green",
    "title": {"tag": "plain_text", "content": "部署成功"}
  },
  "elements": [
    {
      "tag": "markdown",
      "content": "**服务**: api-gateway\n**版本**: v1.2.3\n**环境**: production\n**时间**: 2024-01-01 10:00:00"
    },
    {"tag": "hr"},
    {"tag": "note", "elements": [{"tag": "plain_text", "content": "CI/CD Pipeline #456"}]}
  ]
}
```

### 模板 2：告警卡片

适用于监控告警、错误通知等紧急场景。

```json
{
  "header": {
    "template": "red",
    "title": {"tag": "plain_text", "content": "P0 告警"}
  },
  "elements": [
    {
      "tag": "div",
      "fields": [
        {"is_short": true, "text": {"tag": "lark_md", "content": "**服务**\napi-gateway"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**级别**\n<font color='red'>P0 - 紧急</font>"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**触发时间**\n2024-01-01 10:00"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**持续时间**\n<font color='red'>15 分钟</font>"}}
      ]
    },
    {"tag": "markdown", "content": "**错误详情**: 数据库连接池耗尽，导致 API 超时\n**影响范围**: 全部用户无法登录"},
    {"tag": "hr"},
    {
      "tag": "action",
      "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": "查看监控"}, "type": "primary", "url": "https://grafana.example.com/dashboard/123"},
        {"tag": "button", "text": {"tag": "plain_text", "content": "查看日志"}, "type": "default", "url": "https://kibana.example.com/logs"},
        {"tag": "button", "text": {"tag": "plain_text", "content": "已处理"}, "type": "default"}
      ]
    }
  ]
}
```

### 模板 3：进度报告

适用于构建报告、测试报告、数据统计等场景。

```json
{
  "header": {
    "template": "blue",
    "title": {"tag": "plain_text", "content": "每日构建报告"}
  },
  "elements": [
    {
      "tag": "div",
      "fields": [
        {"is_short": true, "text": {"tag": "lark_md", "content": "**项目**\nfeishu-cli"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**分支**\nmain"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**提交**\nabc1234"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**触发者**\n张三"}}
      ]
    },
    {"tag": "hr"},
    {
      "tag": "markdown",
      "content": "**构建结果**\n<font color='green'>Build: Success</font>\n<font color='green'>Unit Tests: 142/142 passed</font>\n<font color='green'>Integration Tests: 38/38 passed</font>\n<font color='grey'>Coverage: 87.3%</font>"
    },
    {"tag": "hr"},
    {
      "tag": "action",
      "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": "查看详情"}, "type": "primary", "url": "https://ci.example.com/build/789"},
        {"tag": "button", "text": {"tag": "plain_text", "content": "查看覆盖率"}, "type": "default", "url": "https://codecov.example.com/report"}
      ]
    },
    {"tag": "note", "elements": [{"tag": "plain_text", "content": "Pipeline #789 | Duration: 3m 25s"}]}
  ]
}
```

### 模板 4：文档操作通知

适用于飞书文档创建/更新/导出完成后的通知。

```json
{
  "header": {
    "template": "turquoise",
    "title": {"tag": "plain_text", "content": "文档操作完成"}
  },
  "elements": [
    {
      "tag": "div",
      "fields": [
        {"is_short": true, "text": {"tag": "lark_md", "content": "**操作**\n创建文档"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**状态**\n<font color='green'>成功</font>"}}
      ]
    },
    {
      "tag": "markdown",
      "content": "**文档标题**: 技术方案 - 用户认证重构\n**文档 ID**: doxcnxxxxxx\n**权限**: 已授予 full_access"
    },
    {"tag": "hr"},
    {
      "tag": "action",
      "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": "打开文档"}, "type": "primary", "url": "https://xxx.feishu.cn/docx/doxcnxxxxxx"}
      ]
    },
    {"tag": "note", "elements": [{"tag": "plain_text", "content": "由 feishu-cli 自动创建"}]}
  ]
}
```

### 模板 5：审批确认

适用于需要用户决策的场景，如审批请求、确认操作等。

```json
{
  "header": {
    "template": "orange",
    "title": {"tag": "plain_text", "content": "审批请求 - 服务器扩容"}
  },
  "elements": [
    {
      "tag": "div",
      "fields": [
        {"is_short": true, "text": {"tag": "lark_md", "content": "**申请人**\n张三"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**申请时间**\n2024-01-01 10:00"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**类型**\n服务器扩容"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**优先级**\n<font color='red'>紧急</font>"}}
      ]
    },
    {"tag": "hr"},
    {
      "tag": "markdown",
      "content": "**申请说明**\n线上流量持续增长，当前服务器 CPU 利用率已达 85%，需要增加 2 台 8C16G 服务器。\n\n**预计费用**: ¥3,200/月"
    },
    {"tag": "hr"},
    {
      "tag": "action",
      "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": "批准"}, "type": "primary"},
        {"tag": "button", "text": {"tag": "plain_text", "content": "拒绝"}, "type": "danger"},
        {"tag": "button", "text": {"tag": "plain_text", "content": "查看详情"}, "type": "default", "url": "https://example.com/approval/456"}
      ]
    }
  ]
}
```

---

## CLI 发送示例

### 从文件发送卡片

```bash
# 将卡片 JSON 写入文件
cat > /tmp/card.json << 'CARD_EOF'
{
  "header": {
    "template": "green",
    "title": {"tag": "plain_text", "content": "任务完成"}
  },
  "elements": [
    {"tag": "markdown", "content": "所有子任务已完成，可以发布。"},
    {"tag": "note", "elements": [{"tag": "plain_text", "content": "自动通知"}]}
  ]
}
CARD_EOF

# 发送
feishu-cli msg send \
  --receive-id-type email \
  --receive-id user@example.com \
  --msg-type interactive \
  --content-file /tmp/card.json
```

### 使用 template_id

```bash
cat > /tmp/tpl.json << 'EOF'
{
  "type": "template",
  "data": {
    "template_id": "AAqk1xxxxxx",
    "template_variable": {
      "title": "部署通知",
      "env": "production",
      "version": "v1.2.3"
    }
  }
}
EOF

feishu-cli msg send \
  --receive-id-type email \
  --receive-id user@example.com \
  --msg-type interactive \
  --content-file /tmp/tpl.json
```

### 内联 JSON 发送简单卡片

```bash
feishu-cli msg send \
  --receive-id-type email \
  --receive-id user@example.com \
  --msg-type interactive \
  --content '{"header":{"template":"blue","title":{"tag":"plain_text","content":"快速通知"}},"elements":[{"tag":"markdown","content":"任务已完成"}]}'
```

---

## 注意事项

1. **大小限制**：卡片 JSON 最大 30 KB，超出时精简内容或拆分多条消息
2. **按钮回调**：`url` 属性可直接跳转（无需服务端）；`value` 属性需要应用服务端处理回调事件
3. **图片引用**：卡片中的 `img_key` 需要通过飞书 API 上传获取，不能直接使用外部 URL
4. **Markdown 差异**：卡片 Markdown（lark_md）不支持标题、列表等常见语法，仅支持加粗/斜体/删除线/链接/代码/颜色/@人
5. **v1 vs v2**：优先用 v1（兼容性好），需要表格/图表时用 v2
6. **颜色语义**：header 颜色应与消息语义匹配（绿=成功、红=错误、橙=警告、蓝=通知）
