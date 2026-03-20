# nf-core/rnaseq

**Version:** 3.22.2

**Official Documentation:** https://nf-co.re/rnaseq/3.22.2/
**GitHub:** https://github.com/nf-core/rnaseq

> **Note:** When updating to a new version, check the [releases page](https://github.com/nf-core/rnaseq/releases) for breaking changes and update the version in commands below.

## Contents
- [Test command](#test-command)
- [Samplesheet format](#samplesheet-format)
- [Parameters](#parameters)
- [Output files](#output-files)
- [Downstream analysis](#downstream-analysis)

## Test command

```bash
nextflow run nf-core/rnaseq -r 3.22.2 -profile test,docker --outdir test_rnaseq
```

Expected: ~15 min, creates `multiqc/multiqc_report.html`.

## Samplesheet format

```csv
sample,fastq_1,fastq_2,strandedness
CONTROL_REP1,/path/to/ctrl1_R1.fq.gz,/path/to/ctrl1_R2.fq.gz,auto
CONTROL_REP2,/path/to/ctrl2_R1.fq.gz,/path/to/ctrl2_R2.fq.gz,auto
TREATMENT_REP1,/path/to/treat1_R1.fq.gz,/path/to/treat1_R2.fq.gz,auto
```

| Column | Required | Values |
|--------|----------|--------|
| sample | Yes | Alphanumeric, underscores allowed |
| fastq_1 | Yes | Absolute path to R1 |
| fastq_2 | No | Absolute path to R2 (empty for single-end) |
| strandedness | Yes | `auto`, `forward`, `reverse`, `unstranded` |

**Strandedness guide:**
- `auto`: Inferred from data (recommended)
- `forward`: TruSeq Stranded, dUTP protocols
- `reverse`: Ligation-based protocols
- `unstranded`: Non-stranded protocols

## Parameters

### Minimal run
```bash
nextflow run nf-core/rnaseq -r 3.22.2 -profile docker \
    --input samplesheet.csv --outdir results --genome GRCh38
```

### Common parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--aligner` | `star_salmon` | Options: `star_salmon`, `star_rsem`, `hisat2` |
| `--genome` | - | `GRCh38`, `GRCh37`, `mm10`, `BDGP6` |
| `--pseudo_aligner` | - | Set to `salmon` for pseudo-alignment only |
| `--skip_trimming` | false | Skip adapter trimming |
| `--skip_alignment` | false | Pseudo-alignment only |

### Custom reference
```bash
--fasta /path/to/genome.fa \
--gtf /path/to/annotation.gtf \
--star_index /path/to/star/  # Optional, builds if absent
```

## Output files

```
results/
├── star_salmon/
│   ├── salmon.merged.gene_counts.tsv    # Raw counts for DESeq2
│   ├── salmon.merged.gene_tpm.tsv       # TPM values
│   └── *.bam                            # Alignments
├── multiqc/
│   └── multiqc_report.html              # QC summary
└── pipeline_info/
```

**Key outputs:**
- `salmon.merged.gene_counts.tsv`: Input for DESeq2/edgeR
- `salmon.merged.gene_tpm.tsv`: Normalized expression

## Downstream analysis

```r
library(DESeq2)
counts <- read.delim("salmon.merged.gene_counts.tsv", row.names=1)
coldata <- data.frame(
    condition = factor(c("control", "control", "treatment", "treatment"))
)
dds <- DESeqDataSetFromMatrix(
    countData = round(counts),
    colData = coldata,
    design = ~ condition
)
dds <- DESeq(dds)
res <- results(dds, contrast = c("condition", "treatment", "control"))
```

## Troubleshooting

**STAR index fails**: Increase memory with `--max_memory '64.GB'` or provide pre-built `--star_index`.

**Low alignment rate**: Verify genome matches species; check FastQC for adapter contamination.

**Strandedness detection fails**: Specify explicitly with `--strandedness reverse`.

## More Information

- **Full parameter list:** https://nf-co.re/rnaseq/3.22.2/parameters/
- **Output documentation:** https://nf-co.re/rnaseq/3.22.2/docs/output/
- **Usage documentation:** https://nf-co.re/rnaseq/3.22.2/docs/usage/
