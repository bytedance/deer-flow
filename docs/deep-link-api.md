# DeerFlow Deep-Link API

外部系统通过 HTTP GET 请求构造跳转 URL，将用户引导至 DeerFlow 指定 Agent 并自动发起对话。

---

## 约定

| 项目     | 说明                                             |
| -------- | ------------------------------------------------ |
| 协议     | HTTPS                                            |
| 方法     | GET                                              |
| 认证     | 用户需持有 DeerFlow 有效会话，否则重定向到登录页 |
| 根路径   | `https://<deerflow-host>`                        |
| 编码     | 参数值须经 `encodeURIComponent` 编码             |
| 生效条件 | 仅新对话（`/new`）生效，已有对话忽略所有参数     |

### 启动会话恢复（`launch_id`）

当调用方希望同时支持：

- 用户显式再次点击同一个业务入口时重新执行
- 用户刷新浏览器或宿主 iframe 重建时恢复刚才那次会话

应传入 `launch_id`。

规则如下：

- `launch_id` 只用于 DeerFlow 前端恢复逻辑，不透传给 Agent
- 同一浏览器会话内，DeerFlow 首次使用某个 `launch_id` 创建线程后，会记录 `launch_id -> threadId`
- 后续再次打开同一个 `/chats/new?...&launch_id=<same>` 时，若映射仍存在，DeerFlow 应直接恢复该 thread，而不是重复 `auto_send`
- 若调用方希望即使业务参数完全相同也重新执行，必须生成新的 `launch_id`

### 登录验证

DeerFlow 支持两种认证方式：

#### 方式 A：Session Cookie（标准登录）

适用于独立浏览器窗口直接打开的场景。

```
未登录用户访问 deep-link URL
        │
        ▼
  重定向到 /login?next=<encodeURIComponent(目标路径)>
        │
        ▼
  用户完成登录
        │
        ▼
  自动跳回 next 参数指定的路径
```

#### 方式 B：EHM Token 免登（外部系统跳转推荐）

适用于 EHM 等外部系统跳转场景。外部系统预先签发 JWT，DeerFlow 直接恢复用户身份，无需用户手动输入凭据。

**推荐：Cookie 预置**（token 不在地址栏出现，无泄漏风险）

```
外部系统在 DeerFlow 域名下预置 Cookie：
  ehm_token=<JWT> （SameSite=Lax, path=/, max-age=86400）
  ehm_user=<base64 JSON> （可选，SameSite=Lax, path=/, max-age=86400）
        │
        ▼
  直接跳转到 deep-link URL（无需经过 /login）
        │
        ▼
  SSR getServerSideUser() 读取 Cookie，注入用户上下文
```

> 实现：[ehm-auth.ts:140-145](frontend/src/core/auth/ehm-auth.ts#L140-L145) `setEhmCookies`，[server.ts:31-37](frontend/src/core/auth/server.ts#L31-L37) `getServerSideUser` 读取 cookie 直接恢复用户。

**备选：URL 传参**（token 经地址栏传递，用于无法跨域写 cookie 的场景）

```
外部系统构造 /login?next=<deep-link>&ehm_token=<JWT>&ehm_user=<base64>
        │
        ▼
  登录页校验 JWT，写 Cookie（setEhmCookieAndRedirect）
        │
        ▼
  302 跳转到 deep-link 页面
```

**EHM Token 参数**：

| 参数        | 传递方式      | 类型   | 必填 | 约束               | 说明                                                 |
| ----------- | ------------- | ------ | ---- | ------------------ | ---------------------------------------------------- |
| `ehm_token` | Cookie 或 URL | string | 是   | 有效 JWT，未过期   | EHM 签发的身份令牌。payload：`{id, exp, iat}`        |
| `ehm_user`  | Cookie 或 URL | string | 推荐 | base64 编码的 JSON | 用户信息。结构：`{id, user_name, real_name, org_id}` |

> **推荐 Cookie 方式**：外部系统在 DeerFlow 域名下写入 `ehm_token` / `ehm_user` Cookie（`SameSite=Lax, path=/, max-age=86400`），然后直接跳转 deep-link URL，全程 token 不出现在地址栏。需外部系统与 DeerFlow 同域或可通过接口写 DeerFlow 域的 Cookie。

**EHM Token 校验规则**：

| 校验项                                      | 失败行为                                           |
| ------------------------------------------- | -------------------------------------------------- |
| `ehm_token` 不存在或无法解码                | 显示错误 "EHM 单点登录失败：token 无效或已过期"    |
| `ehm_token.exp` 已过期                      | 同上                                               |
| `ehm_user` base64 解码失败                  | 仅使用 token payload 的 `id`，其他字段留空         |
| `ehm_user` JSON 中 `id` 或 `user_name` 缺失 | 视为无效，user 返回 null（后续行为取决于前端守卫） |

**auth 链路**（代码来源）：

| 阶段                | 位置                                                                     | 说明                                              |
| ------------------- | ------------------------------------------------------------------------ | ------------------------------------------------- |
| 登录页读取 EHM 参数 | [login/page.tsx:65-86](<frontend/src/app/(auth)/login/page.tsx#L65-L86>) | 从 `searchParams` 提取 `ehm_token`、`ehm_user`    |
| JWT 校验            | [ehm-auth.ts:93-98](frontend/src/core/auth/ehm-auth.ts#L93-L98)          | `isEhmTokenValid()` 检查 `exp` 是否过期           |
| Cookie 写入         | [ehm-auth.ts:159-166](frontend/src/core/auth/ehm-auth.ts#L159-L166)      | `setEhmCookieAndRedirect()` 写 cookie → 跳转      |
| SSR 身份恢复        | [server.ts:31-37](frontend/src/core/auth/server.ts#L31-L37)              | `getServerEhmToken()` → `getServerEhmUser()`      |
| 401 自动重试        | [fetcher.ts:114-126](frontend/src/core/api/fetcher.ts#L114-L126)         | API 401 → `reauthenticateEhmSession()` → 重试请求 |

**认证场景汇总**：

| 场景                               | 认证方式       | 预期行为                                         |
| ---------------------------------- | -------------- | ------------------------------------------------ |
| 浏览器直接打开 deep-link（已登录） | Session Cookie | 直接进入目标页面                                 |
| 浏览器直接打开 deep-link（未登录） | Session Cookie | 重定向到 `/login?next=<原始路径>`，登录后跳回    |
| 会话已过期                         | Session Cookie | API 返回 401 → 2s 后重定向到登录页               |
| EHM 系统跳转（已持有 EHM 会话）    | EHM Token      | 构造 `/login?next=...&ehm_token=...`，自动免登   |
| EHM iframe 嵌入（Cookie 已预置）   | EHM Cookie     | `getServerEhmToken()` 直接恢复用户，跳过登录页   |
| EHM Token 过期                     | EHM Token      | 登录页显示 token 无效错误，清除 `ehm_token` 参数 |

**调用方验证方式**

```
Session Cookie：
1. 在未登录/无痕窗口中打开任意 deep-link URL
2. 确认页面重定向到 /login?next=...
3. 完成登录后，自动跳回目标页面
4. 确认查询参数完整保留

EHM Token：
1. 在已登录的 EHM 系统中点击包含 ehm_token 的链接
2. 确认页面不出现登录表单，直接跳转到 deep-link 目标页面
3. 若 ehm_token 已过期，应看到 "token 无效或已过期" 提示
```

### 通用参数（所有接口适用）

| 参数        | 类型   | 必填 | 约束        | 说明                                                                   |
| ----------- | ------ | ---- | ----------- | ---------------------------------------------------------------------- |
| `prompt`    | string | 否   | ≤ 2000 字符 | 消息文本。不带 `auto_send` 时仅预填输入框；带 `auto_send=1` 时自动发送 |
| `auto_send` | string | 否   | 仅 `"1"`    | 是否自动发送。非 `"1"` 的任何值视为不自动发送                          |
| `source`    | string | 否   | ≤ 100 字符  | 来源系统标识，写入日志 `[DeepLink] source=<value>`                     |
| `context`   | string | 否   | ≤ 500 字符  | 业务上下文 key，透传至 Agent，用于结果关联                             |
| `launch_id` | string | 否   | ≤ 100 字符  | 启动会话 ID。用于刷新恢复已创建 thread；不透传给 Agent                 |

### 参数校验规则（通用）

| 规则                                                   | 违规时行为           |
| ------------------------------------------------------ | -------------------- |
| 长度超限（prompt ≤ 2000，source ≤ 100，context ≤ 500） | 截断至最大长度       |
| 透传参数值超过 500 字符                                | 丢弃该参数           |
| 含控制字符 `\x00-\x08 \x0B \x0C \x0E-\x1F \x7F`        | 自动过滤             |
| 纯空白字符串                                           | 视为未提供           |
| `auto_send` 值 ≠ `"1"`                                 | 视为 `false`，仅预填 |

> **校验归属说明**：上文"通用参数"和"参数校验规则（通用）"中的规则由前端执行。各接口表格中列出的业务校验规则（如 `device_id` 的正则格式、日期字段格式等）由 **Agent 侧**（SOUL.md）在收到消息后校验，前端只做透传——非法值不会被前端拦截，而是由 Agent 判定后静默回退到表单交互流程。

---

## 接口列表

### 1. 通用对话

创建新对话并可预填/自动发送消息，不指定 Agent。

```
GET /workspace/chats/new
```

**参数**

仅通用参数，无额外参数。

**请求示例**

```
GET /workspace/chats/new?prompt=%E5%88%86%E6%9E%90%E5%85%A8%E5%8E%82%E6%9C%AC%E6%9C%88%E8%AE%BE%E5%A4%87%E5%8F%AF%E7%94%A8%E7%8E%87&auto_send=1&source=portal
```

即：

```
/workspace/chats/new?prompt=分析全厂本月设备可用率&auto_send=1&source=portal
```

**EHM 免登示例**

```
GET /login
  ?next=<encodeURIComponent(/workspace/chats/new?prompt=分析全厂本月设备可用率&auto_send=1&source=portal)>
  &ehm_token=<EHM_JWT>
  &ehm_user=<base64_user_info>
```

**调用方验证方式**

```
1. 在已登录 DeerFlow 的浏览器中打开上述 URL
2. 页面应自动创建新对话，消息已发送且内容为 "分析全厂本月设备可用率"
3. 浏览器控制台应出现 [DeepLink] source=portal
```

---

### 2. 机泵故障诊断

```
GET /workspace/agents/fault-diagnosis--pump/chats/new
```

**参数**

除通用参数外：

| 参数             | 类型   | 必填 | 校验规则                       | 说明                |
| ---------------- | ------ | ---- | ------------------------------ | ------------------- |
| `device_id`      | string | 否\* | `^[A-Za-z0-9_-]+$`，≤ 100 字符 | 设备 ID             |
| `component_id`   | string | 否\* | `^[A-Za-z0-9_-]+$`，≤ 100 字符 | 子设备/部件/测点 ID |
| `diagnosis_date` | string | 否\* | `^\d{4}-\d{2}-\d{2}$`          | 诊断日期            |
| `diagnosis_hour` | string | 否\* | `"0"` ~ `"23"`                 | 诊断小时            |

> \* 四个参数**全部填写且校验通过**时，Agent 跳过交互表单直接执行诊断。任一缺失或校验失败则回退到正常的交互流程（弹出设备选择器让用户手动选择）。

**请求示例**

```
GET /workspace/agents/fault-diagnosis--pump/chats/new
  ?device_id=P-203A
  &component_id=Bearing-1
  &diagnosis_date=2026-06-01
  &diagnosis_hour=8
  &auto_send=1
  &source=grafana-alerting
  &context=alert-12345
```

**EHM 免登示例**（外部系统跳转，无需用户手动登录）

```
GET /login
  ?next=%2Fworkspace%2Fagents%2Ffault-diagnosis--pump%2Fchats%2Fnew%3Fdevice_id%3DP-203A%26component_id%3DBearing-1%26diagnosis_date%3D2026-06-01%26diagnosis_hour%3D8%26auto_send%3D1%26source%3Dgrafana-alerting%26context%3Dalert-12345
  &ehm_token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
  &ehm_user=eyJpZCI6IjEwMDAiLCJ1c2VyX25hbWUiOiJ6aGFuZ3NhbiIsInJlYWxfbmFtZSI6IuW8oOS4iSIsIm9yZ19pZCI6Ijk5OSJ9
```

> `ehm_token` 为 EHM 签发的 JWT（payload: `{id, exp, iat}`），`ehm_user` 为 base64 编码的用户信息 JSON（`{id, user_name, real_name, org_id}`）。登录页校验通过后自动跳回 deep-link 页面。

**调用方验证方式**

```
1. 在已登录的浏览器中打开上述 URL
2. 页面标题应显示 "机泵故障诊断" Agent 徽章
3. 若无报错且开始生成诊断报告，则参数解析成功
4. 浏览器控制台应出现 [DeepLink] source=grafana-alerting
5. 若 URL 中 device_id 改为非法值（如 "P-203;rm"），Agent 应回退到弹出设备选择器的交互流程
```

---

### 3. 旋转机组故障诊断

```
GET /workspace/agents/fault-diagnosis--rotating/chats/new
```

**参数**

| 参数             | 类型   | 必填 | 校验规则                       | 说明           |
| ---------------- | ------ | ---- | ------------------------------ | -------------- |
| `device_id`      | string | 否\* | `^[A-Za-z0-9_-]+$`，≤ 100 字符 | 设备 ID        |
| `component_id`   | string | 否\* | `^[A-Za-z0-9_-]+$`，≤ 100 字符 | 子设备/测点 ID |
| `diagnosis_date` | string | 否\* | `^\d{4}-\d{2}-\d{2}$`          | 诊断日期       |
| `diagnosis_hour` | string | 否\* | `"0"` ~ `"23"`                 | 诊断小时       |

> \* 规则同机泵诊断：四参数齐全且校验通过则直达诊断，否则回退交互。

**请求示例**

```
GET /workspace/agents/fault-diagnosis--rotating/chats/new
  ?device_id=T-501A
  &component_id=DE-Bearing
  &diagnosis_date=2026-06-01
  &diagnosis_hour=14
  &auto_send=1
  &source=dcs-alert
```

**EHM 免登示例**

```
GET /login
  ?next=<encodeURIComponent(/workspace/agents/fault-diagnosis--rotating/chats/new?device_id=T-501A&component_id=DE-Bearing&diagnosis_date=2026-06-01&diagnosis_hour=14&auto_send=1&source=dcs-alert)>
  &ehm_token=<EHM_JWT>
  &ehm_user=<base64_user_info>
```

**调用方验证方式**

```
同机泵诊断。将 agent_name 替换为 fault-diagnosis--rotating，参数规则一致。
```

---

### 4. 往复机故障诊断

```
GET /workspace/agents/fault-diagnosis--reciprocating/chats/new
```

**参数**

| 参数             | 类型   | 必填 | 校验规则                       | 说明                |
| ---------------- | ------ | ---- | ------------------------------ | ------------------- |
| `device_id`      | string | 否\* | `^[A-Za-z0-9_-]+$`，≤ 100 字符 | 设备 ID             |
| `component_id`   | string | 否\* | `^[A-Za-z0-9_-]+$`，≤ 100 字符 | 子设备/气缸/测点 ID |
| `diagnosis_date` | string | 否\* | `^\d{4}-\d{2}-\d{2}$`          | 诊断日期            |
| `diagnosis_hour` | string | 否\* | `"0"` ~ `"23"`                 | 诊断小时            |

> \* 规则同上。

**请求示例**

```
GET /workspace/agents/fault-diagnosis--reciprocating/chats/new
  ?device_id=R-301
  &component_id=Cyl-1
  &diagnosis_date=2026-05-31
  &diagnosis_hour=6
  &auto_send=1
  &source=plc-alert
```

**EHM 免登示例**

```
GET /login
  ?next=<encodeURIComponent(/workspace/agents/fault-diagnosis--reciprocating/chats/new?device_id=R-301&component_id=Cyl-1&diagnosis_date=2026-05-31&diagnosis_hour=6&auto_send=1&source=plc-alert)>
  &ehm_token=<EHM_JWT>
  &ehm_user=<base64_user_info>
```

**调用方验证方式**

```
同机泵诊断。将 agent_name 替换为 fault-diagnosis--reciprocating。
```

---

### 5. 监测分析

```
GET /workspace/agents/monitoring-analysis/chats/new
```

**参数**

除通用参数外：

| 参数               | 类型   | 必填   | 校验规则                                            | 说明                                   |
| ------------------ | ------ | ------ | --------------------------------------------------- | -------------------------------------- |
| `point_ids`        | string | **是** | 逗号分隔的非空字符串                                | 测点 ID 列表，如 `140529abc,140529def` |
| `device_id`        | string | 否     | —                                                   | 设备 ID，用于辅助定位                  |
| `device_type`      | string | 否     | —                                                   | 设备类型编码                           |
| `date_start`       | string | **是** | `^\d{4}-\d{2}-\d{2}$`                               | 开始日期，如 `2026-05-01`              |
| `date_end`         | string | **是** | `^\d{4}-\d{2}-\d{2}$`，且 `date_end` > `date_start` | 结束日期，如 `2026-06-01`              |
| `include_waveform` | string | 否     | —                                                   | 是否包含波形数据                       |
| `analysis_focus`   | string | 否     | —                                                   | 分析侧重点，如 `full`                  |

> \* `point_ids` + `date_start` + `date_end` 三参数**全部填写且校验通过**时，Agent 跳过测点选择表单直接执行数据获取与分析。任一缺失或校验失败则回退到正常的表单交互流程（渲染测点多选器让用户手动选择）。

**请求示例**

```
GET /workspace/agents/monitoring-analysis/chats/new
  ?point_ids=140529abc,140529def
  &device_id=12345
  &device_type=1
  &date_start=2026-05-01
  &date_end=2026-06-01
  &include_waveform=true
  &analysis_focus=full
  &auto_send=1
  &source=monitoring-dashboard
```

**EHM 免登示例**

```
GET /login
  ?next=<encodeURIComponent(/workspace/agents/monitoring-analysis/chats/new?point_ids=140529abc,140529def&device_id=12345&date_start=2026-05-01&date_end=2026-06-01&auto_send=1&source=monitoring-dashboard)>
  &ehm_token=<EHM_JWT>
  &ehm_user=<base64_user_info>
```

**调用方验证方式**

```
1. 在已登录浏览器中打开上述 URL
2. 页面应自动创建新对话，Agent 跳过测点选择器直接拉取数据并分析
3. 若 point_ids 缺失，Agent 应回退到测点多选器交互
4. 若 date_start / date_end 缺失或格式非法，Agent 应回退到测点多选器交互
```

---

### 6. 缺陷闭环

```
GET /workspace/agents/defect-workflow-closure/chats/new
```

该入口接入的是 EHM 闭环平台的 **缺陷流程待办**，不是旧版 DeerFlow 内部 Closure Ticket。旧入口 `/workspace/agents/defect-closure/chats/new` 已从左侧导航隐藏，不建议外部系统继续集成。

**参数**

除通用参数外：

| 参数        | 类型   | 必填 | 校验规则                       | 说明                                                                                                        |
| ----------- | ------ | ---- | ------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| `task_id`   | string | 否   | `^[A-Za-z0-9_-]+$`，≤ 100 字符 | 当前流程任务 ID。用于优先匹配并自动打开当前用户待办中的目标行                                               |
| `defect_id` | string | 否   | `^[A-Za-z0-9_-]+$`，≤ 100 字符 | 闭环平台缺陷业务 ID。`task_id` 未命中时作为第二优先级匹配条件                                               |
| `defect_no` | string | 否   | ≤ 100 字符                     | 缺陷编号，如 `QX20260621-C158E400`。作为第三优先级匹配条件和页面提示文案                                    |
| `auto_open` | string | 否   | 仅 `"1"`                       | 是否在待办列表加载后自动选中匹配行并打开详情                                                                |
| `mode`      | string | 否   | `todo` / `view` / `assist`     | `todo` 表示查看待办列表；`view` 表示引导查看某条缺陷；`assist` 表示围绕当前缺陷辅助查询设备/测点/报警等信息 |

> **当前行为说明**：打开该入口后，页面会立即展示当前登录用户的“缺陷待办”列表。若 URL 携带 `auto_open=1` 和目标参数，AI 工作台会在当前用户已加载的待办列表中按 `task_id` → `defect_id` → `defect_no` 的优先级匹配，命中后自动选中该行并打开详情。当前选中缺陷会进入后续对话上下文。
>
> **直达选中限制**：自动打开只针对当前登录用户待办列表中已经加载出来的行。未命中时不会仅凭 URL 中的 `defect_id` 直接调用详情接口，而是保留待办列表并提示目标缺陷未在当前用户待办中找到。系统不会自动提交、认领、驳回或通过任务；办理动作必须由用户在页面按钮上明确触发。

**请求示例**

```
# 打开我的缺陷待办列表
GET /workspace/agents/defect-workflow-closure/chats/new
  ?auto_send=1
  &source=ehm-defect-management

# EHM 缺陷管理页“AI分析”推荐跳转：自动定位并打开详情
GET /workspace/agents/defect-workflow-closure/chats/new
  ?task_id=90296
  &defect_id=1781744317660112
  &defect_no=QX20260621-C158E400
  &mode=view
  &auto_open=1
  &launch_id=ehm-defect-20260625-001
  &source=ehm-defect-management

# 进入缺陷闭环并请求辅助查询当前缺陷绑定设备的监测信息
GET /workspace/agents/defect-workflow-closure/chats/new
  ?mode=assist
  &prompt=%E5%9C%A8%E6%88%91%E9%80%89%E4%B8%AD%E7%BC%BA%E9%99%B7%E5%90%8E%EF%BC%8C%E8%AF%B7%E5%9F%BA%E4%BA%8E%E7%BB%91%E5%AE%9A%E8%AE%BE%E5%A4%87%E5%B8%AE%E6%88%91%E6%9F%A5%E8%AF%A2%E6%B5%8B%E7%82%B9%E5%92%8C%E6%8A%A5%E8%AD%A6%E4%BF%A1%E6%81%AF
  &auto_send=1
  &source=ehm-defect-management
```

**EHM 免登示例**

```
GET /login
  ?next=<encodeURIComponent(/workspace/agents/defect-workflow-closure/chats/new?task_id=90296&defect_id=1781744317660112&defect_no=QX20260621-C158E400&mode=view&auto_open=1&launch_id=ehm-defect-20260625-001&source=ehm-defect-management)>
  &ehm_token=<EHM_JWT>
  &ehm_user=<base64_user_info>
```

**调用方验证方式**

```
1. 在已登录浏览器中打开 /workspace/agents/defect-workflow-closure/chats/new
2. 页面左侧 Agent 徽章应显示“缺陷闭环”
3. 页面应自动展示当前登录用户的缺陷待办列表
4. 若 URL 携带 task_id / defect_id / defect_no / auto_open=1 且目标行在当前待办列表中，页面应自动选中该行并打开详情
5. 详情区域应展示缺陷详情、历史处理记录和当前节点区域
6. 若当前节点为“待认领”，当前节点表单不应展示，只展示认领入口；认领后再展示表单
7. 若当前节点已认领，页面应展示当前节点表单和平台返回的可操作按钮
8. 选中详情后发送“当前缺陷绑定的设备 ID 是什么”，Agent 应基于当前选中缺陷上下文回答
9. 若目标行不在当前用户已加载待办列表中，页面应保留待办列表并提示未找到目标缺陷，不应直接打开详情
```

---

### 7. 日报

```
GET /workspace/agents/ai-report--daily/chats/new
```

**参数**

除通用参数外：

| 参数               | 类型   | 必填   | 校验规则                                                                               | 说明                                                                                                         |
| ------------------ | ------ | ------ | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `template_id`      | string | **是** | ≤ 100 字符                                                                             | 报告模板 ID，如 `daily-equipment`                                                                            |
| `report_date`      | string | **是** | `^\d{4}-\d{2}-\d{2}$`                                                                  | 报告日期                                                                                                     |
| `equipment_type`   | string | 否     | `all` / `static_equipment` / `rotating_machinery` / `pump` / `reciprocating_machinery` | 设备类型，默认 `all`                                                                                         |
| `compare_with`     | string | 否     | `previous_day` / `previous_week` / `none`                                              | 对比基准，默认 `previous_day`                                                                                |
| `equipment_ids`    | string | 否     | `^[A-Za-z0-9_-]+(,[A-Za-z0-9_-]+)*$`                                                   | 逗号分隔的设备 ID，默认全部设备                                                                              |
| `equipment_labels` | string | 否     | —                                                                                      | 逗号分隔的设备名称，与 `equipment_ids` 一一对应。仅 `equipment_ids` 提供时有效；缺省时用设备 ID 作为显示名称 |
| `kpi_keys`         | string | 否     | `^[a-z_]+(,[a-z_]+)*$`                                                                 | 逗号分隔的 KPI 列表，如 `runtime_rate,alarm_count`。默认按模板勾选                                           |

> \* `template_id` + `report_date` 两参数**全部填写且校验通过**时，Agent 跳过交互表单直接执行完整报告生成。可选参数提供时覆盖表单默认值，全部缺省则使用模板默认值。

**请求示例**

```text
# 最小参数（使用模板默认值）
GET /workspace/agents/ai-report--daily/chats/new
  ?template_id=daily-equipment
  &report_date=2026-06-01
  &auto_send=1
  &source=report-scheduler

# 全参数（指定设备类型、对比基准、设备列表和 KPI）
GET /workspace/agents/ai-report--daily/chats/new
  ?template_id=daily-equipment
  &report_date=2026-06-01
  &equipment_type=rotating_machinery
  &compare_with=previous_week
  &equipment_ids=T-501A,T-501B
  &equipment_labels=循环氢压缩机T-501A,进料泵T-501B
  &kpi_keys=runtime_rate,alarm_count
  &auto_send=1
  &source=report-scheduler
```

**EHM 免登示例**

```
GET /login
  ?next=<encodeURIComponent(/workspace/agents/ai-report--daily/chats/new?template_id=daily-equipment&report_date=2026-06-01&auto_send=1&launch_id=ehm-report-20260625-001&source=report-scheduler)>
  &ehm_token=<EHM_JWT>
  &ehm_user=<base64_user_info>
```

**调用方验证方式**

```
1. 在已登录浏览器中打开上述 URL
2. Agent 应自动使用 daily-equipment 模板和指定日期直达报告生成，无需任何表单交互
3. 若 template_id 不存在，Agent 应回退到模板选择流程
4. 若 report_date 缺失，Agent 应回退到日期表单流程
```

---

### 8. 周报

```
GET /workspace/agents/ai-report--weekly/chats/new
```

**参数**

除通用参数外：

| 参数               | 类型   | 必填   | 校验规则                                                                               | 说明                                                                                                         |
| ------------------ | ------ | ------ | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `template_id`      | string | **是** | ≤ 100 字符                                                                             | 报告模板 ID，如 `weekly-equipment`                                                                           |
| `week_start`       | string | **是** | `^\d{4}-\d{2}-\d{2}$`                                                                  | 周报开始日期                                                                                                 |
| `date_end`         | string | **是** | `^\d{4}-\d{2}-\d{2}$`                                                                  | 周报结束日期，必须 ≥ `week_start`。仅用于校验，不传入模板                                                    |
| `equipment_type`   | string | 否     | `all` / `static_equipment` / `rotating_machinery` / `pump` / `reciprocating_machinery` | 设备类型，默认 `all`                                                                                         |
| `compare_with`     | string | 否     | `previous_week` / `previous_year` / `none`                                             | 对比基准，默认 `previous_week`                                                                               |
| `equipment_ids`    | string | 否     | `^[A-Za-z0-9_-]+(,[A-Za-z0-9_-]+)*$`                                                   | 逗号分隔的设备 ID，默认全部设备                                                                              |
| `equipment_labels` | string | 否     | —                                                                                      | 逗号分隔的设备名称，与 `equipment_ids` 一一对应。仅 `equipment_ids` 提供时有效；缺省时用设备 ID 作为显示名称 |
| `kpi_keys`         | string | 否     | `^[a-z_]+(,[a-z_]+)*$`                                                                 | 逗号分隔的 KPI 列表，如 `runtime_rate,alarm_count`。默认按模板勾选                                           |

> \* `template_id` + `week_start` + `date_end` 三参数**全部填写且校验通过**时，Agent 跳过交互表单直接执行报告生成直到导出完成。可选参数提供时覆盖表单默认值。

**请求示例**

```text
# 最小参数（使用模板默认值）
GET /workspace/agents/ai-report--weekly/chats/new
  ?template_id=weekly-equipment
  &week_start=2026-05-25
  &date_end=2026-06-01
  &auto_send=1
  &source=report-scheduler

# 全参数（指定设备类型、对比基准、设备列表和 KPI）
GET /workspace/agents/ai-report--weekly/chats/new
  ?template_id=weekly-equipment
  &week_start=2026-05-25
  &date_end=2026-06-01
  &equipment_type=pump
  &compare_with=previous_year
  &equipment_ids=P-203A,P-204B
  &equipment_labels=进料泵P-203A,回流泵P-204B
  &kpi_keys=runtime_rate,alarm_count
  &auto_send=1
  &source=report-scheduler
```

**EHM 免登示例**

```
GET /login
  ?next=<encodeURIComponent(/workspace/agents/ai-report--weekly/chats/new?template_id=weekly-equipment&week_start=2026-05-25&date_end=2026-06-01&auto_send=1&launch_id=ehm-report-20260625-002&source=report-scheduler)>
  &ehm_token=<EHM_JWT>
  &ehm_user=<base64_user_info>
```

**调用方验证方式**

```
1. 在已登录浏览器中打开上述 URL
2. Agent 应自动使用 weekly-equipment 模板和指定日期范围直达报告生成，无需任何表单交互
3. 若 template_id 不存在，Agent 应回退到模板选择流程
4. 若 week_start 或 date_end 缺失，Agent 应回退到日期表单流程
```

---

### 9. 月报

```
GET /workspace/agents/ai-report--monthly/chats/new
```

**参数**

除通用参数外：

| 参数               | 类型   | 必填   | 校验规则                                                                               | 说明                                                                                                         |
| ------------------ | ------ | ------ | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `template_id`      | string | **是** | ≤ 100 字符                                                                             | 报告模板 ID，如 `monthly-equipment`                                                                          |
| `report_month`     | string | **是** | `^\d{4}-\d{2}$`                                                                        | 报告月份，如 `2026-06`                                                                                       |
| `equipment_type`   | string | 否     | `all` / `static_equipment` / `rotating_machinery` / `pump` / `reciprocating_machinery` | 设备类型，默认 `all`                                                                                         |
| `compare_with`     | string | 否     | 逗号分隔：`mom` / `yoy` / `none`。`none` 不可与其他值并存                              | 对比基准（可多选），默认 `mom`                                                                               |
| `equipment_ids`    | string | 否     | `^[A-Za-z0-9_-]+(,[A-Za-z0-9_-]+)*$`                                                   | 逗号分隔的设备 ID，默认全部设备                                                                              |
| `equipment_labels` | string | 否     | —                                                                                      | 逗号分隔的设备名称，与 `equipment_ids` 一一对应。仅 `equipment_ids` 提供时有效；缺省时用设备 ID 作为显示名称 |
| `kpi_keys`         | string | 否     | `^[a-z_]+(,[a-z_]+)*$`                                                                 | 逗号分隔的 KPI 列表，如 `runtime_rate,mtbf,mttr,target_rate`。默认按模板勾选                                 |

> \* `template_id` + `report_month` 两参数**全部填写且校验通过**时，Agent 跳过交互表单直接执行报告生成直到导出完成。可选参数提供时覆盖表单默认值。

**请求示例**

```text
# 最小参数（使用模板默认值）
GET /workspace/agents/ai-report--monthly/chats/new
  ?template_id=monthly-equipment
  &report_month=2026-06
  &auto_send=1
  &source=report-scheduler

# 全参数（指定设备类型、环比+同比、设备列表和 KPI）
GET /workspace/agents/ai-report--monthly/chats/new
  ?template_id=monthly-equipment
  &report_month=2026-06
  &equipment_type=static_equipment
  &compare_with=mom,yoy
  &equipment_ids=V-401,V-402
  &equipment_labels=高压分离器V-401,低压分离器V-402
  &kpi_keys=runtime_rate,mtbf,mttr,target_rate
  &auto_send=1
  &source=report-scheduler
```

**EHM 免登示例**

```
GET /login
  ?next=<encodeURIComponent(/workspace/agents/ai-report--monthly/chats/new?template_id=monthly-equipment&report_month=2026-06&auto_send=1&launch_id=ehm-report-20260625-003&source=report-scheduler)>
  &ehm_token=<EHM_JWT>
  &ehm_user=<base64_user_info>
```

**调用方验证方式**

```
1. 在已登录浏览器中打开上述 URL
2. Agent 应自动使用 monthly-equipment 模板和指定月份直达报告生成，无需任何表单交互
3. 若 template_id 不存在，Agent 应回退到模板选择流程
4. 若 report_month 缺失，Agent 应回退到月份表单流程
```

---

### 10. 旋转机组异常研判

```
GET /workspace/agents/abnormal-judgment--rotating/chats/new
```

**参数**

除通用参数外，可传入任意业务参数（如 `device_id`、`anomaly_type`、`start_time`、`end_time` 等）。

> **⚠️ 直达执行暂未实现**：该 Agent（[abnormal-judgment--rotating/SOUL.md](agents/builtin/abnormal-judgment--rotating/SOUL.md)）尚未在 SOUL.md 中解析 `<deep_link_params>` 块。所有参数会经前端透传至 Agent 的 `additional_kwargs`，但 **Agent 不会根据参数直达执行**，而是始终走正常交互流程（渲染异常列表选择器）。待 Agent 端实现 deep-link 直达逻辑后，本节内容将补充更新。

**请求示例**

```http
GET /workspace/agents/abnormal-judgment--rotating/chats/new
  ?device_id=E-301
  &anomaly_type=vibration_spike
  &start_time=2026-06-01T06:00:00
  &end_time=2026-06-01T10:00:00
  &auto_send=1
  &source=prometheus-alertmanager
```

**EHM 免登示例**

```http
GET /login
  ?next=<encodeURIComponent(/workspace/agents/abnormal-judgment--rotating/chats/new?device_id=E-301&anomaly_type=vibration_spike&start_time=2026-06-01T06:00:00&end_time=2026-06-01T10:00:00&auto_send=1&source=prometheus-alertmanager)>
  &ehm_token=<EHM_JWT>
  &ehm_user=<base64_user_info>
```

**调用方验证方式**

```text
1. 在已登录浏览器中打开上述 URL
2. Agent 应自动创建对话并渲染异常列表选择器（用户需手动选择事件）
3. 传入的参数会出现在消息的 additional_kwargs 中，供后续研判参考
4. 直达执行能力待 Agent 端补充 deep_link_params 解析后上线
```

---

### 11. CRM 分析师

```
GET /workspace/agents/crm-analyst/chats/new
```

**参数**

除通用参数外，可传入以下业务参数：

| 参数         | 类型   | 必填 | 校验规则              | 说明                                                         |
| ------------ | ------ | ---- | --------------------- | ------------------------------------------------------------ |
| `query_type` | string | 否   | ≤ 100 字符            | 查询类型：`product_shipment` / `service_events` / `combined` |
| `date_range` | string | 否   | ≤ 100 字符            | 时间范围：`last_7d` / `last_30d` / `last_90d` / `custom`     |
| `date_start` | string | 否   | `^\d{4}-\d{2}-\d{2}$` | 自定义开始日期（date_range=custom 时使用）                   |
| `date_end`   | string | 否   | `^\d{4}-\d{2}-\d{2}$` | 自定义结束日期（date_range=custom 时使用）                   |

> **⚠️ 直达执行暂未实现**：该 Agent（[crm-analyst/SOUL.md](agents/builtin/crm-analyst/SOUL.md)）尚未在 SOUL.md 中解析 `<deep_link_params>` 块。所有参数会经前端透传至 Agent 的 `additional_kwargs`，但 **Agent 不会根据参数直达执行**，而是始终走正常交互流程（用户需手动输入查询意图）。待 Agent 端实现 deep-link 直达逻辑后，本节内容将补充更新。

**请求示例**

```http
GET /workspace/agents/crm-analyst/chats/new
  ?query_type=service_events
  &date_range=last_30d
  &auto_send=1
  &prompt=%E6%9F%A5%E8%AF%A2%E6%9C%8D%E5%8A%A1%E4%BA%8B%E4%BB%B6%E5%B9%B6%E6%A3%80%E6%B5%8B%E5%BC%82%E5%B8%B8
  &source=sap-erp
```

> 即 `prompt=查询服务事件并检测异常`

**EHM 免登示例**

```http
GET /login
  ?next=<encodeURIComponent(/workspace/agents/crm-analyst/chats/new?query_type=service_events&date_range=last_30d&auto_send=1&source=sap-erp)>
  &ehm_token=<EHM_JWT>
  &ehm_user=<base64_user_info>
```

**调用方验证方式**

```text
1. 在已登录浏览器中打开上述 URL
2. Agent 应自动创建对话并等待用户输入查询意图
3. 传入的参数会出现在消息的 additional_kwargs 中，供后续查询参考
4. 直达执行能力待 Agent 端补充 deep_link_params 解析后上线
```

---

## 自定义参数透传

**除上述文档列出的参数外，任何额外参数均自动透传给 Agent。** Agent 在 SOUL.md 中定义自己接受的参数契约。前端不做业务级别的校验——参数值仅做通用校验（长度、控制字符），业务校验由 Agent 自行处理。

示例：如果未来新增一个 "振动频谱分析" Agent，调用方可以直接传自定义参数：

```
GET /workspace/agents/vibration-spectrum/chats/new
  ?device_id=XX-123
  &frequency_range=0-1000Hz
  &window_type=hamming
  &auto_send=1
```

前端自动将 `frequency_range` 和 `window_type` 透传到消息的 `additional_kwargs` 中。

---

## 集成代码示例

### JavaScript (Grafana Webhook)

```javascript
const DEERFLOW_HOST = "https://deerflow.example.com";

function buildDiagnosisUrl(alert) {
  const alertTime = new Date(alert.startsAt);
  const params = new URLSearchParams({
    device_id: alert.labels.device_id,
    component_id: alert.labels.component_id,
    diagnosis_date: alertTime.toISOString().slice(0, 10),
    diagnosis_hour: String(alertTime.getHours()),
    auto_send: "1",
    source: "grafana-alerting",
    context: alert.fingerprint,
  });
  return `${DEERFLOW_HOST}/workspace/agents/fault-diagnosis--pump/chats/new?${params}`;
}

// EHM 免登方式：构造 /login URL 携带 ehm_token
function buildEhmDiagnosisUrl(alert, ehmToken, ehmUserBase64) {
  const deepLink = `/workspace/agents/fault-diagnosis--pump/chats/new?${new URLSearchParams(
    {
      device_id: alert.labels.device_id,
      component_id: alert.labels.component_id,
      diagnosis_date: new Date(alert.startsAt).toISOString().slice(0, 10),
      diagnosis_hour: String(new Date(alert.startsAt).getHours()),
      auto_send: "1",
      source: "grafana-alerting",
      context: alert.fingerprint,
    },
  )}`;
  return `${DEERFLOW_HOST}/login?${new URLSearchParams({
    next: deepLink,
    ehm_token: ehmToken,
    ehm_user: ehmUserBase64,
  })}`;
}
```

### Go (Prometheus AlertManager)

```go
func BuildMonitoringDeepLink(alert *Alert) string {
    params := url.Values{
        "point_ids":  {alert.Labels["point_ids"]},
        "device_id":  {alert.Labels["device_id"]},
        "date_start": {alert.StartsAt.Format("2006-01-02")},
        "date_end":   {time.Now().Format("2006-01-02")},
        "auto_send":  {"1"},
        "source":     {"prometheus-alertmanager"},
        "context":    {fmt.Sprintf("%x", alert.Fingerprint)},
    }
    return "https://deerflow.example.com/workspace/agents/monitoring-analysis/chats/new?" + params.Encode()
}

// EHM 免登方式：构造 /login URL
func BuildEhmMonitoringDeepLink(alert *Alert, ehmToken string, ehmUserBase64 string) string {
    deepLink := "/workspace/agents/monitoring-analysis/chats/new?" + url.Values{
        "point_ids":  {alert.Labels["point_ids"]},
        "device_id":  {alert.Labels["device_id"]},
        "date_start": {alert.StartsAt.Format("2006-01-02")},
        "date_end":   {time.Now().Format("2006-01-02")},
        "auto_send":  {"1"},
        "source":     {"prometheus-alertmanager"},
    }.Encode()
    loginParams := url.Values{
        "next":      {deepLink},
        "ehm_token": {ehmToken},
        "ehm_user":  {ehmUserBase64},
    }
    return "https://deerflow.example.com/login?" + loginParams.Encode()
}
```

### Python (定时调度)

```python
from urllib.parse import urlencode

HOST = "https://deerflow.example.com"


def build_daily_report_url(
    template: str,
    report_date: str,
    *,
    equipment_type: str | None = None,
    compare_with: str | None = None,
    equipment_ids: str | None = None,
    equipment_labels: str | None = None,
    kpi_keys: str | None = None,
) -> str:
    params: dict[str, str] = {
        "template_id": template,
        "report_date": report_date,
        "auto_send": "1",
        "source": "report-scheduler",
    }
    if equipment_type:
        params["equipment_type"] = equipment_type
    if compare_with:
        params["compare_with"] = compare_with
    if equipment_ids:
        params["equipment_ids"] = equipment_ids
    if equipment_labels:
        params["equipment_labels"] = equipment_labels
    if kpi_keys:
        params["kpi_keys"] = kpi_keys
    return f"{HOST}/workspace/agents/ai-report--daily/chats/new?{urlencode(params)}"


def build_weekly_report_url(
    template: str,
    week_start: str,
    date_end: str,
    *,
    equipment_type: str | None = None,
    compare_with: str | None = None,
    equipment_ids: str | None = None,
    equipment_labels: str | None = None,
    kpi_keys: str | None = None,
) -> str:
    params: dict[str, str] = {
        "template_id": template,
        "week_start": week_start,
        "date_end": date_end,
        "auto_send": "1",
        "source": "report-scheduler",
    }
    if equipment_type:
        params["equipment_type"] = equipment_type
    if compare_with:
        params["compare_with"] = compare_with
    if equipment_ids:
        params["equipment_ids"] = equipment_ids
    if equipment_labels:
        params["equipment_labels"] = equipment_labels
    if kpi_keys:
        params["kpi_keys"] = kpi_keys
    return f"{HOST}/workspace/agents/ai-report--weekly/chats/new?{urlencode(params)}"


def build_monthly_report_url(
    template: str,
    report_month: str,
    *,
    equipment_type: str | None = None,
    compare_with: str | None = None,
    equipment_ids: str | None = None,
    equipment_labels: str | None = None,
    kpi_keys: str | None = None,
) -> str:
    params: dict[str, str] = {
        "template_id": template,
        "report_month": report_month,
        "auto_send": "1",
        "source": "report-scheduler",
    }
    if equipment_type:
        params["equipment_type"] = equipment_type
    if compare_with:
        params["compare_with"] = compare_with
    if equipment_ids:
        params["equipment_ids"] = equipment_ids
    if equipment_labels:
        params["equipment_labels"] = equipment_labels
    if kpi_keys:
        params["kpi_keys"] = kpi_keys
    return f"{HOST}/workspace/agents/ai-report--monthly/chats/new?{urlencode(params)}"
```

### Shell (cron)

```bash
#!/bin/bash
HOST="https://deerflow.example.com"
DATE=$(date +%Y-%m-%d)
URL="${HOST}/workspace/agents/ai-report--daily/chats/new?template_id=daily-equipment&report_date=${DATE}&auto_send=1&source=cron-scheduler"
# 通过系统默认浏览器打开
xdg-open "$URL" 2>/dev/null || open "$URL" 2>/dev/null
```

---

## 验证清单

集成方可按以下步骤逐项验证：

| #   | 验证项                                                                         | 预期结果                                         |
| --- | ------------------------------------------------------------------------------ | ------------------------------------------------ |
| 1   | 未登录状态下打开任意 deep-link URL                                             | 重定向到 `/login?next=...`，登录后跳回目标页面   |
| 2   | EHM 免登：构造 `/login?next=<deep-link>&ehm_token=<有效JWT>&ehm_user=<base64>` | 不显示登录表单，直接跳转到目标页面               |
| 3   | EHM 免登：`ehm_token` 已过期                                                   | 显示 "token 无效或已过期"，清除 `ehm_token` 参数 |
| 4   | EHM 免登：不传 `ehm_user`                                                      | 仅 token 验证通过，用户详情从后端补全            |
| 5   | `auto_send=1` + `prompt=测试`                                                  | 页面打开后自动发送 "测试"                        |
| 6   | `prompt=测试` 不带 `auto_send`                                                 | 输入框预填 "测试"，不自动发送                    |
| 7   | `auto_send=2`                                                                  | 视为不自动发送                                   |
| 8   | `prompt=<超2000字符>`                                                          | 截断至 2000 字符后发送                           |
| 9   | `device_id=P-203;rm+rf` (诊断接口)                                             | 参数透传至 Agent，Agent 校验失败后回退交互流程   |
| 10  | `diagnosis_date=2026/06/01` (诊断接口)                                         | 参数透传至 Agent，Agent 校验失败后回退交互流程   |
| 11  | 已有对话 URL 后加 `?prompt=xxx`                                                | 参数被忽略，对话正常加载                         |
| 12  | 监测分析只传 `device_id` 不传 `point_ids`                                      | Agent 回退到测点多选器交互                       |
| 13  | 控制台检查 `[DeepLink] source=<value>`                                         | source 参数正确输出到控制台                      |
