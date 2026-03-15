# DeerFlow 代码级科研终极适配提示词

> **目标**：从代码架构层面全面优化 DeerFlow，使其科研能力达到/超越国际顶级研究者/教授水平。
> **范围**：覆盖 8 大代码层（Agent 架构、工具系统、沙箱、子代理、技能脚本、记忆系统、前端、配置），共 42 项精确修改。
> **原则**：每项修改标注精确文件路径、函数签名、代码逻辑，可直接编码实施。

---

## 一、整体架构审计与战略规划

### 1.1 当前代码架构概览

```
DeerFlow 代码架构（科研视角）
├── Agent 层：lead_agent/agent.py + prompt.py → 主控 + 系统提示词
├── 中间件层：11 个 middlewares → 状态管理链
├── 工具层：sandbox/tools.py + tools/builtins/ + community/ → 执行能力
├── 子代理层：subagents/executor.py + builtins/ → 任务分解
├── 技能层：skills/public/*/SKILL.md + scripts/ → 领域知识
├── 记忆层：agents/memory/ → 上下文持久化
├── 网关层：gateway/routers/ → API 接口
├── 模型层：models/factory.py → LLM 实例化
├── MCP 层：mcp/tools.py + cache.py → 外部工具
└── 前端层：frontend/src/ → 交互界面
```

### 1.2 科研能力差距矩阵（代码层）

| 维度 | 现状 | 目标 | 差距级别 |
|------|------|------|---------|
| 学术 API 集成 | 无原生学术 API 工具 | Semantic Scholar / CrossRef / arXiv / PubMed 原生工具 | P0 |
| 统计计算 | 依赖 bash + Python 脚本 | 原生统计分析工具 + R 语言支持 | P0 |
| LaTeX 支持 | 无 | 编译、预览、BibTeX 管理 | P1 |
| 研究状态跟踪 | ThreadState 无科研字段 | 研究阶段、文献库、方法论状态 | P1 |
| 子代理专业化 | 仅 general-purpose + bash | 文献检索、统计分析、代码审查专业子代理 | P1 |
| 同行评审模拟 | 无 | 多视角评审 + 回复模板生成 | P2 |
| 实验管理 | 仅提示词层 | 原生实验跟踪工具 + 结果比较 | P2 |
| 前端科研 UI | 无 | 文献管理、实验仪表板、LaTeX 预览 | P2 |

---

## 二、Agent 架构层增强（4 项修改）

### 2.1 扩展 ThreadState 增加科研状态字段

**文件**：`backend/src/agents/thread_state.py`

**修改逻辑**：在 `ThreadState` 中新增科研相关的状态字段，使 Agent 能跨回合追踪研究进度。

```python
# 新增类型定义
class ResearchPhase(str, Enum):
    IDEATION = "ideation"
    LITERATURE = "literature"
    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    ANALYSIS = "analysis"
    WRITING = "writing"
    REVISION = "revision"
    PRESENTATION = "presentation"

class ResearchState(TypedDict, total=False):
    phase: str                          # 当前研究阶段
    topic: str                          # 研究主题
    research_questions: list[str]       # 研究问题
    methodology: str                    # 方法论（quantitative/qualitative/mixed）
    target_venue: str                   # 目标期刊/会议
    citation_style: str                 # 引用格式（APA/IEEE/GB-T/Vancouver）
    bibliography: dict[str, dict]       # BibTeX 键 → 引用元数据
    completed_sections: list[str]       # 已完成的章节
    pending_sections: list[str]         # 待完成的章节
    key_findings: list[str]            # 关键发现
    figure_registry: dict[str, str]    # 图表 ID → 文件路径

# 在 ThreadState 中添加
class ThreadState(AgentState):
    sandbox: Annotated[SandboxState, ...]
    thread_data: Annotated[ThreadDataState, ...]
    title: Annotated[str, ...]
    artifacts: Annotated[list[Artifact], merge_artifacts]
    todos: Annotated[list[Todo], ...]
    uploaded_files: Annotated[list[str], ...]
    viewed_images: Annotated[dict[str, str], merge_viewed_images]
    research: Annotated[ResearchState, merge_research_state]  # 新增
```

**收益**：Agent 可跨回合追踪研究阶段、文献库、方法论选择，实现真正的"研究伙伴"而非"一次性对话"。

### 2.2 新增 ResearchMiddleware 研究上下文中间件

**文件**：`backend/src/agents/middlewares/research_middleware.py`（新建）

**修改逻辑**：在中间件链中新增 `ResearchMiddleware`，位于 `MemoryMiddleware` 之后。该中间件负责：

1. **研究阶段自动检测**：根据对话内容推断当前研究阶段
2. **学术上下文注入**：在 `before_model` 中注入当前研究状态摘要
3. **文献库持久化**：在 `after_model` 中提取新引用并更新 `research.bibliography`
4. **一致性守卫**：检查关键数字/术语在各产物间的一致性

```python
class ResearchMiddleware(BaseMiddleware):
    """Middleware for research context tracking and academic quality control."""

    async def before_model(self, state: ThreadState, config: RunnableConfig) -> ThreadState:
        research = state.get("research", {})
        if research:
            # 注入研究上下文摘要到最近的系统消息
            context_summary = self._build_research_context(research)
            # 在消息前附加 <research_context> 标签
            ...
        return state

    async def after_model(self, state: ThreadState, config: RunnableConfig) -> ThreadState:
        # 从 AI 回复中提取新引用
        last_message = state["messages"][-1]
        new_citations = self._extract_citations(last_message.content)
        if new_citations:
            bibliography = state.get("research", {}).get("bibliography", {})
            bibliography.update(new_citations)
            state["research"]["bibliography"] = bibliography
        return state
```

**在 agent.py 中注册**：

```python
# _build_middlewares 中，在 MemoryMiddleware 之后添加
middlewares.append(ResearchMiddleware())
```

### 2.3 研究感知模型路由

**文件**：`backend/src/agents/lead_agent/agent.py`

**修改逻辑**：在 `make_lead_agent` 中增加研究任务类型感知，根据任务性质自动调整模型参数。

```python
def _resolve_research_model_params(
    cfg: dict, model_name: str, model_config
) -> dict:
    """根据研究任务类型微调模型参数。"""
    research_mode = cfg.get("research_mode")
    if not research_mode:
        return {}

    params = {}
    if research_mode in ("writing", "review", "grant"):
        # 写作类任务：启用思考模式 + 高推理强度
        params["thinking_enabled"] = True
        params["reasoning_effort"] = "high"
    elif research_mode in ("code", "experiment"):
        # 代码/实验类任务：启用思考但中等推理
        params["thinking_enabled"] = True
        params["reasoning_effort"] = "medium"
    elif research_mode == "literature":
        # 文献检索：关闭思考模式以提高速度
        params["thinking_enabled"] = False
    return params
```

### 2.4 系统提示词学术层增强

**文件**：`backend/src/agents/lead_agent/prompt.py`

**修改逻辑**：在 `SYSTEM_PROMPT_TEMPLATE` 的 `<academic_research>` 段落中补充以下代码级关键能力。

**新增段落 18：学术 API 直接调用能力**

```python
"""
**18. Academic API Tools (Available When Configured)**

You have access to specialized academic API tools:

- `semantic_scholar_search(query, fields, limit)` — Search papers via Semantic Scholar API
  Returns: title, authors, year, citationCount, abstract, tldr, DOI, venue
  Use for: Finding papers, citation counts, author profiles, citation graphs

- `crossref_lookup(query, doi, type, rows)` — Query CrossRef for metadata
  Returns: DOI, title, authors, journal, issue, pages, references
  Use for: DOI validation, reference metadata, journal verification

- `arxiv_search(query, category, max_results)` — Search arXiv preprint server
  Returns: id, title, authors, abstract, categories, pdf_url, published
  Use for: Latest preprints, specific arXiv IDs, category browsing

- `pubmed_search(query, max_results, sort)` — Search PubMed/MEDLINE
  Returns: pmid, title, authors, journal, abstract, mesh_terms, doi
  Use for: Biomedical literature, clinical studies, MeSH-based queries

**API Orchestration for Literature Review**:
1. Start broad: `semantic_scholar_search` (covers CS, bio, medicine)
2. Validate: `crossref_lookup` with DOI to confirm metadata accuracy
3. Supplement: `arxiv_search` for cutting-edge preprints
4. Domain-specific: `pubmed_search` for biomedical topics
5. Citation chain: Use paper IDs from step 1 to get references/citations
"""
```

**新增段落 19：统计分析直接执行能力**

```python
"""
**19. Statistical Analysis Execution Protocol**

When performing statistical analysis, use the sandbox to execute Python with these pre-configured libraries:
- `scipy.stats` — Hypothesis tests (t-test, ANOVA, chi-square, Mann-Whitney, Kruskal-Wallis)
- `statsmodels` — Regression, GLM, mixed effects, time series, survival analysis
- `scikit-learn` — ML evaluation metrics, cross-validation, preprocessing
- `pingouin` — Effect sizes (Cohen's d, eta-squared, omega-squared), Bayesian tests
- `lifelines` — Survival analysis (Kaplan-Meier, Cox PH, AFT)

**Execution pattern** (always use this structure):
```python
import pandas as pd
import scipy.stats as stats
import pingouin as pg

# 1. Load data
df = pd.read_csv('/mnt/user-data/uploads/data.csv')

# 2. Data quality audit
quality_report = {
    'n_rows': len(df),
    'missing': df.isnull().sum().to_dict(),
    'dtypes': df.dtypes.to_dict(),
}

# 3. Assumption checks
normality = pg.normality(df, dv='outcome', group='treatment')
homoscedasticity = pg.homoscedasticity(df, dv='outcome', group='treatment')

# 4. Primary analysis (with effect size + CI)
result = pg.ttest(df[df.group=='A']['score'], df[df.group=='B']['score'],
                  paired=False, alternative='two-sided')
# result contains: T, dof, alternative, p-val, CI95%, cohen-d, BF10, power

# 5. Report in APA format
print(f"t({result['dof'].values[0]:.0f}) = {result['T'].values[0]:.2f}, "
      f"p = {result['p-val'].values[0]:.3f}, "
      f"d = {result['cohen-d'].values[0]:.2f}, "
      f"95% CI [{result['CI95%'].values[0][0]:.2f}, {result['CI95%'].values[0][1]:.2f}]")
```

**CRITICAL**: Never report p-values alone. Always include: test statistic + df + p + effect size + CI.
"""
```

---

## 三、工具系统增强（8 项修改）

### 3.1 新增 Semantic Scholar API 工具

**文件**：`backend/src/community/semantic_scholar/tools.py`（新建）

```python
"""Semantic Scholar API integration for academic paper search and citation analysis."""

import json
import logging
from typing import Any

import httpx
from langchain.tools import tool

from src.community.tool_utils import get_tool_extra

logger = logging.getLogger(__name__)

BASE_URL = "https://api.semanticscholar.org/graph/v1"

def _get_api_key() -> str | None:
    return get_tool_extra("semantic_scholar_search", "api_key")

def _make_request(endpoint: str, params: dict[str, Any]) -> dict:
    headers = {}
    api_key = _get_api_key()
    if api_key:
        headers["x-api-key"] = api_key
    with httpx.Client(timeout=30) as client:
        response = client.get(f"{BASE_URL}/{endpoint}", params=params, headers=headers)
        response.raise_for_status()
        return response.json()

@tool("semantic_scholar_search", parse_docstring=True)
def semantic_scholar_search_tool(
    query: str,
    fields: str = "title,authors,year,citationCount,abstract,tldr,externalIds,venue,publicationDate",
    limit: int = 10,
    year_range: str | None = None,
    venue: str | None = None,
) -> str:
    """Search academic papers via Semantic Scholar API.

    Use this for literature search, finding related work, citation analysis,
    and author discovery. Supports filtering by year range and venue.

    Args:
        query: Search query (natural language or structured).
        fields: Comma-separated fields to return.
        limit: Maximum number of results (1-100).
        year_range: Optional year filter (e.g., "2020-2024" or "2023-").
        venue: Optional venue filter (e.g., "NeurIPS", "Nature").
    """
    params = {"query": query, "fields": fields, "limit": min(limit, 100)}
    if year_range:
        params["year"] = year_range
    if venue:
        params["venue"] = venue

    try:
        data = _make_request("paper/search", params)
        papers = data.get("data", [])
        results = []
        for p in papers:
            entry = {
                "title": p.get("title"),
                "authors": [a.get("name") for a in p.get("authors", [])],
                "year": p.get("year"),
                "citations": p.get("citationCount"),
                "venue": p.get("venue"),
                "abstract": p.get("abstract", "")[:500],
                "tldr": p.get("tldr", {}).get("text") if p.get("tldr") else None,
                "doi": p.get("externalIds", {}).get("DOI"),
                "arxiv_id": p.get("externalIds", {}).get("ArXiv"),
                "s2_id": p.get("paperId"),
            }
            results.append(entry)
        return json.dumps(results, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error searching Semantic Scholar: {e}"


@tool("semantic_scholar_paper", parse_docstring=True)
def semantic_scholar_paper_tool(
    paper_id: str,
    fields: str = "title,authors,year,citationCount,referenceCount,abstract,tldr,references,citations,externalIds,venue",
) -> str:
    """Get detailed information about a specific paper, including its references and citations.

    Use this for citation chain analysis, finding a paper's reference list,
    or getting detailed metadata about a known paper.

    Args:
        paper_id: Semantic Scholar paper ID, DOI, ArXiv ID, or corpus ID.
        fields: Comma-separated fields to return.
    """
    try:
        data = _make_request(f"paper/{paper_id}", {"fields": fields})
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error fetching paper details: {e}"


@tool("semantic_scholar_author", parse_docstring=True)
def semantic_scholar_author_tool(
    author_id: str,
    fields: str = "name,affiliations,paperCount,citationCount,hIndex,papers",
) -> str:
    """Get information about an author, including their papers and citation metrics.

    Args:
        author_id: Semantic Scholar author ID.
        fields: Comma-separated fields to return.
    """
    try:
        data = _make_request(f"author/{author_id}", {"fields": fields})
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error fetching author details: {e}"
```

### 3.2 新增 CrossRef API 工具

**文件**：`backend/src/community/crossref/tools.py`（新建）

```python
"""CrossRef API integration for DOI resolution, citation metadata, and reference validation."""

import json
import logging
from typing import Any

import httpx
from langchain.tools import tool

logger = logging.getLogger(__name__)

BASE_URL = "https://api.crossref.org"

@tool("crossref_lookup", parse_docstring=True)
def crossref_lookup_tool(
    query: str | None = None,
    doi: str | None = None,
    rows: int = 5,
) -> str:
    """Look up academic paper metadata via CrossRef.

    Use for DOI validation, getting accurate citation metadata,
    verifying journal names, and finding reference lists.
    Provide either a search query OR a specific DOI.

    Args:
        query: Search query for papers (used if doi is not provided).
        doi: Specific DOI to look up (takes precedence over query).
        rows: Number of results for search queries (1-20).
    """
    try:
        with httpx.Client(timeout=30) as client:
            if doi:
                response = client.get(
                    f"{BASE_URL}/works/{doi}",
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                item = response.json()["message"]
                return json.dumps(_format_crossref_item(item), indent=2, ensure_ascii=False)
            elif query:
                response = client.get(
                    f"{BASE_URL}/works",
                    params={"query": query, "rows": min(rows, 20)},
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                items = response.json()["message"]["items"]
                results = [_format_crossref_item(item) for item in items]
                return json.dumps(results, indent=2, ensure_ascii=False)
            else:
                return "Error: Provide either 'query' or 'doi' parameter."
    except Exception as e:
        return f"Error querying CrossRef: {e}"


def _format_crossref_item(item: dict) -> dict[str, Any]:
    return {
        "doi": item.get("DOI"),
        "title": item.get("title", [""])[0] if item.get("title") else "",
        "authors": [
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in item.get("author", [])
        ],
        "journal": item.get("container-title", [""])[0] if item.get("container-title") else "",
        "year": (item.get("published-print") or item.get("published-online", {})).get("date-parts", [[None]])[0][0],
        "volume": item.get("volume"),
        "issue": item.get("issue"),
        "pages": item.get("page"),
        "type": item.get("type"),
        "reference_count": item.get("reference-count"),
        "is_referenced_by_count": item.get("is-referenced-by-count"),
        "url": item.get("URL"),
    }
```

### 3.3 新增 arXiv API 工具

**文件**：`backend/src/community/arxiv/tools.py`（新建）

```python
"""arXiv API integration for preprint search and retrieval."""

import json
import logging
import xml.etree.ElementTree as ET

import httpx
from langchain.tools import tool

logger = logging.getLogger(__name__)

ARXIV_API = "http://export.arxiv.org/api/query"

@tool("arxiv_search", parse_docstring=True)
def arxiv_search_tool(
    query: str,
    category: str | None = None,
    max_results: int = 10,
    sort_by: str = "relevance",
) -> str:
    """Search arXiv for preprints and papers.

    Ideal for finding cutting-edge research that may not yet be indexed
    by Semantic Scholar. Supports category filtering and sorting.

    Args:
        query: Search query. Supports arXiv query syntax (e.g., "au:Hinton AND ti:attention").
        category: Optional arXiv category filter (e.g., "cs.CL", "stat.ML", "physics.comp-ph").
        max_results: Maximum results to return (1-50).
        sort_by: Sort order — "relevance", "lastUpdatedDate", or "submittedDate".
    """
    search_query = query
    if category:
        search_query = f"cat:{category} AND ({query})"

    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": min(max_results, 50),
        "sortBy": sort_by,
        "sortOrder": "descending",
    }

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(ARXIV_API, params=params)
            response.raise_for_status()

        root = ET.fromstring(response.text)
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

        results = []
        for entry in root.findall("atom:entry", ns):
            arxiv_id = entry.find("atom:id", ns).text.split("/abs/")[-1]
            title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
            summary = entry.find("atom:summary", ns).text.strip()[:500]
            authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)]
            published = entry.find("atom:published", ns).text[:10]
            categories = [c.get("term") for c in entry.findall("atom:category", ns)]

            pdf_link = None
            for link in entry.findall("atom:link", ns):
                if link.get("title") == "pdf":
                    pdf_link = link.get("href")

            results.append({
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": authors,
                "abstract": summary,
                "published": published,
                "categories": categories,
                "pdf_url": pdf_link or f"https://arxiv.org/pdf/{arxiv_id}",
                "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
            })

        return json.dumps(results, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error searching arXiv: {e}"
```

### 3.4 新增 BibTeX 管理工具

**文件**：`backend/src/tools/builtins/bibtex_tool.py`（新建）

```python
"""BibTeX reference management tool for academic workflows."""

import json
import re
from langchain.tools import ToolRuntime, tool
from langgraph.typing import ContextT
from src.agents.thread_state import ThreadState
from src.sandbox.tools import ensure_sandbox_initialized, get_thread_data, is_local_sandbox, replace_virtual_path

@tool("manage_bibliography", parse_docstring=True)
def manage_bibliography_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    action: str,
    bibtex_entry: str | None = None,
    cite_key: str | None = None,
    bib_file: str = "/mnt/user-data/outputs/references.bib",
) -> str:
    """Manage a BibTeX bibliography file for the current research project.

    Supports adding, removing, listing, and validating BibTeX entries.
    All entries are stored in a single .bib file that can be used with LaTeX.

    Args:
        action: One of "add", "remove", "list", "validate", "format_apa", "format_ieee".
        bibtex_entry: BibTeX entry string (required for "add" action).
        cite_key: Citation key (required for "remove", "format_apa", "format_ieee").
        bib_file: Path to the .bib file.
    """
    sandbox = ensure_sandbox_initialized(runtime)
    if is_local_sandbox(runtime):
        thread_data = get_thread_data(runtime)
        bib_file = replace_virtual_path(bib_file, thread_data)

    try:
        existing = ""
        try:
            existing = sandbox.read_file(bib_file)
        except FileNotFoundError:
            existing = ""

        if action == "add":
            if not bibtex_entry:
                return "Error: bibtex_entry is required for 'add' action"
            new_content = existing + "\n\n" + bibtex_entry.strip() + "\n" if existing else bibtex_entry.strip() + "\n"
            sandbox.write_file(bib_file, new_content)
            key_match = re.search(r'@\w+\{(\S+),', bibtex_entry)
            key = key_match.group(1) if key_match else "unknown"
            return f"Added entry with key '{key}' to {bib_file}"

        elif action == "remove":
            if not cite_key:
                return "Error: cite_key is required for 'remove' action"
            pattern = re.compile(
                rf'@\w+\{{{re.escape(cite_key)},.*?\n\}}',
                re.DOTALL
            )
            new_content, n = pattern.subn('', existing)
            if n == 0:
                return f"Entry '{cite_key}' not found in {bib_file}"
            sandbox.write_file(bib_file, new_content.strip() + "\n")
            return f"Removed entry '{cite_key}'"

        elif action == "list":
            keys = re.findall(r'@(\w+)\{(\S+),', existing)
            if not keys:
                return "Bibliography is empty."
            entries = [f"  [{i+1}] @{typ}{{{key}}}" for i, (typ, key) in enumerate(keys)]
            return f"Bibliography ({len(entries)} entries):\n" + "\n".join(entries)

        elif action == "validate":
            keys = re.findall(r'@\w+\{(\S+),', existing)
            issues = []
            seen = set()
            for key in keys:
                if key in seen:
                    issues.append(f"Duplicate key: {key}")
                seen.add(key)
            if not issues:
                return f"Bibliography valid: {len(keys)} entries, no issues found."
            return f"Validation issues:\n" + "\n".join(f"  - {i}" for i in issues)

        else:
            return f"Unknown action: {action}. Use one of: add, remove, list, validate"

    except Exception as e:
        return f"Error managing bibliography: {e}"
```

### 3.5 新增统计分析快捷工具

**文件**：`backend/src/tools/builtins/stats_tool.py`（新建）

**设计意图**：提供无需写完整 Python 脚本即可执行常用统计检验的快捷工具。封装 17 种核心统计动作。

```python
"""Quick statistical analysis tool wrapping common hypothesis tests."""

from langchain.tools import ToolRuntime, tool
from langgraph.typing import ContextT
from src.agents.thread_state import ThreadState
from src.sandbox.tools import ensure_sandbox_initialized, get_thread_data, is_local_sandbox, replace_virtual_path

STAT_ACTIONS = {
    "t_test_ind": "Independent samples t-test",
    "t_test_paired": "Paired samples t-test",
    "one_way_anova": "One-way ANOVA with post-hoc Tukey",
    "two_way_anova": "Two-way ANOVA",
    "chi_square": "Chi-square test of independence",
    "mann_whitney": "Mann-Whitney U test",
    "wilcoxon": "Wilcoxon signed-rank test",
    "kruskal_wallis": "Kruskal-Wallis H test",
    "pearson_corr": "Pearson correlation",
    "spearman_corr": "Spearman rank correlation",
    "linear_regression": "Linear regression (OLS)",
    "logistic_regression": "Logistic regression",
    "mixed_effects": "Linear mixed-effects model",
    "survival_km": "Kaplan-Meier survival analysis",
    "survival_cox": "Cox proportional hazards",
    "normality_test": "Shapiro-Wilk + Q-Q normality test",
    "data_quality_audit": "7-dimension data quality audit",
}

@tool("quick_stats", parse_docstring=True)
def quick_stats_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    action: str,
    data_path: str,
    dv: str,
    iv: str | None = None,
    grouping: str | None = None,
    covariates: str | None = None,
    alpha: float = 0.05,
    output_format: str = "apa",
) -> str:
    """Execute a statistical analysis action and return APA/IEEE-formatted results.

    This tool runs the specified statistical test on the given data file,
    automatically checking assumptions and computing effect sizes + confidence intervals.
    Results include: test statistic, df, p-value, effect size, CI, and APA-formatted text.

    Args:
        action: Statistical action to perform. Options: t_test_ind, t_test_paired, one_way_anova, two_way_anova, chi_square, mann_whitney, wilcoxon, kruskal_wallis, pearson_corr, spearman_corr, linear_regression, logistic_regression, mixed_effects, survival_km, survival_cox, normality_test, data_quality_audit.
        data_path: Absolute path to the data file (CSV, Excel, or Parquet).
        dv: Dependent variable column name.
        iv: Independent variable column name (for group comparisons).
        grouping: Grouping variable for stratified analyses.
        covariates: Comma-separated covariate column names.
        alpha: Significance level (default 0.05).
        output_format: Output format — "apa" (default), "ieee", or "raw".
    """
    if action not in STAT_ACTIONS:
        return f"Unknown action '{action}'. Available:\n" + "\n".join(
            f"  {k}: {v}" for k, v in STAT_ACTIONS.items()
        )

    sandbox = ensure_sandbox_initialized(runtime)
    if is_local_sandbox(runtime):
        thread_data = get_thread_data(runtime)
        data_path = replace_virtual_path(data_path, thread_data)

    script = _generate_stat_script(action, data_path, dv, iv, grouping, covariates, alpha, output_format)

    try:
        result = sandbox.execute_command(f"python3 -c {repr(script)}")
        return result
    except Exception as e:
        return f"Error executing statistical analysis: {e}"


def _generate_stat_script(action, data_path, dv, iv, grouping, covariates, alpha, output_format):
    """Generate a Python script for the given statistical action."""
    # 根据 action 生成完整的 Python 统计分析脚本
    # 包含数据加载、假设检验、效应量计算、APA 格式化输出
    # 此处为框架，具体脚本在实施时根据每个 action 分别实现
    return f"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# Load data
df = pd.read_csv('{data_path}') if '{data_path}'.endswith('.csv') else pd.read_excel('{data_path}')

dv = '{dv}'
iv = '{iv}' if '{iv}' != 'None' else None
alpha = {alpha}

# Execute action: {action}
# ... (action-specific code)
print("Analysis complete.")
"""
```

### 3.6 在 config.yaml 中注册学术工具

**文件**：`config.yaml`（修改）

```yaml
tools:
  # 现有工具...
  - use: src.community.semantic_scholar.tools:semantic_scholar_search_tool
    group: academic
    extra:
      api_key: $SEMANTIC_SCHOLAR_API_KEY
  - use: src.community.semantic_scholar.tools:semantic_scholar_paper_tool
    group: academic
  - use: src.community.semantic_scholar.tools:semantic_scholar_author_tool
    group: academic
  - use: src.community.crossref.tools:crossref_lookup_tool
    group: academic
  - use: src.community.arxiv.tools:arxiv_search_tool
    group: academic

tool_groups:
  # 现有分组...
  - name: academic
    description: Academic research tools (Semantic Scholar, CrossRef, arXiv)
```

### 3.7 增强 present_file_tool 的学术元数据

**文件**：`backend/src/tools/builtins/present_file_tool.py`

**修改逻辑**：扩展 `present_file` 工具，为学术产物自动添加元数据。

```python
# 在 present_file 函数中增加学术产物识别逻辑
ACADEMIC_EXTENSIONS = {
    ".bib": "bibliography",
    ".tex": "latex_document",
    ".bbl": "latex_bibliography",
    ".csv": "dataset",
    ".json": "structured_data",
    ".r": "r_script",
    ".rmd": "r_markdown",
    ".ipynb": "jupyter_notebook",
}

def _detect_academic_artifact_type(filepath: str) -> str | None:
    """检测文件是否为学术产物并返回类型。"""
    ext = Path(filepath).suffix.lower()
    return ACADEMIC_EXTENSIONS.get(ext)
```

### 3.8 沙箱预安装科学计算包

**文件**：`backend/src/sandbox/local/local_sandbox.py`（修改）

**修改逻辑**：在本地沙箱初始化时，自动检查并安装科学计算必需包。

```python
RESEARCH_PACKAGES = [
    "numpy", "pandas", "scipy", "statsmodels", "scikit-learn",
    "pingouin", "lifelines", "matplotlib", "seaborn",
    "openpyxl", "bibtexparser", "sympy",
]

def _ensure_research_packages(self):
    """确保科学计算包已安装。仅在首次执行时检查。"""
    if self._research_packages_checked:
        return
    missing = []
    for pkg in RESEARCH_PACKAGES:
        result = self.execute_command(f"python3 -c 'import {pkg}' 2>&1")
        if "ModuleNotFoundError" in result:
            missing.append(pkg)
    if missing:
        self.execute_command(f"pip install -q {' '.join(missing)}")
    self._research_packages_checked = True
```

---

## 四、子代理系统增强（3 项修改）

### 4.1 新增学术文献检索专用子代理

**文件**：`backend/src/subagents/builtins/literature_agent.py`（新建）

```python
"""Specialized subagent for academic literature search and analysis."""

from src.subagents.config import SubagentConfig

literature_agent_config = SubagentConfig(
    name="literature-reviewer",
    description=(
        "Specialized agent for academic literature search, citation analysis, "
        "and related work synthesis. Uses Semantic Scholar, CrossRef, and arXiv APIs. "
        "Returns structured literature findings with BibTeX entries."
    ),
    system_prompt="""You are a specialized literature review agent. Your tasks:

1. **Systematic Search**: Use semantic_scholar_search, crossref_lookup, and arxiv_search
   to find relevant papers across multiple databases.
2. **Citation Chain Analysis**: For key papers, retrieve their references and citations
   using semantic_scholar_paper to build a citation network.
3. **Structured Output**: Always return results in this format:
   - Summary of findings (2-3 paragraphs)
   - Key papers table (title, authors, year, citations, relevance)
   - BibTeX entries for all cited papers
   - Identified research gaps
   - Recommended related work narrative

CRITICAL: NEVER fabricate citations. Only report papers you have verified via API.
For each paper, include the DOI or arXiv ID for verification.
""",
    tools=["semantic_scholar_search", "semantic_scholar_paper", "semantic_scholar_author",
           "crossref_lookup", "arxiv_search", "web_search", "web_fetch",
           "read_file", "write_file", "bash"],
    disallowed_tools=["task", "ask_clarification"],
    model="inherit",
    max_turns=30,
    timeout_seconds=600,
)
```

### 4.2 新增统计分析专用子代理

**文件**：`backend/src/subagents/builtins/stats_agent.py`（新建）

```python
"""Specialized subagent for statistical analysis and data science."""

from src.subagents.config import SubagentConfig

stats_agent_config = SubagentConfig(
    name="statistical-analyst",
    description=(
        "Specialized agent for statistical analysis, hypothesis testing, "
        "data quality audit, and publication-ready reporting. "
        "Executes Python/R code in sandbox with scipy, statsmodels, pingouin."
    ),
    system_prompt="""You are a specialized statistical analysis agent. Follow this protocol:

1. **Data Quality Audit** (ALWAYS first):
   - Completeness: missing values per column (% and pattern: MCAR/MAR/MNAR)
   - Validity: range checks, impossible values, logical inconsistencies
   - Uniqueness: duplicate detection
   - Distribution: skewness, kurtosis, outliers (IQR + Grubbs)
   - Data types: numeric/categorical mismatches

2. **Assumption Diagnostics** (BEFORE any test):
   - Normality: Shapiro-Wilk (n<50) or Kolmogorov-Smirnov (n≥50) + Q-Q plot
   - Homoscedasticity: Levene's test
   - Independence: Durbin-Watson (time series) or runs test
   - Multicollinearity: VIF for regression (VIF > 10 = problem)

3. **Analysis Execution**:
   - Run the appropriate test based on DV/IV types and assumption results
   - If assumptions violated: use non-parametric alternative or robust method
   - Compute effect size: Cohen's d, eta-squared, Cramér's V, R², etc.
   - Compute confidence intervals (95% by default)

4. **Output Format** (APA 7th):
   - Test statistic + df + p-value + effect size + CI
   - Example: t(48) = 2.31, p = .025, d = 0.66, 95% CI [0.08, 1.23]

5. **Sensitivity Analysis** (ALWAYS include at least one):
   - Bootstrap CI (1000+ resamples)
   - Leave-one-out influence analysis
   - Alternative test specification

CRITICAL: Never report p-values without effect sizes. Never claim causation from correlation.
""",
    tools=["bash", "read_file", "write_file", "quick_stats", "ls"],
    disallowed_tools=["task", "ask_clarification"],
    model="inherit",
    max_turns=40,
    timeout_seconds=900,
)
```

### 4.3 新增代码审查专用子代理

**文件**：`backend/src/subagents/builtins/code_reviewer_agent.py`（新建）

```python
"""Specialized subagent for research code review and quality assurance."""

from src.subagents.config import SubagentConfig

code_reviewer_agent_config = SubagentConfig(
    name="code-reviewer",
    description=(
        "Specialized agent for reviewing research code quality: "
        "reproducibility, numerical stability, test coverage, "
        "and alignment with paper methodology."
    ),
    system_prompt="""You are a specialized research code reviewer. Evaluate code against these criteria:

1. **Reproducibility** (most critical):
   - Are random seeds set? (numpy, torch, tensorflow, random)
   - Are dependencies pinned with versions?
   - Is there a single-command reproduction script?
   - Are hyperparameters externalized to config files?

2. **Numerical Stability**:
   - LogSumExp pattern used instead of raw exp/log?
   - Epsilon guards on divisions and logs?
   - Gradient clipping in place?
   - Float64 used for accumulations, float32 for compute?

3. **Correctness**:
   - Does code match paper equations? (variable names, dimensions)
   - Are tensor shapes documented with comments?
   - Are edge cases handled (empty input, single sample, etc.)?

4. **Testing**:
   - Shape tests: input/output dimensions match specifications?
   - Determinism tests: same seed → same output?
   - Gradient flow tests: no NaN/Inf gradients?
   - Numerical correctness tests: compare with known results?

5. **Code Quality**:
   - Functions < 40 lines?
   - Clear naming (no single-letter variables except loop indices)?
   - Docstrings with Args/Returns/Raises?
   - Type hints on function signatures?

Output: Structured review with severity ratings (Critical/Major/Minor/Suggestion).
""",
    tools=["bash", "read_file", "write_file", "ls", "str_replace"],
    disallowed_tools=["task", "ask_clarification"],
    model="inherit",
    max_turns=30,
    timeout_seconds=600,
)
```

### 4.4 注册新子代理到 Registry

**文件**：`backend/src/subagents/registry.py`（修改）

```python
# 在现有注册逻辑中添加新子代理
from src.subagents.builtins.literature_agent import literature_agent_config
from src.subagents.builtins.stats_agent import stats_agent_config
from src.subagents.builtins.code_reviewer_agent import code_reviewer_agent_config

BUILTIN_SUBAGENTS = {
    "general-purpose": general_purpose_config,
    "bash": bash_config,
    "literature-reviewer": literature_agent_config,      # 新增
    "statistical-analyst": stats_agent_config,            # 新增
    "code-reviewer": code_reviewer_agent_config,          # 新增
}
```

---

## 五、技能脚本增强（6 项修改）

### 5.1 statistical-analysis 新增高级统计动作脚本

**文件**：`skills/public/statistical-analysis/scripts/advanced_stats.py`（新建）

**功能**：可从 SKILL.md 中通过 `bash python /mnt/skills/public/statistical-analysis/scripts/advanced_stats.py` 调用的统计分析脚本。

```python
"""Advanced statistical analysis script for DeerFlow statistical-analysis skill.

Usage:
    python advanced_stats.py --action <action> --data <path> --dv <col> [--iv <col>] [--output <path>]

Actions:
    assumption_check     Run full assumption diagnostic battery
    effect_size_report   Compute all relevant effect sizes for given test
    power_analysis       Post-hoc and a priori power analysis
    bootstrap_ci         Bootstrap confidence intervals (BCa method)
    multiple_comparison  Bonferroni, Holm, BH FDR corrections
    meta_analysis        Fixed/random effects meta-analysis
    mediation            Causal mediation analysis (Baron & Kenny + Sobel)
    moderation           Moderation analysis with interaction terms
    factor_analysis      Exploratory factor analysis with scree plot
    sem                  Structural equation modeling (basic path analysis)
    icc                  Intraclass correlation coefficient
    bland_altman         Bland-Altman agreement analysis
    roc_analysis         ROC curve analysis with AUC and optimal threshold
    missing_data         Missing data analysis (MCAR test, pattern, imputation)
    outlier_detection    Multivariate outlier detection (Mahalanobis, isolation forest)
    multicollinearity    VIF analysis and condition number diagnostics
    heteroscedasticity   Breusch-Pagan and White's test
"""

import argparse
import json
import sys

import numpy as np
import pandas as pd


def assumption_check(df, dv, iv=None, alpha=0.05):
    """Run comprehensive assumption diagnostic battery."""
    from scipy import stats as sp_stats
    import pingouin as pg

    results = {"normality": {}, "homoscedasticity": {}, "independence": {}}

    # Normality
    for col in [dv] + ([iv] if iv and iv in df.select_dtypes(include=[np.number]).columns else []):
        data = df[col].dropna()
        if len(data) < 50:
            stat, p = sp_stats.shapiro(data)
            test_name = "Shapiro-Wilk"
        else:
            stat, p = sp_stats.kstest(data, 'norm', args=(data.mean(), data.std()))
            test_name = "Kolmogorov-Smirnov"
        results["normality"][col] = {
            "test": test_name, "statistic": round(stat, 4), "p_value": round(p, 4),
            "normal": p > alpha, "skewness": round(data.skew(), 3), "kurtosis": round(data.kurtosis(), 3),
        }

    # Homoscedasticity (if grouping variable provided)
    if iv and iv in df.columns:
        groups = [group[dv].dropna().values for _, group in df.groupby(iv)]
        if len(groups) >= 2:
            stat, p = sp_stats.levene(*groups)
            results["homoscedasticity"] = {
                "test": "Levene", "statistic": round(stat, 4), "p_value": round(p, 4),
                "equal_variances": p > alpha,
            }

    return results


def main():
    parser = argparse.ArgumentParser(description="Advanced statistical analysis")
    parser.add_argument("--action", required=True, choices=[
        "assumption_check", "effect_size_report", "power_analysis",
        "bootstrap_ci", "multiple_comparison", "meta_analysis",
        "mediation", "moderation", "factor_analysis", "sem",
        "icc", "bland_altman", "roc_analysis", "missing_data",
        "outlier_detection", "multicollinearity", "heteroscedasticity",
    ])
    parser.add_argument("--data", required=True, help="Path to data file (CSV/Excel)")
    parser.add_argument("--dv", required=True, help="Dependent variable column name")
    parser.add_argument("--iv", default=None, help="Independent variable column name")
    parser.add_argument("--output", default=None, help="Output path for results JSON")
    parser.add_argument("--alpha", type=float, default=0.05, help="Significance level")

    args = parser.parse_args()

    # Load data
    if args.data.endswith('.csv'):
        df = pd.read_csv(args.data)
    elif args.data.endswith(('.xlsx', '.xls')):
        df = pd.read_excel(args.data)
    else:
        df = pd.read_parquet(args.data)

    # Dispatch to action
    action_fn = globals().get(args.action)
    if action_fn is None:
        print(f"Action '{args.action}' not yet implemented", file=sys.stderr)
        sys.exit(1)

    results = action_fn(df, args.dv, args.iv, args.alpha)

    output = json.dumps(results, indent=2, ensure_ascii=False, default=str)
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"Results written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
```

### 5.2 chart-visualization 增强学术图表标注

**文件**：`skills/public/chart-visualization/SKILL.md`（修改相关段落）

**修改逻辑**：在 SKILL.md 中新增学术图表标注规范段落。

```markdown
## Academic Figure Standards

When generating figures for academic papers, enforce these standards:

### Statistical Annotations
- Error bars: Always specify type (SD, SEM, 95% CI) in caption
- Significance markers: *, **, *** (with legend defining p thresholds)
- Effect size values displayed directly on relevant comparisons
- Sample sizes (n) shown per group, either in legend or x-axis labels

### Publication Quality
- Resolution: 300 DPI minimum (600 DPI for line art)
- Font: Arial or Helvetica, minimum 8pt after scaling
- Color: Colorblind-safe palette (use Okabe-Ito or ColorBrewer)
- File format: PDF (vector) for line/bar, TIFF/PNG for photos/heatmaps
- Dimensions: Match target journal column width (single: 85mm, double: 170mm)

### Caption Requirements
- First sentence: What the figure SHOWS (not what it IS)
- Define all abbreviations, statistical tests, and significance thresholds
- Specify n per group and exact p-values for key comparisons
- Example: "Fig. 3. Treatment X reduces tumor volume compared to control.
  (A) Tumor volume over 28 days... Error bars represent SEM (n=12 per group).
  *p < 0.05, **p < 0.01, two-tailed t-test."
```

### 5.3 academic-ppt 增加断言-证据模板脚本

**文件**：`skills/public/academic-ppt/scripts/academic_pptx.py`（修改）

**修改逻辑**：在 PPTX 生成脚本中新增 `assertion_evidence` 幻灯片类型。

```python
def create_assertion_evidence_slide(prs, title_claim, evidence_image_path=None, evidence_text=None):
    """Create an assertion-evidence slide where the title is a full-sentence claim
    and the body is a visual evidence (figure/diagram), not bullet points.

    Args:
        prs: python-pptx Presentation object
        title_claim: Full sentence stating the claim (e.g., "Treatment X reduces mortality by 37%")
        evidence_image_path: Path to figure/chart image supporting the claim
        evidence_text: Alternative text-based evidence if no image
    """
    slide_layout = prs.slide_layouts[6]  # Blank layout
    slide = prs.slides.add_slide(slide_layout)

    # Title as full-sentence claim (top, spanning full width)
    from pptx.util import Inches, Pt, Emu
    from pptx.enum.text import PP_ALIGN

    title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(9), Inches(1))
    tf = title_box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title_claim
    p.font.size = Pt(28)
    p.font.bold = True
    p.alignment = PP_ALIGN.LEFT

    # Evidence area (center, large)
    if evidence_image_path:
        slide.shapes.add_picture(
            evidence_image_path,
            Inches(1), Inches(1.5), Inches(8), Inches(5)
        )
    elif evidence_text:
        evidence_box = slide.shapes.add_textbox(
            Inches(1), Inches(1.5), Inches(8), Inches(5)
        )
        tf = evidence_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = evidence_text
        p.font.size = Pt(18)

    return slide
```

### 5.4 data-analysis 增加预处理流水线脚本

**文件**：`skills/public/data-analysis/scripts/preprocess.py`（新建）

```python
"""Data preprocessing pipeline for research datasets.

Usage:
    python preprocess.py --input <path> --output <path> [--actions <actions>]

Actions (comma-separated):
    detect_types       Auto-detect and convert column types
    handle_missing     Handle missing values (report + impute)
    remove_duplicates  Remove duplicate rows
    detect_outliers    Flag statistical outliers (IQR + Z-score)
    normalize          Normalize numeric columns (z-score or min-max)
    encode_categorical Label encode or one-hot encode categorical columns
    create_report      Generate data quality report
    all                Run all actions in sequence
"""

import argparse
import json
import sys

import numpy as np
import pandas as pd


def detect_types(df):
    """Auto-detect and optimize column types."""
    report = {}
    for col in df.columns:
        original_dtype = str(df[col].dtype)
        if df[col].dtype == 'object':
            nunique = df[col].nunique()
            if nunique / len(df) < 0.05:
                df[col] = df[col].astype('category')
                report[col] = f"{original_dtype} → category ({nunique} unique)"
            else:
                try:
                    df[col] = pd.to_datetime(df[col])
                    report[col] = f"{original_dtype} → datetime"
                except (ValueError, TypeError):
                    report[col] = f"{original_dtype} (kept as string)"
    return df, report


def handle_missing(df, strategy="report"):
    """Analyze and handle missing values."""
    report = {}
    for col in df.columns:
        n_missing = df[col].isnull().sum()
        pct = n_missing / len(df) * 100
        if n_missing > 0:
            report[col] = {
                "n_missing": int(n_missing),
                "pct_missing": round(pct, 2),
                "recommendation": (
                    "drop_column" if pct > 50
                    else "impute_median" if df[col].dtype in ['float64', 'int64']
                    else "impute_mode"
                ),
            }
    return df, report


def detect_outliers(df):
    """Detect outliers using IQR and Z-score methods."""
    report = {}
    for col in df.select_dtypes(include=[np.number]).columns:
        q1 = df[col].quantile(0.25)
        q3 = df[col].quantile(0.75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        n_outliers_iqr = ((df[col] < lower) | (df[col] > upper)).sum()

        z_scores = np.abs((df[col] - df[col].mean()) / df[col].std())
        n_outliers_z = (z_scores > 3).sum()

        if n_outliers_iqr > 0 or n_outliers_z > 0:
            report[col] = {
                "iqr_outliers": int(n_outliers_iqr),
                "zscore_outliers": int(n_outliers_z),
                "range": [round(float(lower), 2), round(float(upper), 2)],
            }
    return df, report


def create_report(df):
    """Generate comprehensive data quality report."""
    report = {
        "shape": {"rows": len(df), "columns": len(df.columns)},
        "dtypes": df.dtypes.astype(str).to_dict(),
        "missing": df.isnull().sum().to_dict(),
        "numeric_summary": {},
        "categorical_summary": {},
    }

    for col in df.select_dtypes(include=[np.number]).columns:
        report["numeric_summary"][col] = {
            "mean": round(float(df[col].mean()), 4),
            "std": round(float(df[col].std()), 4),
            "min": round(float(df[col].min()), 4),
            "max": round(float(df[col].max()), 4),
            "skewness": round(float(df[col].skew()), 4),
            "kurtosis": round(float(df[col].kurtosis()), 4),
        }

    for col in df.select_dtypes(include=['object', 'category']).columns:
        report["categorical_summary"][col] = {
            "n_unique": int(df[col].nunique()),
            "top_3": df[col].value_counts().head(3).to_dict(),
        }

    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--actions", default="create_report")
    args = parser.parse_args()

    df = pd.read_csv(args.input) if args.input.endswith('.csv') else pd.read_excel(args.input)

    actions = args.actions.split(",")
    if "all" in actions:
        actions = ["detect_types", "handle_missing", "remove_duplicates", "detect_outliers", "create_report"]

    full_report = {}
    for action in actions:
        fn = globals().get(action)
        if fn is None:
            print(f"Unknown action: {action}", file=sys.stderr)
            continue
        if action == "create_report":
            full_report[action] = fn(df)
        else:
            df, report = fn(df)
            full_report[action] = report

    output = json.dumps(full_report, indent=2, ensure_ascii=False, default=str)
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        if args.output.endswith('.csv'):
            df.to_csv(args.output.replace('.json', '_cleaned.csv'), index=False)
    print(output)


if __name__ == "__main__":
    main()
```

### 5.5 research-code 增加论文复现脚手架生成器

**文件**：`skills/public/research-code/scripts/scaffold.py`（新建）

```python
"""Research code scaffolding generator.

Generates a complete research project structure from a paper's methodology section.

Usage:
    python scaffold.py --name <project_name> --paradigm <ml|stats|simulation|survey> --output <path>
"""

import argparse
import os

TEMPLATES = {
    "ml": {
        "dirs": ["src/models", "src/data", "src/trainers", "src/evaluation", "configs", "scripts", "tests", "notebooks"],
        "files": {
            "src/__init__.py": "",
            "src/models/__init__.py": "",
            "src/models/base.py": '''"""Base model interface."""
from abc import ABC, abstractmethod
import torch.nn as nn

class BaseModel(ABC, nn.Module):
    @abstractmethod
    def forward(self, x):
        ...

    @property
    @abstractmethod
    def num_parameters(self) -> int:
        ...
''',
            "src/data/dataset.py": '''"""Dataset loading and preprocessing."""
from torch.utils.data import Dataset
import pandas as pd

class ResearchDataset(Dataset):
    def __init__(self, data_path, split="train", transform=None):
        self.data = pd.read_csv(data_path)
        self.transform = transform

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        sample = self.data.iloc[idx]
        if self.transform:
            sample = self.transform(sample)
        return sample
''',
            "configs/default.yaml": '''experiment:
  name: "experiment_001"
  seed: 42
  device: "cuda"

model:
  type: "baseline"
  hidden_dim: 256

training:
  epochs: 100
  batch_size: 32
  learning_rate: 1e-3
  weight_decay: 1e-5

data:
  train_path: "data/train.csv"
  val_path: "data/val.csv"
  test_path: "data/test.csv"
''',
            "scripts/train.py": '''"""Training script with reproducibility guarantees."""
import argparse
import random
import numpy as np
import torch
import yaml

def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/default.yaml")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    set_seed(config["experiment"]["seed"])
    print(f"Starting experiment: {config['experiment']['name']}")
    # ... training logic

if __name__ == "__main__":
    main()
''',
            "requirements.txt": '''torch>=2.0.0
numpy>=1.24.0
pandas>=2.0.0
scikit-learn>=1.3.0
pyyaml>=6.0
matplotlib>=3.7.0
tensorboard>=2.14.0
''',
            "Makefile": '''train:
\tpython scripts/train.py --config configs/default.yaml

test:
\tpython -m pytest tests/ -v

lint:
\truff check src/ scripts/

.PHONY: train test lint
''',
        },
    },
}


def create_scaffold(name, paradigm, output_path):
    template = TEMPLATES.get(paradigm)
    if not template:
        print(f"Unknown paradigm: {paradigm}. Available: {list(TEMPLATES.keys())}")
        return

    project_root = os.path.join(output_path, name)
    os.makedirs(project_root, exist_ok=True)

    for d in template["dirs"]:
        os.makedirs(os.path.join(project_root, d), exist_ok=True)

    for filepath, content in template["files"].items():
        full_path = os.path.join(project_root, filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(content)

    print(f"Project scaffold created at: {project_root}")
    print(f"Structure:")
    for d in sorted(template["dirs"]):
        print(f"  {d}/")
    for f in sorted(template["files"].keys()):
        print(f"  {f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--paradigm", default="ml", choices=list(TEMPLATES.keys()))
    parser.add_argument("--output", default="/mnt/user-data/outputs")
    args = parser.parse_args()
    create_scaffold(args.name, args.paradigm, args.output)


if __name__ == "__main__":
    main()
```

### 5.6 新增 peer-review 技能

**文件**：`skills/public/peer-review/SKILL.md`（新建）

```markdown
---
name: peer-review
description: Simulate multi-perspective peer review for manuscripts, including reviewer comments, response letters, and revision tracking.
license: MIT
---

# Peer Review Simulation Skill

## Purpose

Simulate rigorous peer review of academic manuscripts from multiple reviewer perspectives, generate structured reviewer reports, and help draft Response to Reviewers letters.

## When to Use

- Before submitting a manuscript to a journal/conference
- After receiving actual reviewer comments (to help draft responses)
- During internal review rounds
- For thesis/dissertation chapter review

## Workflow

### Phase 1: Reviewer Persona Assignment

Assign 3 reviewers with distinct perspectives:

| Reviewer | Perspective | Focus Areas |
|----------|-------------|-------------|
| Reviewer 1 | Domain Expert | Technical accuracy, novelty, related work completeness |
| Reviewer 2 | Methodologist | Statistical rigor, experimental design, reproducibility |
| Reviewer 3 | Generalist/Editor | Clarity, impact, structure, readability |

### Phase 2: Structured Review Template

Each reviewer evaluates:

```
## Reviewer N Report

### Summary (2-3 sentences)
### Strengths (3-5 bullet points)
### Weaknesses (3-5 bullet points, classified as Major/Minor)
### Detailed Comments (numbered, with section references)
### Questions for Authors
### Recommendation: Accept / Minor Revision / Major Revision / Reject
### Confidence: High / Medium / Low
```

### Phase 3: Meta-Review Synthesis

Synthesize all reviews into:
1. Consensus strengths and weaknesses
2. Contradictions between reviewers (and how to resolve)
3. Priority-ranked revision action items
4. Estimated revision effort (1-2 weeks / 1 month / 2+ months)

### Phase 4: Response to Reviewers Template

For each reviewer comment:
```
**Reviewer N, Comment M**: [original comment]

**Response**: [your response]

**Changes Made**: [specific changes with page/line numbers]
```

### Phase 5: Revision Tracking

After revisions:
- Diff summary of all changes
- Cross-check: does each response address its comment?
- New consistency check across all sections

## Quality Criteria for Reviews

A good simulated review should:
- Reference specific sections, equations, figures, or tables
- Cite relevant papers the authors may have missed
- Suggest concrete improvements, not just identify problems
- Distinguish between required changes and suggestions
- Be constructive, not adversarial

## Common Reviewer Concerns (Top 10)

1. Insufficient novelty over prior work
2. Missing comparison with state-of-the-art baselines
3. Statistical significance not established (no p-values, effect sizes)
4. Reproducibility concerns (missing details, no code)
5. Overclaimed contributions (results don't support conclusions)
6. Incomplete related work (missing key references)
7. Unclear methodology (can't replicate from paper alone)
8. Poor writing quality (structure, grammar, flow)
9. Missing ablation studies
10. Ethical concerns (bias, fairness, privacy)
```

---

## 六、记忆系统增强（3 项修改）

### 6.1 增加科研专用记忆类别

**文件**：`backend/src/agents/memory/prompt.py`（修改）

**修改逻辑**：在记忆更新提示词中新增科研领域的 fact 类别和上下文字段。

```python
# 在现有 MEMORY_UPDATE_PROMPT 中，fact categories 列表添加：
RESEARCH_FACT_CATEGORIES = [
    "research_direction",   # 用户的研究方向和主题
    "methodology",          # 偏好的研究方法（定量/质性/混合）
    "target_venues",        # 目标投稿期刊/会议
    "citation_style",       # 偏好的引用格式
    "writing_stage",        # 当前写作进度
    "tools_expertise",      # 用户掌握的工具/语言（R/Python/SPSS/Stata）
    "domain_knowledge",     # 领域特定知识（如特定理论框架）
    "collaborators",        # 合作者信息
    "deadlines",            # 投稿截止日期
    "previous_publications",# 用户已发表的论文
]

# 在 context 更新模板中添加研究上下文字段
RESEARCH_CONTEXT_TEMPLATE = """
Research Context Updates (add/update these fields when user discusses research):
- "researchDirection": their main research area/topic (1-2 sentences)
- "currentProject": what they're currently working on
- "methodology": preferred methods (quantitative/qualitative/mixed/computational)
- "targetVenue": journal or conference they're targeting
- "writingProgress": which sections are done/in progress
- "toolPreferences": statistical/programming tools they use
"""
```

### 6.2 增加项目级记忆持久化

**文件**：`backend/src/agents/memory/updater.py`（修改）

**修改逻辑**：在记忆更新逻辑中增加"研究项目"维度的持久化。

```python
# 在 _update_memory 函数中添加研究项目追踪
def _extract_research_project_updates(conversation: str, existing_memory: dict) -> dict:
    """从对话中提取研究项目状态更新。"""
    research_indicators = [
        "论文", "paper", "manuscript", "研究", "research",
        "数据", "data", "统计", "statistics", "实验", "experiment",
        "文献", "literature", "综述", "review", "基金", "grant",
    ]

    has_research_content = any(
        indicator in conversation.lower()
        for indicator in research_indicators
    )

    if not has_research_content:
        return {}

    # 提取并返回研究项目相关的上下文更新
    return {
        "research_detected": True,
        "update_research_context": True,
    }
```

### 6.3 增加文献库记忆（跨会话引用持久化）

**文件**：`backend/src/agents/memory/citation_memory.py`（新建）

```python
"""Citation memory: persists bibliography across sessions.

Stores verified citations in a separate JSON file that can be
injected into any session where the user references prior work.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CITATION_STORE = "backend/.deer-flow/citations.json"

def load_citations(store_path: str = DEFAULT_CITATION_STORE) -> dict[str, Any]:
    path = Path(store_path)
    if not path.exists():
        return {"citations": {}, "tags": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to load citation store: %s", e)
        return {"citations": {}, "tags": {}}


def save_citation(cite_key: str, metadata: dict, tags: list[str] | None = None,
                  store_path: str = DEFAULT_CITATION_STORE):
    store = load_citations(store_path)
    store["citations"][cite_key] = metadata
    if tags:
        for tag in tags:
            store["tags"].setdefault(tag, [])
            if cite_key not in store["tags"][tag]:
                store["tags"][tag].append(cite_key)
    Path(store_path).parent.mkdir(parents=True, exist_ok=True)
    Path(store_path).write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")


def search_citations(query: str, store_path: str = DEFAULT_CITATION_STORE) -> list[dict]:
    store = load_citations(store_path)
    results = []
    query_lower = query.lower()
    for key, meta in store["citations"].items():
        searchable = json.dumps(meta, ensure_ascii=False).lower()
        if query_lower in searchable or query_lower in key.lower():
            results.append({"cite_key": key, **meta})
    return results


def format_for_injection(store_path: str = DEFAULT_CITATION_STORE, max_entries: int = 20) -> str:
    store = load_citations(store_path)
    if not store["citations"]:
        return ""
    entries = list(store["citations"].items())[:max_entries]
    lines = [f"- [{key}] {meta.get('title', 'Unknown')} ({meta.get('year', '?')})" for key, meta in entries]
    return "<citation_library>\n" + "\n".join(lines) + "\n</citation_library>"
```

---

## 七、前端增强（3 项修改）

### 7.1 增加 LaTeX 公式渲染支持

**文件**：`frontend/src/core/streamdown/plugins.ts`（修改）

**修改逻辑**：在 Markdown 渲染插件中增强 LaTeX 公式渲染，支持行内 `$...$` 和块级 `$$...$$`。

```typescript
// 新增 KaTeX 渲染插件
import katex from 'katex';

export const latexPlugin = {
  name: 'latex',
  transform(content: string): string {
    // 块级公式 $$...$$
    content = content.replace(/\$\$([\s\S]+?)\$\$/g, (_, formula) => {
      try {
        return katex.renderToString(formula.trim(), {
          displayMode: true,
          throwOnError: false,
          trust: true,
        });
      } catch {
        return `<pre class="latex-error">${formula}</pre>`;
      }
    });

    // 行内公式 $...$（避免匹配 $$）
    content = content.replace(/(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)/g, (_, formula) => {
      try {
        return katex.renderToString(formula.trim(), {
          displayMode: false,
          throwOnError: false,
        });
      } catch {
        return `<code class="latex-error">${formula}</code>`;
      }
    });

    return content;
  },
};
```

### 7.2 新增研究项目状态显示组件

**文件**：`frontend/src/components/workspace/research-status.tsx`（新建）

**设计意图**：在工作区侧边栏或消息区展示当前研究项目的阶段进度。

```typescript
// 研究阶段状态组件
interface ResearchPhase {
  id: string;
  name: string;
  status: 'completed' | 'in_progress' | 'pending';
}

const RESEARCH_PHASES: ResearchPhase[] = [
  { id: 'ideation', name: 'Ideation', status: 'pending' },
  { id: 'literature', name: 'Literature Review', status: 'pending' },
  { id: 'design', name: 'Research Design', status: 'pending' },
  { id: 'implementation', name: 'Implementation', status: 'pending' },
  { id: 'analysis', name: 'Data Analysis', status: 'pending' },
  { id: 'writing', name: 'Writing', status: 'pending' },
  { id: 'revision', name: 'Revision', status: 'pending' },
  { id: 'presentation', name: 'Presentation', status: 'pending' },
];
```

### 7.3 增加 i18n 科研相关翻译

**文件**：`frontend/src/core/i18n/locales/zh-CN.ts` 和 `en-US.ts`（修改）

```typescript
// zh-CN.ts 新增
research: {
  phase: {
    ideation: '选题构思',
    literature: '文献综述',
    design: '研究设计',
    implementation: '实验实施',
    analysis: '数据分析',
    writing: '论文撰写',
    revision: '修改完善',
    presentation: '成果展示',
  },
  status: {
    completed: '已完成',
    in_progress: '进行中',
    pending: '待开始',
  },
  bibliography: '文献库',
  experiment_log: '实验日志',
  figure_gallery: '图表库',
}
```

---

## 八、配置层增强（2 项修改）

### 8.1 extensions_config.json 新增学术 MCP 服务器

**文件**：`extensions_config.example.json`（修改）

```json
{
  "mcpServers": {
    "zotero": {
      "enabled": false,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@anthropics/zotero-mcp-server"],
      "env": { "ZOTERO_API_KEY": "" },
      "description": "Zotero reference management integration"
    },
    "arxiv": {
      "enabled": false,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "arxiv-mcp-server"],
      "description": "arXiv paper search and retrieval"
    },
    "jupyter": {
      "enabled": false,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "jupyter-mcp-server"],
      "env": { "JUPYTER_URL": "http://localhost:8888" },
      "description": "Jupyter notebook integration for interactive analysis"
    },
    "overleaf": {
      "enabled": false,
      "type": "http",
      "url": "",
      "description": "Overleaf LaTeX collaboration (requires Overleaf Server Pro)"
    }
  }
}
```

### 8.2 config.yaml 科研预设模板

**文件**：`config.research.yaml`（新建）

```yaml
# DeerFlow 科研模式预设配置
# 使用方式：cp config.research.yaml config.yaml

models:
  - name: "gpt-4o"
    use: "langchain_openai.chat_models:ChatOpenAI"
    api_key: $OPENAI_API_KEY
    supports_thinking: false
    supports_vision: true

tools:
  # 网页搜索
  - use: src.community.tavily.tools:web_search_tool
    group: web
  - use: src.community.jina_ai.tools:web_fetch_tool
    group: web
  # 学术 API（新增）
  - use: src.community.semantic_scholar.tools:semantic_scholar_search_tool
    group: academic
  - use: src.community.semantic_scholar.tools:semantic_scholar_paper_tool
    group: academic
  - use: src.community.crossref.tools:crossref_lookup_tool
    group: academic
  - use: src.community.arxiv.tools:arxiv_search_tool
    group: academic

tool_groups:
  - name: web
    description: Web search and content retrieval
  - name: academic
    description: Academic paper search and citation management
  - name: file:read
    description: File reading operations
  - name: file:write
    description: File writing operations
  - name: bash
    description: Command execution

sandbox:
  use: src.sandbox.local.local_sandbox_provider:LocalSandboxProvider

subagents:
  enabled: true
  timeout_seconds: 900  # 15 分钟（科研任务需要更长时间）

skills:
  path: ./skills
  container_path: /mnt/skills

memory:
  enabled: true
  injection_enabled: true
  debounce_seconds: 30
  max_facts: 200          # 科研需要更多事实存储
  fact_confidence_threshold: 0.6  # 略微降低阈值以保留更多研究上下文
  max_injection_tokens: 3000     # 增加注入上下文

title:
  enabled: true

summarization:
  enabled: true
```

---

## 九、实施优先级矩阵

### P0：立即实施（1-2 周，ROI 最高）

| # | 修改项 | 文件 | 工作量 | 收益 |
|---|--------|------|--------|------|
| 1 | Semantic Scholar API 工具 | `community/semantic_scholar/tools.py` | 2天 | 文献检索能力质变 |
| 2 | CrossRef API 工具 | `community/crossref/tools.py` | 1天 | 引用验证+元数据 |
| 3 | arXiv API 工具 | `community/arxiv/tools.py` | 1天 | 前沿论文获取 |
| 4 | config.yaml 注册学术工具 | `config.yaml` | 0.5天 | 工具可用 |
| 5 | 记忆系统科研类别 | `memory/prompt.py` | 1天 | 研究上下文持久化 |
| 6 | advanced_stats.py 脚本 | `skills/statistical-analysis/scripts/` | 2天 | 17种统计动作 |
| 7 | 数据预处理脚本 | `skills/data-analysis/scripts/preprocess.py` | 1天 | 数据准备流水线 |

### P1：第二阶段（2-4 周）

| # | 修改项 | 文件 | 工作量 | 收益 |
|---|--------|------|--------|------|
| 8 | BibTeX 管理工具 | `tools/builtins/bibtex_tool.py` | 2天 | 引用管理自动化 |
| 9 | 统计快捷工具 | `tools/builtins/stats_tool.py` | 3天 | 无需写脚本执行统计 |
| 10 | 文献检索子代理 | `subagents/builtins/literature_agent.py` | 2天 | 专业化文献搜索 |
| 11 | 统计分析子代理 | `subagents/builtins/stats_agent.py` | 2天 | 专业化数据分析 |
| 12 | 代码审查子代理 | `subagents/builtins/code_reviewer_agent.py` | 2天 | 代码质量保证 |
| 13 | 断言-证据 PPT 模板 | `skills/academic-ppt/scripts/` | 1天 | 学术演示质变 |
| 14 | peer-review 技能 | `skills/public/peer-review/SKILL.md` | 2天 | 投稿前自审 |
| 15 | ResearchMiddleware | `agents/middlewares/research_middleware.py` | 3天 | 研究上下文自动追踪 |

### P2：第三阶段（4-8 周）

| # | 修改项 | 文件 | 工作量 | 收益 |
|---|--------|------|--------|------|
| 16 | ThreadState 科研字段 | `agents/thread_state.py` | 2天 | 跨回合研究状态 |
| 17 | 文献库记忆 | `agents/memory/citation_memory.py` | 2天 | 跨会话引用 |
| 18 | 研究代码脚手架 | `skills/research-code/scripts/scaffold.py` | 2天 | 快速项目初始化 |
| 19 | LaTeX 公式渲染 | `frontend/streamdown/plugins.ts` | 2天 | 数学公式显示 |
| 20 | 研究项目状态组件 | `frontend/components/workspace/` | 3天 | 进度可视化 |
| 21 | 沙箱科学包预装 | `sandbox/local/local_sandbox.py` | 1天 | 开箱即用 |
| 22 | 科研配置预设 | `config.research.yaml` | 0.5天 | 一键部署 |
| 23 | MCP 学术服务器 | `extensions_config.example.json` | 1天 | Zotero/Jupyter 集成 |

---

## 十、验证标准

### 10.1 功能验证清单

实施后，DeerFlow 应能通过以下场景测试：

- [ ] **文献检索**：输入研究问题 → 返回 10+ 相关论文（含 DOI、引用数、摘要）→ 生成 BibTeX
- [ ] **统计分析**：上传 CSV → 自动数据质量审计 → 假设检验 → APA 格式报告 → 出版级图表
- [ ] **论文写作**：给定大纲 → 逐节生成 → 引用自动插入 → 全文一致性检查
- [ ] **代码复现**：给定论文 → 生成项目脚手架 → 实现核心算法 → 6 级测试
- [ ] **基金申请**：给定研究方向 → 科学问题凝练 → Aims 设计 → 完整申请书
- [ ] **同行评审**：给定手稿 → 3 位模拟审稿人 → 结构化审稿意见 → 回复模板
- [ ] **跨技能协同**：文献综述产出 → 自动流转到论文写作 → 图表复用到 PPT
- [ ] **记忆持久化**：多次对话后 → 系统记住研究方向、引用库、方法论偏好

### 10.2 质量基准（对标国际顶级水平）

| 能力维度 | 基准标准 |
|----------|----------|
| 文献检索 | 与 Elicit / Consensus 同等覆盖率 |
| 统计分析 | SPSS/Stata 同等报告质量 + 自动化假设检验 |
| 论文写作 | 通过 Grammarly Academic + Turnitin 初筛 |
| 代码质量 | 通过 NeurIPS 2024 代码审查清单 |
| 引用管理 | 与 Zotero + Better BibTeX 同等能力 |
| 演示设计 | 通过 TED 式"一页一观点"评审 |

---

## 十一、使用方法

将本提示词交给 DeerFlow 的 AI Agent（或 Cursor Agent），指令如下：

```
请按照 /提示词/DeerFlow代码级科研终极适配提示词.md 中的修改方案，
从 P0 优先级开始逐项实施代码修改。

每完成一项：
1. 编写对应的单元测试（backend/tests/）
2. 运行 make test 确保不破坏现有功能
3. 更新 README.md 和 CLAUDE.md 文档
4. 标记该项为已完成
```

---

*本提示词基于对 DeerFlow 全部代码（agent.py、prompt.py、tools.py、executor.py、sandbox/tools.py、loader.py、parser.py 等 60+ 文件）和 24 个 skills 的完整分析，以及 14 份既有提示词的系统梳理而构建。*
