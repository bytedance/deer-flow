# 知识链路运营观察口径

> 面向技术 owner 和月度评审的观察指南。

## 观察频率

| 周期 | 关注指标 | 方式 |
|------|---------|------|
| 每日 | failed_doc_count > 0 | 巡检 Health Tab |
| 每周 | index_success_rate, retrieval_p95 | 周报引用 |
| 每月 | 全量指标趋势 | 月度评审 |

## 核心 SLA 口径

### 索引成功率 >= 95%

- **计算公式**：`ready / (ready + failed + pending + indexing + cancelled)`
- **数据来源**：知识库 Health Tab → Index Success卡片
- **低于 95%**：检查 Failure by Type 分布，定位主要失败类别
- **低于 85%**：立即排查索引服务状态，检查 embedding 服务可用性

### 检索 P95 延迟 < 500ms

- **数据来源**：知识库 Health Tab → Retrieval P95 卡片
- **500ms-2000ms**：黄色预警，检查 vector store 负载
- **> 2000ms**：红色告警，排查网络/服务瓶颈

### 失败文档数 < 5

- **数据来源**：知识库 Health Tab → Failed Docs 卡片
- **>= 5**：需要关注，按 KB 下钻定位
- **>= 20**：需要立即处理，可能存在系统性索引问题

## 下钻流程

1. 打开知识库页面 → **Health Tab**
2. 查看顶部 4 张 SLA 卡片概览
3. 如有 Failure by Type 标签，点击定位错误类别
4. 在 Per Knowledge Base 表中找到 `failed > 0` 的 KB
5. 进入该 KB 详情页查看具体失败文档

## 常见问题处理

| 症状 | 可能原因 | 处理建议 |
|------|---------|---------|
| ENCRYPTED_PDF 占比高 | 用户上传了加密 PDF | 通知用户提供解密版本 |
| DIMENSION_MISMATCH | Embedding 模型切换后未重建索引 | 重建该 KB 的索引 |
| UNSUPPORTED_FORMAT | 上传了不支持的文件格式 | 检查文件类型白名单 |
| EMPTY_RESULT | 文档解析后无文本内容 | 检查原文件是否为扫描件/图片 |
| 检索延迟升高 | vector store 负载增加 | 检查 Chroma/向量库连接池 |
| 索引成功率突降 | 上游服务异常 | 检查 embedding 服务和 MarkItDown 可用性 |

## 告警阈值参考

详见 `backend/packages/harness/deerflow/knowledge_base/thresholds.py` 中的 `RECOMMENDED_THRESHOLDS` 和 `health_check()` 函数。

| 指标 | Warning | Critical |
|------|---------|----------|
| index_success_rate | < 95% | < 85% |
| retrieval_p95_latency_ms | > 500ms | > 2000ms |
| failed_doc_count | >= 5 | >= 20 |
