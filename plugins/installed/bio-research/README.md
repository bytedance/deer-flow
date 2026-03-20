# Bio-Research Plugin

Connect to preclinical research tools and databases (literature search, genomics analysis, target prioritization) to accelerate early-stage life sciences R&D. Use with [Cowork](https://claude.com/product/cowork) or install directly in Claude Code.

This plugin consolidates 10 MCP server integrations and 5 analysis skills into a single package for life science researchers.

## What's Included

### MCP Servers (Data Sources & Tools)

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](CONNECTORS.md).

| Provider | What It Does | Category/Placeholder |
|----------|-------------|---------------------|
| U.S. National Library of Medicine | Search biomedical literature and research articles | `~~literature` |
| deepsense.ai | Access preprints from bioRxiv and medRxiv | `~~literature` |
| John Wiley & Sons | Access academic research and publications | `~~journal access` |
| Sage Bionetworks | Collaborative research data management | `~~data repository` |
| deepsense.ai | Bioactive drug-like compound database | `~~chemical database` |
| OpenTargets | Drug target discovery and prioritization | `~~drug targets` |
| deepsense.ai | NIH/NLM clinical trial registry | `~~clinical trials` |
| BioRender | Scientific illustration creation | `~~scientific illustration` |
| Owkin | AI for biology — histopathology and drug discovery | `~~AI research` |
| Benchling\* | Lab data management platform | `~~lab platform` |

### Optional Binary MCP Servers

These require a separate binary download:

- **10X Genomics txg-mcp** (`~~genomics platform`) — Cloud analysis data and workflows ([GitHub](https://github.com/10XGenomics/txg-mcp/releases))
- **ToolUniverse** (`~~tool database`) — AI tools for scientific discovery from Harvard MIMS ([GitHub](https://github.com/mims-harvard/ToolUniverse/releases))

### Skills (Analysis Workflows)

#### Single-Cell RNA QC
Automated quality control for scRNA-seq data following scverse best practices. Supports `.h5ad` and `.h5` files with MAD-based filtering and comprehensive visualizations.

#### scvi-tools
Deep learning toolkit for single-cell omics. Covers scVI, scANVI, totalVI, PeakVI, MultiVI, DestVI, veloVI, and sysVI models for integration, batch correction, label transfer, and multi-modal analysis.

#### Nextflow Pipelines
Run nf-core bioinformatics pipelines on local or public GEO/SRA sequencing data:
- **rnaseq** — Gene expression and differential expression
- **sarek** — Germline and somatic variant calling (WGS/WES)
- **atacseq** — Chromatin accessibility analysis

#### Instrument Data to Allotrope
Convert laboratory instrument output files (PDF, CSV, Excel, TXT) to Allotrope Simple Model (ASM) format. Supports 40+ instrument types including cell counters, spectrophotometers, plate readers, qPCR, and chromatography systems.

#### Scientific Problem Selection
Systematic framework for research problem selection based on Fischbach & Walsh's framework. Includes 9 skills covering ideation, risk assessment, optimization, decision trees, adversity planning, and synthesis.

## Getting Started

```bash
# Install the plugin
/install anthropics/knowledge-work-plugins bio-research

# Run the start command to see available tools
/start
```

## Common Workflows

**Literature Review**
Search ~~literature database for papers, access full-text through ~~journal access, and create figures with ~~scientific illustration.

**Single-Cell Analysis**
Run QC on scRNA-seq data, then use scvi-tools for integration, batch correction, and cell type annotation.

**Sequencing Pipeline**
Download public data from GEO/SRA, run nf-core pipelines (RNA-seq, variant calling, ATAC-seq), and verify outputs.

**Drug Discovery**
Search ~~chemical database for bioactive compounds, use ~~drug target database for target prioritization, and review clinical trial data.

**Research Strategy**
Pitch a new idea, troubleshoot a stuck project, or evaluate strategic decisions using the scientific problem selection framework.

## License

Skills are licensed under Apache 2.0. MCP servers are provided by their respective authors — see individual server documentation for terms.
