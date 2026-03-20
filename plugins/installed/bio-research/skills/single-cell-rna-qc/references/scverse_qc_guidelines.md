# scverse Quality Control Guidelines

This document provides detailed information about quality control best practices for single-cell RNA-seq data, following the scverse ecosystem recommendations.

## Quality Control Metrics

### Count Depth (Total Counts)
- **What it measures**: Total number of UMI/reads per cell
- **Why it matters**: Low count cells may be empty droplets, debris, or poorly captured cells
- **Typical range**: 500-50,000 counts per cell (varies by protocol)
- **Red flags**: Bimodal distributions may indicate mixing of high and low-quality cells

### Gene Detection (Genes per Cell)
- **What it measures**: Number of genes with at least 1 count
- **Why it matters**: Strongly correlates with count depth; low values indicate poor capture
- **Typical range**: 200-5,000 genes per cell
- **Red flags**: Very low values (<200) suggest technical failures

### Mitochondrial Content
- **What it measures**: Percentage of counts from mitochondrial genes
- **Why it matters**: High MT% indicates cell stress, apoptosis, or lysed cells
- **Typical range**: <5% for most tissues, up to 10-15% for metabolically active cells
- **Species-specific patterns**:
  - Mouse: Genes start with 'mt-' (e.g., mt-Nd1, mt-Co1)
  - Human: Genes start with 'MT-' (e.g., MT-ND1, MT-CO1)
- **Context matters**: Some cell types (cardiomyocytes, neurons) naturally have higher MT content

### Ribosomal Content
- **What it measures**: Percentage of counts from ribosomal protein genes
- **Why it matters**: Can indicate cell state or contamination
- **Patterns**: Genes start with 'Rpl'/'RPL' (large subunit) or 'Rps'/'RPS' (small subunit)
- **Note**: High ribosomal content isn't always bad - metabolically active cells have more ribosomes

### Hemoglobin Content
- **What it measures**: Percentage of counts from hemoglobin genes
- **Why it matters**: Indicates blood contamination in non-blood tissues
- **Patterns**: Genes matching '^Hb[^(p)]' or '^HB[^(P)]' (excludes Hbp1/HBP1)
- **When to use**: Particularly important for tissue samples (brain, liver, etc.)

## MAD-Based Filtering Rationale

### Why MAD Instead of Fixed Thresholds?

Fixed thresholds (e.g., "remove cells with <500 genes") fail because:
- Different protocols yield different ranges
- Different tissues have different characteristics
- Different species have different gene counts
- Fixed thresholds are arbitrary and not data-driven

MAD (Median Absolute Deviation) is robust to outliers and adapts to your dataset:
```
MAD = median(|X - median(X)|)
Outlier bounds = median ± n_MADs × MAD
```

### Recommended MAD Thresholds

Following scverse best practices (deliberately permissive):

**5 MADs for count depth (log-transformed)**
- Very permissive to retain rare cell populations
- Catches extreme outliers (empty droplets, debris)
- Log transformation handles the typical right-skewed distribution

**5 MADs for gene counts (log-transformed)**
- Parallels count depth filtering
- Most informative when combined with count filtering
- Log transformation normalizes the distribution

**3 MADs for mitochondrial percentage**
- More stringent because high MT% strongly indicates dying cells
- Uses raw percentages (not log-transformed)
- Combined with hard threshold for extra stringency

**Hard threshold: 8% mitochondrial content**
- Additional filter beyond MAD-based detection
- Conservative cutoff that works across most tissues
- Adjust higher (10-15%) for metabolically active cell types

### Why Be Permissive?

The default thresholds intentionally err on the side of keeping cells because:
1. **Rare populations**: Stringent filtering may remove rare but viable cell types
2. **Biological variation**: Some healthy cells naturally have extreme values
3. **Reversibility**: Easier to filter more later than to recover lost cells
4. **Downstream robustness**: Modern normalization methods handle moderate quality variation

## Interpreting QC Visualizations

### Histograms
- **Bimodal distributions**: May indicate mixing of cell types or quality issues
- **Long tails**: Common for count depth; MAD filtering handles this
- **Sharp cutoffs**: May indicate prior filtering or technical artifacts

### Violin Plots
- Shows distribution shape and density
- Median (line) and mean (diamond) should be similar for symmetric distributions
- Wide distributions suggest high heterogeneity

### Scatter Plots

**Counts vs Genes (colored by MT%)**
- Should show strong positive correlation (R² > 0.8 typical)
- Points deviating from trend may be outliers
- High MT% cells often cluster at low counts/genes

**Counts vs MT%**
- Negative correlation expected (dying cells have fewer counts)
- Vertical stratification may indicate batch effects
- Cells with high counts + high MT% are suspicious

**Genes vs MT%**
- Similar to counts vs MT%, but often weaker correlation
- Useful for identifying cells with gene detection issues

## Gene Filtering

After filtering cells, remove genes detected in fewer than 20 cells:
- **Why 20?**: Balances noise reduction with information retention
- **Benefits**: Reduces dataset size, speeds up computation, removes noisy genes
- **Trade-offs**: May lose very rare markers; adjust to 10 if studying rare populations

## Species-Specific Considerations

### Mouse (Mus musculus)
- Mitochondrial genes: mt-* (lowercase)
- Ribosomal genes: Rpl*, Rps* (capitalized first letter)
- Hemoglobin genes: Hb* (but not Hbp1)

### Human (Homo sapiens)
- Mitochondrial genes: MT-* (uppercase)
- Ribosomal genes: RPL*, RPS* (all uppercase)
- Hemoglobin genes: HB* (but not HBP1)

### Other Species
Adjust gene name patterns in the script to match your organism's gene nomenclature. Consult Ensembl or your reference annotation for correct prefixes.

## When to Adjust Parameters

Consider adjusting filtering thresholds when:

**More stringent (lower MADs)**
- High ambient RNA contamination suspected
- Many low-quality cells observed in visualizations
- Downstream analysis shows quality-driven clustering

**More permissive (higher MADs)**
- Studying rare cell populations
- Dataset has high technical quality
- Cell types naturally have extreme values (e.g., neurons with high MT%)

**Tissue-specific adjustments**
- Brain/neurons: May need higher MT% threshold (10-15%)
- Blood: Can be more stringent with MT% (5-8%)
- Tumor samples: Often need more permissive thresholds due to biological variation

## Advanced QC Considerations

### Not Included in This Workflow

**Ambient RNA correction**
- Tool: SoupX, CellBender, DecontX
- When: High background RNA in droplet-based data
- Effect: Removes contamination from lysed cells

**Doublet detection**
- Tool: scDblFinder, scrublet, DoubletFinder
- When: Always recommended for droplet-based data
- Effect: Identifies and removes multiplets (2+ cells in one droplet)

**Cell cycle scoring**
- Tool: scanpy's score_genes_cell_cycle
- When: Cell cycle effects confound biological signal
- Effect: Allows regressing out or accounting for cell cycle phase

**Batch correction**
- Tool: Harmony, scVI, ComBat
- When: Integrating data from multiple batches/experiments
- Effect: Removes technical batch effects while preserving biology

## References

- scverse Best Practices: https://www.sc-best-practices.org/preprocessing_visualization/quality_control.html
- Luecken & Theis (2019): Current best practices in single-cell RNA-seq analysis
- Osorio & Cai (2021): Systematic determination of the mitochondrial proportion in human and mouse genomes
- Germain et al. (2020): Doublet identification in single-cell sequencing data using scDblFinder
