# nf-core/atacseq

**Version:** 2.1.2

**Official Documentation:** https://nf-co.re/atacseq/2.1.2/
**GitHub:** https://github.com/nf-core/atacseq

> **Note:** When updating to a new version, check the [releases page](https://github.com/nf-core/atacseq/releases) for breaking changes and update the version in commands below.

## Contents
- [Test command](#test-command)
- [Samplesheet format](#samplesheet-format)
- [Parameters](#parameters)
- [Output files](#output-files)
- [Quality metrics](#quality-metrics)

## Test command

```bash
nextflow run nf-core/atacseq -r 2.1.2 -profile test,docker --outdir test_atacseq
```

Expected: ~15 min, creates peaks and BigWig tracks.

## Samplesheet format

```csv
sample,fastq_1,fastq_2,replicate
CONTROL,/path/to/ctrl_rep1_R1.fq.gz,/path/to/ctrl_rep1_R2.fq.gz,1
CONTROL,/path/to/ctrl_rep2_R1.fq.gz,/path/to/ctrl_rep2_R2.fq.gz,2
TREATMENT,/path/to/treat_rep1_R1.fq.gz,/path/to/treat_rep1_R2.fq.gz,1
TREATMENT,/path/to/treat_rep2_R1.fq.gz,/path/to/treat_rep2_R2.fq.gz,2
```

| Column | Required | Description |
|--------|----------|-------------|
| sample | Yes | Condition/group identifier |
| fastq_1 | Yes | Absolute path to R1 |
| fastq_2 | Yes | Absolute path to R2 (paired-end required) |
| replicate | Yes | Replicate number (integer) |

### Design file for differential analysis
```csv
sample,condition
CONTROL,control
TREATMENT,treatment
```

Use with `--deseq2_design design.csv`.

## Parameters

### Minimal run
```bash
nextflow run nf-core/atacseq -r 2.1.2 -profile docker \
    --input samplesheet.csv --outdir results --genome GRCh38 --read_length 50
```

### Common parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--genome` | - | `GRCh38`, `GRCh37`, `mm10` |
| `--read_length` | 50 | Read length for MACS2 optimization |
| `--narrow_peak` | true | Narrow peaks (false for broad) |
| `--mito_name` | chrM | Mitochondrial chromosome name |
| `--keep_mito` | false | Keep mitochondrial reads |
| `--min_reps_consensus` | 1 | Min replicates for consensus peaks |

### Differential accessibility
```bash
--deseq2_design design.csv
```

## Output files

```
results/
├── bwa/mergedLibrary/
│   ├── *.mLb.mkD.sorted.bam     # Filtered, deduplicated alignments
│   └── bigwig/
│       └── *.bigWig             # Coverage tracks
├── macs2/narrowPeak/
│   ├── *.narrowPeak             # Peak calls
│   └── consensus/
│       └── consensus_peaks.bed  # Merged peaks across replicates
├── deeptools/
│   ├── plotFingerprint/         # Library complexity
│   └── plotProfile/             # TSS enrichment
├── deseq2/                      # If --deseq2_design provided
└── multiqc/
```

**Key outputs:**
- `*.mLb.mkD.sorted.bam`: Analysis-ready alignments
- `*.narrowPeak`: MACS2 peak calls (BED format)
- `consensus_peaks.bed`: Consensus peaks across replicates
- `*.bigWig`: Genome browser tracks

## Quality metrics

| Metric | Good | Acceptable | Poor |
|--------|------|------------|------|
| Mapped reads | >80% | 60-80% | <60% |
| Mitochondrial | <20% | 20-40% | >40% |
| Duplicates | <30% | 30-50% | >50% |
| FRiP | >30% | 15-30% | <15% |
| TSS enrichment | >6 | 4-6 | <4 |

**Fragment size**: Should show nucleosomal periodicity (~50bp nucleosome-free, ~200bp mono-nucleosome).

## Downstream analysis

```r
library(ChIPseeker)
library(GenomicRanges)
peaks <- import("consensus_peaks.bed")
peakAnno <- annotatePeak(peaks, TxDb = TxDb.Hsapiens.UCSC.hg38.knownGene)
```

**Motif analysis:**
```bash
findMotifsGenome.pl consensus_peaks.bed hg38 motifs/ -size 200
```

## Troubleshooting

**Low FRiP**: Check library complexity in `plotFingerprint/`. May indicate over-transposition.

**Few peaks**: Lower threshold with `--macs_qvalue 0.1` or use `--narrow_peak false` for broader peaks.

**High duplicates**: Normal for low-input; pipeline removes by default.

## More Information

- **Full parameter list:** https://nf-co.re/atacseq/2.1.2/parameters/
- **Output documentation:** https://nf-co.re/atacseq/2.1.2/docs/output/
- **Usage documentation:** https://nf-co.re/atacseq/2.1.2/docs/usage/
