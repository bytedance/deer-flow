# DeerFlow 适配说明（v1.0.0）

## 目标
在不改动现有 OpenClaw public 版本的前提下，提供可提交 DeerFlow 的公开版技能。

## 当前版本定位
- 版本号：`1.0.0`
- 能力边界：可信搜索 + 公文写作 + 普通 Word 排版
- 不包含：红头模板生成

## 已完成调整
1. 新建独立副本目录，不影响原技能。
2. `SKILL.md` 补充元数据并重置版本号。
3. 删除红头相关资产：`templates/`、`scripts/template_generator.py`。
4. 文档移除红头说明，统一普通版流程。
5. 输出目录改为 DeerFlow 友好策略：
   - 优先 `OFFICIAL_DOC_OUTPUT_DIR`
   - 否则 `./output/`
6. 新增 `requirements.txt` 便于复现。
7. 清理平台私有痕迹：`_meta.json`、`.clawhub/`、`scripts/__pycache__/`。

## 最小回归测试（建议）
1. 不配置 `config.ini` 运行 `dkag_search.py`，应提示配置缺失。
2. 配置有效 `api_key` 后执行真实搜索，检查 `knowledgeBase` 字段。
3. 用最小 Markdown 调用 `format_document.py`，检查 Word 正常生成到 `./output/`。
