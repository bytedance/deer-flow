---
name: nextflow-development
description: Run nf-core bioinformatics pipelines (rnaseq, sarek, atacseq) on sequencing data. Use when analyzing RNA-seq, WGS/WES, or ATAC-seq data—either local FASTQs or public datasets from GEO/SRA. Triggers on nf-core, Nextflow, FASTQ analysis, variant calling, gene expression, differential expression, GEO reanalysis, GSE/GSM/SRR accessions, or samplesheet creation.
---

# nf-core Pipeline Deployment

Run nf-core bioinformatics pipelines on local or public sequencing data.

**Target users:** Bench scientists and researchers without specialized bioinformatics training who need to run large-scale omics analyses—differential expression, variant calling, or chromatin accessibility analysis.

## Workflow Checklist

```
- [ ] Step 0: Acquire data (if from GEO/SRA)
- [ ] Step 1: Environment check (MUST pass)
- [ ] Step 2: Select pipeline (confirm with user)
- [ ] Step 3: Run test profile (MUST pass)
- [ ] Step 4: Create samplesheet
- [ ] Step 5: Configure & run (confirm genome with user)
- [ ] Step 6: Verify outputs
```

---

## Step 0: Acquire Data (GEO/SRA Only)

**Skip this step if user has local FASTQ files.**

For public datasets, fetch from GEO/SRA first. See [references/geo-sra-acquisition.md](references/geo-sra-acquisition.md) for the full workflow.

**Quick start:**

```bash
# 1. Get study info
python scripts/sra_geo_fetch.py info GSE110004

# 2. Download (interactive mode)
python scripts/sra_geo_fetch.py download GSE110004 -o ./fastq -i

# 3. Generate samplesheet
python scripts/sra_geo_fetch.py samplesheet GSE110004 --fastq-dir ./fastq -o samplesheet.csv
```

**DECISION POINT:** After fetching study info, confirm with user:
- Which sample subset to download (if multiple data types)
- Suggested genome and pipeline

Then continue to Step 1.

---

## Step 1: Environment Check

**Run first. Pipeline will fail without passing environment.**

```bash
python scripts/check_environment.py
```

All critical checks must pass. If any fail, provide fix instructions:

### Docker issues

| Problem | Fix |
|---------|-----|
| Not installed | Install from https://docs.docker.com/get-docker/ |
| Permission denied | `sudo usermod -aG docker $USER` then re-login |
| Daemon not running | `sudo systemctl start docker` |

### Nextflow issues

| Problem | Fix |
|---------|-----|
| Not installed | `curl -s https://get.nextflow.io \| bash && mv nextflow ~/bin/` |
| Version < 23.04 | `nextflow self-update` |

### Java issues

| Problem | Fix |
|---------|-----|
| Not installed / < 11 | `sudo apt install openjdk-11-jdk` |

**Do not proceed until all checks pass.** For HPC/Singularity, see [references/troubleshooting.md](references/troubleshooting.md).

---

## Step 2: Select Pipeline

**DECISION POINT: Confirm with user before proceeding.**

| Data Type | Pipeline | Version | Goal |
|-----------|----------|---------|------|
| RNA-seq | `rnaseq` | 3.22.2 | Gene expression |
| WGS/WES | `sarek` | 3.7.1 | Variant calling |
| ATAC-seq | `atacseq` | 2.1.2 | Chromatin accessibility |

Auto-detect from data:
```bash
python scripts/detect_data_type.py /path/to/data
```

For pipeline-specific details:
- [references/pipelines/rnaseq.md](references/pipelines/rnaseq.md)
- [references/pipelines/sarek.md](references/pipelines/sarek.md)
- [references/pipelines/atacseq.md](references/pipelines/atacseq.md)

---

## Step 3: Run Test Profile

**Validates environment with small data. MUST pass before real data.**

```bash
nextflow run nf-core/<pipeline> -r <version> -profile test,docker --outdir test_output
```

| Pipeline | Command |
|----------|---------|
| rnaseq | `nextflow run nf-core/rnaseq -r 3.22.2 -profile test,docker --outdir test_rnaseq` |
| sarek | `nextflow run nf-core/sarek -r 3.7.1 -profile test,docker --outdir test_sarek` |
| atacseq | `nextflow run nf-core/atacseq -r 2.1.2 -profile test,docker --outdir test_atacseq` |

Verify:
```bash
ls test_output/multiqc/multiqc_report.html
grep "Pipeline completed successfully" .nextflow.log
```

If test fails, see [references/troubleshooting.md](references/troubleshooting.md).

---

## Step 4: Create Samplesheet

### Generate automatically

```bash
python scripts/generate_samplesheet.py /path/to/data <pipeline> -o samplesheet.csv
```

The script:
- Discovers FASTQ/BAM/CRAM files
- Pairs R1/R2 reads
- Infers sample metadata
- Validates before writing

**For sarek:** Script prompts for tumor/normal status if not auto-detected.

### Validate existing samplesheet

```bash
python scripts/generate_samplesheet.py --validate samplesheet.csv <pipeline>
```

### Samplesheet formats

**rnaseq:**
```csv
sample,fastq_1,fastq_2,strandedness
SAMPLE1,/abs/path/R1.fq.gz,/abs/path/R2.fq.gz,auto
```

**sarek:**
```csv
patient,sample,lane,fastq_1,fastq_2,status
patient1,tumor,L001,/abs/path/tumor_R1.fq.gz,/abs/path/tumor_R2.fq.gz,1
patient1,normal,L001,/abs/path/normal_R1.fq.gz,/abs/path/normal_R2.fq.gz,0
```

**atacseq:**
```csv
sample,fastq_1,fastq_2,replicate
CONTROL,/abs/path/ctrl_R1.fq.gz,/abs/path/ctrl_R2.fq.gz,1
```

---

## Step 5: Configure & Run

### 5a. Check genome availability

```bash
python scripts/manage_genomes.py check <genome>
# If not installed:
python scripts/manage_genomes.py download <genome>
```

Common genomes: GRCh38 (human), GRCh37 (legacy), GRCm39 (mouse), R64-1-1 (yeast), BDGP6 (fly)

### 5b. Decision points

**DECISION POINT: Confirm with user:**

1. **Genome:** Which reference to use
2. **Pipeline-specific options:**
   - **rnaseq:** aligner (star_salmon recommended, hisat2 for low memory)
   - **sarek:** tools (haplotypecaller for germline, mutect2 for somatic)
   - **atacseq:** read_length (50, 75, 100, or 150)

### 5c. Run pipeline

```bash
nextflow run nf-core/<pipeline> \
    -r <version> \
    -profile docker \
    --input samplesheet.csv \
    --outdir results \
    --genome <genome> \
    -resume
```

**Key flags:**
- `-r`: Pin version
- `-profile docker`: Use Docker (or `singularity` for HPC)
- `--genome`: iGenomes key
- `-resume`: Continue from checkpoint

**Resource limits (if needed):**
```bash
--max_cpus 8 --max_memory '32.GB' --max_time '24.h'
```

---

## Step 6: Verify Outputs

### Check completion

```bash
ls results/multiqc/multiqc_report.html
grep "Pipeline completed successfully" .nextflow.log
```

### Key outputs by pipeline

**rnaseq:**
- `results/star_salmon/salmon.merged.gene_counts.tsv` - Gene counts
- `results/star_salmon/salmon.merged.gene_tpm.tsv` - TPM values

**sarek:**
- `results/variant_calling/*/` - VCF files
- `results/preprocessing/recalibrated/` - BAM files

**atacseq:**
- `results/macs2/narrowPeak/` - Peak calls
- `results/bwa/mergedLibrary/bigwig/` - Coverage tracks

---

## Quick Reference

For common exit codes and fixes, see [references/troubleshooting.md](references/troubleshooting.md).

### Resume failed run

```bash
nextflow run nf-core/<pipeline> -resume
```

---

## References

- [references/geo-sra-acquisition.md](references/geo-sra-acquisition.md) - Downloading public GEO/SRA data
- [references/troubleshooting.md](references/troubleshooting.md) - Common issues and fixes
- [references/installation.md](references/installation.md) - Environment setup
- [references/pipelines/rnaseq.md](references/pipelines/rnaseq.md) - RNA-seq pipeline details
- [references/pipelines/sarek.md](references/pipelines/sarek.md) - Variant calling details
- [references/pipelines/atacseq.md](references/pipelines/atacseq.md) - ATAC-seq details

---

## Disclaimer

This skill is provided as a prototype example demonstrating how to integrate nf-core bioinformatics pipelines into Claude Code for automated analysis workflows. The current implementation supports three pipelines (rnaseq, sarek, and atacseq), serving as a foundation that enables the community to expand support to the full set of nf-core pipelines.

It is intended for educational and research purposes and should not be considered production-ready without appropriate validation for your specific use case. Users are responsible for ensuring their computing environment meets pipeline requirements and for verifying analysis results.

Anthropic does not guarantee the accuracy of bioinformatics outputs, and users should follow standard practices for validating computational analyses. This integration is not officially endorsed by or affiliated with the nf-core community.

## Attribution

When publishing results, cite the appropriate pipeline. Citations are available in each nf-core repository's CITATIONS.md file (e.g., https://github.com/nf-core/rnaseq/blob/3.22.2/CITATIONS.md).

## Licenses

- **nf-core pipelines:** MIT License (https://nf-co.re/about)
- **Nextflow:** Apache License, Version 2.0 (https://www.nextflow.io/about-us.html)
- **NCBI SRA Toolkit:** Public Domain (https://github.com/ncbi/sra-tools/blob/master/LICENSE)
