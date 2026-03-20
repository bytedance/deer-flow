# nf-core/sarek

**Version:** 3.7.1

**Official Documentation:** https://nf-co.re/sarek/3.7.1/
**GitHub:** https://github.com/nf-core/sarek

> **Note:** When updating to a new version, check the [releases page](https://github.com/nf-core/sarek/releases) for breaking changes and update the version in commands below.

## Contents
- [Test command](#test-command)
- [Samplesheet format](#samplesheet-format)
- [Variant calling modes](#variant-calling-modes)
- [Parameters](#parameters)
- [Output files](#output-files)

## Test command

```bash
nextflow run nf-core/sarek -r 3.7.1 -profile test,docker --outdir test_sarek
```

Expected: ~20 min, creates aligned BAMs and variant calls.

## Samplesheet format

### From FASTQ
```csv
patient,sample,lane,fastq_1,fastq_2
patient1,tumor,L001,/path/to/tumor_L001_R1.fq.gz,/path/to/tumor_L001_R2.fq.gz
patient1,tumor,L002,/path/to/tumor_L002_R1.fq.gz,/path/to/tumor_L002_R2.fq.gz
patient1,normal,L001,/path/to/normal_R1.fq.gz,/path/to/normal_R2.fq.gz
```

### From BAM/CRAM
```csv
patient,sample,bam,bai
patient1,tumor,/path/to/tumor.bam,/path/to/tumor.bam.bai
patient1,normal,/path/to/normal.bam,/path/to/normal.bam.bai
```

### With tumor/normal status
```csv
patient,sample,lane,fastq_1,fastq_2,status
patient1,tumor,L001,tumor_R1.fq.gz,tumor_R2.fq.gz,1
patient1,normal,L001,normal_R1.fq.gz,normal_R2.fq.gz,0
```

`status`: 0 = normal, 1 = tumor

## Variant calling modes

### Germline (single sample)
```bash
nextflow run nf-core/sarek -r 3.7.1 -profile docker \
    --input samplesheet.csv --outdir results --genome GRCh38 \
    --tools haplotypecaller,snpeff
```

### Somatic (tumor-normal pair)
```bash
nextflow run nf-core/sarek -r 3.7.1 -profile docker \
    --input samplesheet.csv --outdir results --genome GRCh38 \
    --tools mutect2,strelka,snpeff
```

### WES (exome)
```bash
nextflow run nf-core/sarek -r 3.7.1 -profile docker \
    --input samplesheet.csv --outdir results --genome GRCh38 \
    --wes --intervals /path/to/targets.bed \
    --tools haplotypecaller,snpeff
```

### Joint germline (cohort)
```bash
--tools haplotypecaller --joint_germline
```

## Parameters

### Available tools

**Germline callers:**
- `haplotypecaller`: GATK HaplotypeCaller
- `freebayes`: FreeBayes
- `deepvariant`: DeepVariant (GPU optional)
- `strelka`: Strelka2 germline

**Somatic callers:**
- `mutect2`: GATK Mutect2
- `strelka`: Strelka2 somatic
- `manta`: Structural variants

**CNV callers:**
- `ascat`: Copy number
- `controlfreec`: CNV detection
- `tiddit`: SV calling

**Annotation:**
- `snpeff`: Functional annotation
- `vep`: Variant Effect Predictor

### Key parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--tools` | - | Comma-separated list of tools |
| `--genome` | - | `GRCh38`, `GRCh37` |
| `--wes` | false | Exome mode (requires `--intervals`) |
| `--intervals` | - | BED file for targeted regions |
| `--joint_germline` | false | Joint calling for cohorts |
| `--skip_bqsr` | false | Skip base quality recalibration |

## Output files

```
results/
├── preprocessing/
│   └── recalibrated/           # Analysis-ready BAMs
│       └── *.recal.bam
├── variant_calling/
│   ├── haplotypecaller/        # Germline VCFs
│   ├── mutect2/                # Somatic VCFs (filtered)
│   └── strelka/
├── annotation/
│   └── snpeff/                 # Annotated VCFs
└── multiqc/
```

## Troubleshooting

**BQSR fails**: Check known sites available for genome. Skip with `--skip_bqsr` for non-standard references.

**Mutect2 no variants**: Verify tumor/normal pairing in samplesheet (check `status` column).

**Out of memory**: `--max_memory '128.GB'` for WGS.

**DeepVariant GPU**: Ensure NVIDIA Docker runtime configured.

## More Information

- **Full parameter list:** https://nf-co.re/sarek/3.7.1/parameters/
- **Output documentation:** https://nf-co.re/sarek/3.7.1/docs/output/
- **Usage documentation:** https://nf-co.re/sarek/3.7.1/docs/usage/
