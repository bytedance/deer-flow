# DeerFlow 科研适配二次审计与精修提示词

> **背景**：在完成第一轮 42 项代码级科研适配后，通过全面审计发现了集成遗漏、一致性缺口和可进一步优化的空间。
> **目标**：修补所有集成断点，确保新增能力端到端可用，并进行精细化打磨。
> **已修复的关键问题**：`task_tool.py` 中 `subagent_type` 的 `Literal` 类型已扩展、SKILL.md 已更新、CLAUDE.md 已同步。

---

## 一、已完成的紧急修复（本轮已执行）

| # | 问题 | 文件 | 修复内容 |
|---|------|------|----------|
| 1 | task_tool 不识别新子代理 | `backend/src/tools/builtins/task_tool.py` | `Literal` 扩展为 5 种类型 + docstring 补充 + 错误消息更新 |
| 2 | literature-review 未引用新工具 | `skills/public/literature-review/SKILL.md` | Step 1.2 添加 "Preferred Method" 段落引导使用 built-in tools |
| 3 | academic-integrity 未引用新工具 | `skills/public/academic-integrity/SKILL.md` | Step 1.2 添加工具优先使用说明 |
| 4 | CLAUDE.md 未记录新能力 | `backend/CLAUDE.md` | 更新 Subagent + Community tools 段落 |

---

## 二、仍需完善的文件清单（按优先级排列）

### P0：功能完整性（不修会导致功能不可用）

#### 2.1 academic-writing SKILL.md 引用集成

**文件**：`skills/public/academic-writing/SKILL.md`

**问题**：长达 1318 行的学术写作技能，其引用相关段落仍使用 Python 脚本调用 API，未引导使用新的 `crossref_lookup` 和 `semantic_scholar_search` 工具。

**修改方案**：
- 找到所有使用 `urllib` 调用学术 API 的代码块
- 在每个代码块前添加 "Preferred Method" 段落，引导优先使用 built-in 工具
- 在 "Citation Integration" 章节明确说明可用 `crossref_lookup(doi="...")` 验证 DOI

#### 2.2 grant-writing SKILL.md 集成

**文件**：`skills/public/grant-writing/SKILL.md`

**问题**：基金写作技能中的文献支撑步骤仍使用脚本调用 API，未引用新工具。

**修改方案**：
- 在文献检索相关步骤中添加工具优先使用说明

#### 2.3 dataset-search SKILL.md 集成

**文件**：`skills/public/dataset-search/SKILL.md`

**问题**：数据集搜索技能可以利用 `semantic_scholar_search` 查找附带数据集的论文。

**修改方案**：
- 添加说明：可通过 `semantic_scholar_search(query="dataset for X")` 查找相关数据集论文

---

### P1：用户体验优化（不影响功能但提升体验）

#### 2.4 前端子代理类型标签

**文件**：
- `frontend/src/components/workspace/messages/subtask-card.tsx`
- `frontend/src/core/i18n/locales/zh-CN.ts`
- `frontend/src/core/i18n/locales/en-US.ts`

**问题**：前端 subtask 卡片不显示新子代理的专属标签/图标，用户无法直观区分 `literature-reviewer` 和 `general-purpose`。

**修改方案**：

```typescript
// subtask-card.tsx 中根据 subagent_type 显示标签
const SUBAGENT_LABELS: Record<string, { label: string; icon: string }> = {
  "general-purpose": { label: "General", icon: "🔧" },
  "bash": { label: "Terminal", icon: "💻" },
  "literature-reviewer": { label: "Literature", icon: "📚" },
  "statistical-analyst": { label: "Statistics", icon: "📊" },
  "code-reviewer": { label: "Code Review", icon: "🔍" },
};
```

```typescript
// zh-CN.ts
subagentTypes: {
  "general-purpose": "通用任务",
  "bash": "命令执行",
  "literature-reviewer": "文献检索",
  "statistical-analyst": "统计分析",
  "code-reviewer": "代码审查",
}

// en-US.ts
subagentTypes: {
  "general-purpose": "General Purpose",
  "bash": "Command Execution",
  "literature-reviewer": "Literature Review",
  "statistical-analyst": "Statistical Analysis",
  "code-reviewer": "Code Review",
}
```

#### 2.5 experiment-tracking SKILL.md 集成

**文件**：`skills/public/experiment-tracking/SKILL.md`

**问题**：实验追踪技能可以利用新的统计子代理进行自动结果分析。

**修改方案**：
- 在实验结果分析步骤中添加：可将结果数据交给 `statistical-analyst` 子代理进行自动化假设检验和 APA 报告

#### 2.6 deep-research SKILL.md 增强

**文件**：`skills/public/deep-research/SKILL.md`

**问题**：深度研究技能应引导使用学术 API 工具进行学术类深度研究。

**修改方案**：
- 添加"学术研究模式"分支：检测到学术研究意图时，优先使用 `semantic_scholar_search` + `arxiv_search` + `crossref_lookup`

---

### P2：质量加固（锦上添花）

#### 2.7 单元测试

**文件**（需新建）：
- `backend/tests/test_semantic_scholar_tools.py`
- `backend/tests/test_crossref_tools.py`
- `backend/tests/test_arxiv_tools.py`
- `backend/tests/test_citation_memory.py`
- `backend/tests/test_subagent_registry_academic.py`

**修改方案**：

```python
# test_semantic_scholar_tools.py（示例）
"""Tests for Semantic Scholar API tools."""
import json
from unittest.mock import MagicMock, patch

def test_semantic_scholar_search_returns_json():
    """Test that search returns valid JSON with expected fields."""
    from src.community.semantic_scholar.tools import semantic_scholar_search_tool
    # Mock httpx response
    ...

def test_semantic_scholar_search_handles_api_error():
    """Test graceful error handling on API failure."""
    ...

def test_semantic_scholar_paper_with_doi():
    """Test paper lookup by DOI."""
    ...
```

```python
# test_citation_memory.py（示例）
"""Tests for citation memory persistence."""
import json
import tempfile
from pathlib import Path

from src.agents.memory.citation_memory import (
    load_citations, save_citation, search_citations,
    remove_citation, format_for_injection, get_citation_count,
)

def test_save_and_load_citation():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    save_citation("vaswani2017", {"title": "Attention Is All You Need", "year": 2017}, store_path=path)
    store = load_citations(path)
    assert "vaswani2017" in store["citations"]
    assert store["citations"]["vaswani2017"]["year"] == 2017

def test_search_citations():
    ...

def test_remove_citation():
    ...

def test_format_for_injection_empty():
    ...
```

```python
# test_subagent_registry_academic.py（示例）
"""Tests for academic subagent registration."""
from src.subagents.builtins import BUILTIN_SUBAGENTS

def test_literature_reviewer_registered():
    assert "literature-reviewer" in BUILTIN_SUBAGENTS

def test_statistical_analyst_registered():
    assert "statistical-analyst" in BUILTIN_SUBAGENTS

def test_code_reviewer_registered():
    assert "code-reviewer" in BUILTIN_SUBAGENTS

def test_all_subagents_have_valid_config():
    for name, config in BUILTIN_SUBAGENTS.items():
        assert config.name == name
        assert config.description
        assert config.system_prompt
        assert config.timeout_seconds > 0
```

#### 2.8 沙箱科学计算包文档

**文件**：`backend/docs/SCIENTIFIC_COMPUTING.md`（新建）

**修改方案**：记录本地沙箱使用科学计算技能时需要安装的包：

```markdown
# Scientific Computing in Sandbox

When using statistical-analysis, data-analysis, or research-code skills,
the sandbox environment needs these Python packages:

## Required Packages

```bash
pip install numpy pandas scipy statsmodels scikit-learn \
    pingouin lifelines matplotlib seaborn openpyxl sympy
```

## For Local Sandbox

Install these packages in the same Python environment that the backend uses.

## For Docker Sandbox (AIO)

The AIO sandbox image includes most scientific packages by default.
```

#### 2.9 config.yaml 注释增强

**文件**：`config.yaml`

**问题**：新增的学术工具段落缺少与现有工具同样详细的注释说明。

**修改方案**：
- 为每个学术工具添加 `# Requires: SEMANTIC_SCHOLAR_API_KEY (optional, increases rate limit)` 等注释
- 添加工具组 `academic` 的 description

#### 2.10 prompt.py 子代理描述与 task_tool.py 一致性

**文件**：`backend/src/agents/lead_agent/prompt.py`

**问题**：prompt.py 段落 20 和 task_tool.py docstring 对三个新子代理的描述应保持一致。

**修改方案**：
- 检查 prompt.py 段落 20 与 task_tool.py docstring 的一致性
- 确保 subagent 名称、功能描述完全匹配

---

## 三、跨文件一致性检查清单

| 检查项 | 涉及文件 | 预期状态 |
|--------|----------|----------|
| 子代理名称一致 | `builtins/__init__.py` → `registry.py` → `task_tool.py` → `prompt.py` | ✅ 已确认一致 |
| 工具名称一致 | `community/*/tools.py` → `config.yaml` → `prompt.py` | ✅ 已确认一致 |
| SKILL.md YAML 格式 | `peer-review/SKILL.md` | ✅ 已确认可被 parser.py 解析 |
| 依赖已满足 | `httpx` 在 `pyproject.toml` | ✅ httpx>=0.28.0 已存在 |
| 记忆类别已存在 | `memory/prompt.py` 中的 `research`/`literature`/`experiment` | ✅ 已存在 |
| CLAUDE.md 已更新 | 子代理 + community tools 段落 | ✅ 本轮已更新 |
| 前端自动发现 | `skills/api.ts` → `loadSkills()` → peer-review | ✅ 后端动态加载 |

---

## 四、执行指令

将本提示词交给 Cursor Agent，指令如下：

```
请按照 /提示词/DeerFlow科研适配二次审计与精修提示词.md 中的清单，
从 P0 开始逐项修复。

对于每项修改：
1. 先读取目标文件确认当前状态
2. 执行精确修改
3. 对代码文件检查 linter 错误
4. 标记完成

对于 P2 的单元测试：
1. 按照项目现有测试模式（backend/tests/test_*.py）创建
2. 运行 make test 确保通过
```

---

## 五、第一轮已完成的修改总览（供参考）

| 层级 | 新建文件 | 修改文件 |
|------|----------|----------|
| 学术 API 工具 | `semantic_scholar/tools.py`, `crossref/tools.py`, `arxiv_search/tools.py` + `__init__.py` | `config.yaml`（注册工具 + 工具组） |
| 子代理 | `literature_agent.py`, `stats_agent.py`, `code_reviewer_agent.py` | `builtins/__init__.py`（注册），`task_tool.py`（Literal 扩展） |
| 技能 | `peer-review/SKILL.md` | `chart-visualization/SKILL.md`，`literature-review/SKILL.md`，`academic-integrity/SKILL.md` |
| 脚本 | `advanced_stats.py`, `preprocess.py`, `scaffold.py` | — |
| 记忆 | `citation_memory.py` | — |
| 提示词 | — | `prompt.py`（新增段落 18/19/20） |
| 配置 | `config.research.yaml` | `extensions_config.example.json` |
| 文档 | — | `CLAUDE.md` |
