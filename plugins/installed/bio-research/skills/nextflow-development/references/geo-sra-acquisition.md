# GEO/SRA Data Acquisition

Download raw sequencing data from NCBI GEO/SRA and prepare it for nf-core pipelines.

**Use this when:** Reanalyzing published datasets, validating findings, or comparing results against public cohorts.

## Table of Contents

- [Workflow Overview](#workflow-overview)
- [Step 1: Fetch Study Information](#step-1-fetch-study-information)
- [Step 2: Review Sample Groups](#step-2-review-sample-groups)
- [Step 3: Download FASTQ Files](#step-3-download-fastq-files)
- [Step 4: Generate Samplesheet](#step-4-generate-samplesheet)
- [Step 5: Run nf-core Pipeline](#step-5-run-nf-core-pipeline)
- [Supported Pipelines](#supported-pipelines)
- [Supported Organisms](#supported-organisms)
- [Complete Example](#complete-example)
- [Troubleshooting](#troubleshooting)

---

## Workflow Overview

Example: "Find differentially expressed genes in GSE309891 (drug-treated vs control)"

```
┌─────────────────────────────────────────────────────────────────┐
│                    GEO/SRA DATA ACQUISITION                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │   Fetch study info     │
                 │   • Query NCBI/SRA     │
                 │   • Get metadata       │
                 │   • Detect organism    │
                 │   • Identify data type │
                 └────────────────────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │   Present summary      │
                 │   • Organism: Human    │
                 │   • Genome: GRCh38     │
                 │   • Type: RNA-Seq      │
                 │   • Pipeline: rnaseq   │
                 │   • Samples: 12        │
                 │     (6 treated,        │
                 │      6 control)        │
                 │   • Size: ~24 GB       │
                 └────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  USER CONFIRMS  │◄──── Decision point
                    │  genome/pipeline│
                    └─────────────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │   Select samples       │
                 │   • Group by condition │
                 │   • Show treated/ctrl  │
                 └────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  USER SELECTS   │◄──── Decision point
                    │  sample subset  │
                    └─────────────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │   Download FASTQs      │
                 │   • 24 files (R1+R2)   │
                 │   • Parallel transfers │
                 │   • Auto-resume        │
                 └────────────────────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │   Generate samplesheet │
                 │   • Map SRR to files   │
                 │   • Pair R1/R2         │
                 │   • Assign conditions  │
                 └────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    NF-CORE PIPELINE EXECUTION                   │
│              (Continue with Step 1 of main workflow)            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Instructions for Claude

When assisting users with GEO/SRA data acquisition:

1. **Always fetch study info first** to show the user what data is available
2. **Ask for confirmation before downloading** - Present the sample groups and sizes, then ask which subset to download using AskUserQuestion
3. **Suggest appropriate genome and pipeline** based on the organism and data type
4. **Return to main SKILL.md workflow** after data preparation is complete

Example confirmation question:
```
Question: "Which sample group would you like to download?"
Options:
  - "RNA-Seq:PAIRED (42 samples, ~87 GB)"
  - "RNA-Seq:SINGLE (7 samples, ~4.5 GB)"
  - "All samples (49 samples, ~92 GB)"
```

---

## Step 1: Fetch Study Information

Get metadata about a GEO study before downloading.

```bash
python scripts/sra_geo_fetch.py info <GEO_ID>
```

**Example:**
```bash
python scripts/sra_geo_fetch.py info GSE110004
```

**Output includes:**
- Study title and summary
- Organism (with auto-suggested genome)
- Number of samples and runs
- Data types (RNA-Seq, ATAC-seq, etc.)
- Estimated download size
- Suggested nf-core pipeline

**Save info to JSON:**
```bash
python scripts/sra_geo_fetch.py info GSE110004 -o study_info.json
```

---

## Step 2: Review Sample Groups

View sample groups organized by data type and layout. This is useful for studies with mixed data types.

```bash
python scripts/sra_geo_fetch.py groups <GEO_ID>
```

**Example output:**
```
Sample Group          Count Layout     GSM Range                    Est. Size
--------------------------------------------------------------------------------
RNA-Seq                  42 PAIRED     GSM2879618...(42 samples)      87.4 GB
RNA-Seq                   7 SINGLE     GSM2976181-GSM2976187           4.5 GB
--------------------------------------------------------------------------------
TOTAL                    49                                           91.9 GB

Available groups for --subset option:
  1. "RNA-Seq:PAIRED" - 42 samples (~87.4 GB)
  2. "RNA-Seq:SINGLE" - 7 samples (~4.5 GB)
```

**List individual runs:**
```bash
python scripts/sra_geo_fetch.py list <GEO_ID>

# Filter by data type
python scripts/sra_geo_fetch.py list GSE110004 --filter "RNA-Seq:PAIRED"
```

**DECISION POINT:** Review the sample groups. Decide which subset to download if the study has multiple data types.

---

## Step 3: Download FASTQ Files

Download FASTQ files from ENA (faster than SRA).

```bash
python scripts/sra_geo_fetch.py download <GEO_ID> -o <OUTPUT_DIR>
```

**Options:**
- `-o, --output`: Output directory (required)
- `-i, --interactive`: Interactively select sample group to download
- `-s, --subset`: Filter by data type (e.g., "RNA-Seq:PAIRED")
- `-p, --parallel`: Parallel downloads (default: 4)
- `-t, --timeout`: Download timeout in seconds (default: 600)

### Interactive Mode (Recommended)

Use `-i` flag for interactive sample selection when the study has multiple data types:

```bash
python scripts/sra_geo_fetch.py download GSE110004 -o ./fastq -i
```

**Interactive output:**
```
============================================================
  SELECT SAMPLE GROUP TO DOWNLOAD
============================================================

  [1] RNA-Seq (paired)
      Samples: 42
      GSM: GSM2879618...(42 samples)
      Size: ~87.4 GB

  [2] RNA-Seq (single)
      Samples: 7
      GSM: GSM2976181-GSM2976187
      Size: ~4.5 GB

  [0] Download ALL (49 samples)
------------------------------------------------------------

Enter selection (0-2):
```

### Direct Subset Selection

Alternatively, specify the subset directly:

```bash
# Download only RNA-Seq paired-end data
python scripts/sra_geo_fetch.py download GSE110004 -o ./fastq \
    --subset "RNA-Seq:PAIRED" --parallel 6
```

**Note:** Downloads automatically skip existing files. Resume interrupted downloads by re-running the command.

---

## Step 4: Generate Samplesheet

Create a samplesheet compatible with nf-core pipelines.

```bash
python scripts/sra_geo_fetch.py samplesheet <GEO_ID> \
    --fastq-dir <FASTQ_DIR> \
    -o samplesheet.csv
```

**Options:**
- `-f, --fastq-dir`: Directory containing downloaded FASTQ files (required)
- `-o, --output`: Output samplesheet path (default: samplesheet.csv)
- `-p, --pipeline`: Target pipeline (auto-detected if not specified)

**Example:**
```bash
python scripts/sra_geo_fetch.py samplesheet GSE110004 \
    --fastq-dir ./fastq \
    -o samplesheet.csv
```

**Output:** The script will:
1. Create samplesheet in the format required by the target pipeline
2. Display suggested genome reference
3. Show suggested nf-core command

---

## Step 5: Run nf-core Pipeline

After generating the samplesheet, the script provides a suggested command.

**Example output:**
```
Suggested command:
   nextflow run nf-core/rnaseq \
       --input samplesheet.csv \
       --outdir results \
       --genome R64-1-1 \
       -profile docker
```

**DECISION POINT:** Review and confirm:
1. Is the suggested pipeline correct?
2. Is the genome reference correct for your organism?
3. Do you need additional pipeline options?

Then return to the main SKILL.md workflow (Step 1: Environment Check) to proceed with pipeline execution.

---

## Supported Pipelines

The skill auto-detects appropriate pipelines based on library strategy. Pipelines marked with ★ are fully supported with configs, samplesheet generation, and documentation. Others are suggested but require manual setup following nf-core documentation.

| Library Strategy | Suggested Pipeline | Support |
|------------------|--------------------|---------|
| RNA-Seq          | nf-core/rnaseq     | ★ Full  |
| ATAC-seq         | nf-core/atacseq    | ★ Full  |
| WGS/WXS          | nf-core/sarek      | ★ Full  |
| ChIP-seq         | nf-core/chipseq    | Manual  |
| Bisulfite-Seq    | nf-core/methylseq  | Manual  |
| miRNA-Seq        | nf-core/smrnaseq   | Manual  |
| Amplicon         | nf-core/ampliseq   | Manual  |

---

## Supported Organisms

Common organisms with auto-suggested genomes:

| Organism | Genome | Notes |
|----------|--------|-------|
| Homo sapiens | GRCh38 | Human reference |
| Mus musculus | GRCm39 | Mouse reference |
| Saccharomyces cerevisiae | R64-1-1 | Yeast S288C |
| Drosophila melanogaster | BDGP6 | Fruit fly |
| Caenorhabditis elegans | WBcel235 | C. elegans |
| Danio rerio | GRCz11 | Zebrafish |
| Arabidopsis thaliana | TAIR10 | Arabidopsis |
| Rattus norvegicus | Rnor_6.0 | Rat |

See `scripts/config/genomes.yaml` for the full list.

---

## Complete Example

Reanalyze GSE110004 (yeast RNA-seq):

```bash
# 1. Get study info and sample groups
python scripts/sra_geo_fetch.py info GSE110004

# 2. Download with interactive selection
python scripts/sra_geo_fetch.py download GSE110004 -o ./fastq -i
# Select option [1] for RNA-Seq paired-end samples

# 3. Generate samplesheet
python scripts/sra_geo_fetch.py samplesheet GSE110004 \
    --fastq-dir ./fastq \
    -o samplesheet.csv

# 4. Run nf-core/rnaseq (continue with main SKILL.md workflow)
nextflow run nf-core/rnaseq \
    --input samplesheet.csv \
    --outdir results \
    --genome R64-1-1 \
    -profile docker
```

### Alternative: Non-interactive Download

```bash
# Review sample groups first
python scripts/sra_geo_fetch.py groups GSE110004

# Download specific subset directly
python scripts/sra_geo_fetch.py download GSE110004 \
    --subset "RNA-Seq:PAIRED" \
    -o ./fastq \
    --parallel 4
```

---

## Troubleshooting

### ENA Download Fails
If ENA downloads fail, the data may need to be fetched directly from SRA:

```bash
# Create SRA tools environment
conda create -n sra_tools -c bioconda sra-tools

# Download with prefetch + fasterq-dump
conda run -n sra_tools prefetch SRR6357070
conda run -n sra_tools fasterq-dump SRR6357070 -O ./fastq
```

### No SRA Runs Found
Some GEO datasets only have processed data, not raw sequencing reads. Check:
```bash
python scripts/sra_geo_fetch.py info <GEO_ID>
```
If "Runs: 0", the dataset may not have raw data in SRA.

### SuperSeries Support
GEO SuperSeries (which contain multiple SubSeries) are automatically handled. The tool will:
1. Detect that a GEO ID is a SuperSeries
2. Find the linked BioProject accession
3. Fetch all SRA runs from the BioProject

Example: GSE110004 is a SuperSeries that links to BioProject PRJNA432544.

### Genome Not Recognized
If the organism is not in the genome mapping, manually specify the genome:
```bash
# Check available iGenomes
python scripts/manage_genomes.py list

# Or provide custom reference files to nf-core
nextflow run nf-core/rnaseq --fasta /path/to/genome.fa --gtf /path/to/genes.gtf
```

---

## Requirements

- Python 3.8+
- `requests` library (optional but recommended)
- `pyyaml` library (optional, for genome config)
- Network access to NCBI and ENA

Install optional dependencies:
```bash
pip install requests pyyaml
```
