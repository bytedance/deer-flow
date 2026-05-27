# 记忆设置评审

当你在本地评审 Memory Settings 的新增/编辑流程时，可按本文用最少手动步骤完成。

## 快速评审

1. 用你已有的任一可用开发方式在本地启动 DeerFlow。

   例如：

   ```bash
   make dev
   ```

   或

   ```bash
   make docker-start
   ```

   如果你本地已经运行了 DeerFlow，可直接复用现有环境。

2. 加载示例记忆数据。

   ```bash
   python scripts/load_memory_sample.py
   ```

3. 打开 `Settings > Memory`。

   本地默认地址：
   - 应用：`http://localhost:2026`
   - 仅前端回退地址：`http://localhost:3000`

## 最小手动测试

1. 点击 `Add fact`。
2. 新建一条 fact：
   - Content：`Reviewer-added memory fact`
   - Category：`testing`
   - Confidence：`0.88`
3. 确认新 fact 立即出现，且 source 显示为 `Manual`。
4. 编辑示例 fact `This sample fact is intended for edit testing.`，修改为：
   - Content：`This sample fact was edited during manual review.`
   - Category：`testing`
   - Confidence：`0.91`
5. 确认编辑后的 fact 立即更新。
6. 刷新页面，确认新增 fact 与编辑后的 fact 仍然持久化存在。

## 可选健全性检查

- 搜索 `Reviewer-added`，确认能命中新建 fact。
- 搜索 `workflow`，确认分类文本可被搜索。
- 在 `All`、`Facts`、`Summaries` 之间切换。
- 删除可丢弃样例 fact `Delete fact testing can target this disposable sample entry.`，确认列表立即更新。
- 清空所有记忆，确认页面进入空状态。

## 样例文件

- 样例数据：`backend/docs/memory-settings-sample.json`
- 本地默认运行时目标文件：`backend/.deer-flow/memory.json`

加载脚本在覆盖现有运行时记忆文件前，会自动创建带时间戳的备份。
