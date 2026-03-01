# Stock Deep Research Skill Implementation Plan

## Objective
Create a new skill `stock-deep-research` that implements a complete buy-side stock deep research workflow.
This workflow **must** integrate specific local skills and MCPs as core components, while also utilizing other available resources (like search MCPs) to ensure a comprehensive report.

## Language & Localization
- **Report Language**: Chinese (Simplified).
- **Search Keywords**: Use original Chinese stock names/keywords; do not translate.
- **Skill Description**: `SKILL.md` will use Chinese for description and instructions.
- **Code Comments/Prompts**: Chinese.

## References
- **Requirements**: `main.py` (L789-1047) for report framework and agent roles.

## Components

### Mandatory Core Skills (Must Use)
- `stock-mapper`: Standardize stock codes/names.
- `finance-pdf-ingest`: Download and process reports (Executed first).
- `stock-news-get`: Fetch news.
- `xueqiu-hotposts-analyzer`: Fetch sentiment/posts.

### Mandatory MCPs (Must Use)
- `tu-mcp` (Tushare Data): `http://127.0.0.1:29002/tu-mcp`
- `local-rag-mcp` (WeKnora RAG): `http://127.0.0.1:29001/local-rag-mcp`

### Supplementary Resources (To ensure completeness)
- `huoshan-search-mcp` or `WebSearch` (from `extensions_config.json`): For industry trends, competitor analysis, and macro info not covered by specific skills.

## Implementation Steps

### 1. Directory Setup
- Create directory: `/home/dingkd/deer-flow/skills/custom/stock-deep-research`
- Create sub-directory: `scripts`

### 2. Skill Definition (`SKILL.md`)
- Define the skill metadata (name, description in Chinese).
- Define the trigger: "股票研究" (Stock Research).
- Document the usage command and parameters.

### 3. Script Development (`scripts/research.py`)
Develop a Python script that orchestrates the workflow:

#### A. Initialization & Mapping
- Input: User provides Stock Name/Code.
- Action: Call `stock-mapper` to get standardized `name` (Chinese), `symbol`, `ts_code`.

#### B. PDF Ingestion (Priority Task)
- Action: Call `finance-pdf-ingest` immediately with Chinese stock name.
- Note: Runs in background/parallel to optimize time.

#### C. Comprehensive Data Collection
- **News**: Call `stock-news-get`.
- **Sentiment**: Call `xueqiu-hotposts-analyzer`.
- **Financial Data**: Connect to `tu-mcp` (SSE) for financial statements.
- **RAG Retrieval**: Connect to `local-rag-mcp` (SSE) for report details.
- **General Search**: Use Search MCP for missing industry/competitor info.

#### D. Agentic Analysis & Synthesis (in Chinese)
- Use `autogen` to instantiate agents:
  - `NewsAnalyst`, `SentimentAnalyst`, `FinancialAnalyst`, `DocAnalyst`.
  - **`ResearchDirector`**:
    - Aggregates analyses.
    - **Logic Reflection/Debate**: Explicit step to challenge assumptions and check data consistency (e.g., "Is the revenue growth consistent with industry trends?").
    - **Report Generation**: Produces final report with sections: Investment Suggestion, Core Logic, Marginal Changes, Fundamentals, Financials, Valuation, Risks.

### 4. Verification
- Verify the script runs and calls the tools correctly.
- Check if MCP connections work.

## Todo List
- [ ] Create directory structure
- [ ] Write `SKILL.md` (Chinese description)
- [ ] Write `scripts/research.py` (Chinese prompts, incorporating all mandatory and supplementary tools)
- [ ] Verify implementation
