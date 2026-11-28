# CHANGELOG

## v1.0.0 (2026-04-22)

DeerFlow 首发整理版（基于 OpenClaw public 分支整理）。

### 变更摘要
- 重置版本号为 `1.0.0`，用于 DeerFlow 提交起点。
- 保留核心能力：
  - 深知可信搜索素材召回
  - 公文写作流程编排
  - 普通格式 Word 排版输出
- 移除红头能力：
  - 删除 `templates/` 目录
  - 删除 `scripts/template_generator.py`
  - 删除文档中红头相关指令与说明
- 平台兼容增强：
  - 输出路径默认改为 `./output/`
  - 支持环境变量 `OFFICIAL_DOC_OUTPUT_DIR`
- 工程清理：
  - 删除平台私有元数据与缓存文件（`_meta.json`、`.clawhub/`、`scripts/__pycache__/`）
  - 新增 `requirements.txt`

### 兼容性说明
- 当前 DeerFlow 版本不包含红头公文模板处理。
- 如需红头能力，请在私有版本中维护或后续以插件能力扩展。
