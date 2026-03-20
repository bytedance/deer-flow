# Troubleshooting

Quick fixes for common nf-core pipeline issues.

## Contents
- [Exit Codes](#exit-codes)
- [HPC/Singularity Issues](#hpcsingularity-issues)
- [Pipeline Failures](#pipeline-failures)
- [RNA-seq Specific](#rna-seq-specific)
- [Sarek Specific](#sarek-specific)
- [ATAC-seq Specific](#atac-seq-specific)
- [Resource Management](#resource-management)
- [Getting Help](#getting-help)

## Exit Codes

Common exit codes indicating resource issues (per [nf-core docs](https://nf-co.re/docs/usage/troubleshooting/crash_halfway)):

| Code | Cause | Fix |
|------|-------|-----|
| 137 | Out of memory | `--max_memory '32.GB'` or `'64.GB'` for WGS |
| 143 | Out of memory | `--max_memory '32.GB'` or `'64.GB'` for WGS |
| 104, 134, 139, 247 | Out of memory | Increase `--max_memory` |
| 1 | General error | Check `.nextflow.log` for details |

Most pipelines auto-retry with 2x then 3x resources before failing.

## HPC/Singularity Issues

### Singularity cache issues
```bash
export NXF_SINGULARITY_CACHEDIR="$HOME/.singularity/cache"
mkdir -p $NXF_SINGULARITY_CACHEDIR
```

### Using Singularity instead of Docker
On HPC systems without Docker, use Singularity:
```bash
nextflow run nf-core/<pipeline> -profile singularity ...
```

> **Note**: For basic environment setup (Docker, Nextflow, Java installation), see the inline instructions in Step 1 of SKILL.md.

## Pipeline Failures

### Container pull failed
- Check network connectivity
- Try: `-profile singularity` instead of docker
- For offline: `nf-core download <pipeline> -r <version>`

### "No such file" errors
- Use **absolute paths** in samplesheet
- Verify files exist: `ls /path/to/file`

### Resume not working
```bash
# Check work directory exists
ls -la work/

# Force clean restart (loses cache)
rm -rf work/ .nextflow*
nextflow run nf-core/<pipeline> ...
```

## RNA-seq Specific

### STAR index fails
- Increase memory: `--max_memory '64.GB'`
- Or provide pre-built: `--star_index /path/to/star/`

### Low alignment rate
- Verify genome matches species
- Check FastQC for adapter contamination
- Try different aligner: `--aligner hisat2`

### Strandedness detection fails
- Specify explicitly: `--strandedness reverse`
- Common values: `forward`, `reverse`, `unstranded`

## Sarek Specific

### BQSR fails
- Check known sites for genome
- Skip for non-standard references: `--skip_bqsr`

### Mutect2 no variants
- Verify tumor/normal pairing
- Check samplesheet `status` column: 0=normal, 1=tumor

### Out of memory for WGS
```bash
--max_memory '128.GB' --max_cpus 16
```

### DeepVariant GPU issues
- Ensure NVIDIA Docker runtime configured
- Or use CPU mode (slower)

## ATAC-seq Specific

### Low FRiP score
- Check library complexity in `plotFingerprint/`
- May indicate over-transposition

### Few peaks called
- Lower threshold: `--macs_qvalue 0.1`
- Use broad peaks: `--narrow_peak false`

### High duplicates
- Normal for low-input samples
- Pipeline removes by default
- Consider deeper sequencing

## Resource Management

### Set resource limits
```bash
--max_cpus 8 --max_memory '32.GB' --max_time '24.h'
```

### Check available resources
```bash
# CPUs
nproc

# Memory
free -h

# Disk
df -h .
```

## Getting Help

1. Check `.nextflow.log` for error details
2. Search nf-core Slack: https://nf-co.re/join
3. Open issue on GitHub: https://github.com/nf-core/<pipeline>/issues
