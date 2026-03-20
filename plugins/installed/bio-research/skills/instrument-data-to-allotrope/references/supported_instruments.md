# Supported Instruments

## What Can This Skill Convert?

**Any instrument data that maps to an Allotrope schema can be converted.** The skill uses a tiered parsing approach:

1. **Native allotropy parsers** (listed below) - Highest fidelity, validated against vendor-specific formats
2. **Flexible fallback parser** - Handles any tabular data (CSV, Excel, TXT) by mapping columns to ASM fields
3. **PDF extraction** - Extracts tables from PDFs, then applies flexible parsing

If your instrument isn't listed below, the skill can still convert it as long as your data contains recognizable measurement fields (sample IDs, values, units, timestamps, etc.) that map to an ASM technique schema.

---

## Instruments with Native Allotropy Parsers

The following instruments have optimized parsers in the allotropy library with their Vendor enum values.

## Cell Counting

| Instrument | Vendor Enum | File Types |
|------------|-------------|------------|
| Beckman Coulter Vi-CELL BLU | `BECKMAN_VI_CELL_BLU` | .csv |
| Beckman Coulter Vi-CELL XR | `BECKMAN_VI_CELL_XR` | .txt, .xls, .xlsx |
| ChemoMetec NucleoView NC-200 | `CHEMOMETEC_NUCLEOVIEW` | .xlsx |
| ChemoMetec NC-View | `CHEMOMETEC_NC_VIEW` | .xlsx |
| Revvity Matrix | `REVVITY_MATRIX` | .csv |

## Spectrophotometry (UV-Vis)

| Instrument | Vendor Enum | File Types |
|------------|-------------|------------|
| Thermo Fisher NanoDrop One | `THERMO_FISHER_NANODROP_ONE` | .csv, .xlsx |
| Thermo Fisher NanoDrop Eight | `THERMO_FISHER_NANODROP_EIGHT` | .tsv, .txt |
| Thermo Fisher NanoDrop 8000 | `THERMO_FISHER_NANODROP_8000` | .csv |
| Unchained Labs Lunatic | `UNCHAINED_LABS_LUNATIC` | .csv, .xlsx |
| Thermo Fisher Genesys 30 | `THERMO_FISHER_GENESYS30` | .csv |

## Plate Readers (Multi-mode, Absorbance, Fluorescence)

| Instrument | Vendor Enum | File Types |
|------------|-------------|------------|
| Molecular Devices SoftMax Pro | `MOLDEV_SOFTMAX_PRO` | .txt |
| PerkinElmer EnVision | `PERKIN_ELMER_ENVISION` | .csv |
| Agilent Gen5 (BioTek) | `AGILENT_GEN5` | .xlsx |
| Agilent Gen5 Image | `AGILENT_GEN5_IMAGE` | .xlsx |
| BMG MARS (CLARIOstar) | `BMG_MARS` | .csv, .txt |
| BMG LabTech Smart Control | `BMG_LABTECH_SMART_CONTROL` | .csv |
| Thermo SkanIt | `THERMO_SKANIT` | .xlsx |
| Revvity Kaleido | `REVVITY_KALEIDO` | .csv |
| Tecan Magellan | `TECAN_MAGELLAN` | .xlsx |

## ELISA / Immunoassay

| Instrument | Vendor Enum | File Types |
|------------|-------------|------------|
| Molecular Devices SoftMax Pro | `MOLDEV_SOFTMAX_PRO` | .txt |
| MSD Discovery Workbench | `MSD_WORKBENCH` | .txt |
| MSD Methodical Mind | `METHODICAL_MIND` | .xlsx |
| BMG MARS | `BMG_MARS` | .csv, .txt |

## qPCR / PCR

| Instrument | Vendor Enum | File Types |
|------------|-------------|------------|
| Applied Biosystems QuantStudio | `APPBIO_QUANTSTUDIO` | .xlsx |
| Applied Biosystems QuantStudio Design & Analysis | `APPBIO_QUANTSTUDIO_DESIGNANALYSIS` | .xlsx, .csv |
| Bio-Rad CFX Maestro | `BIORAD_CFX_MAESTRO` | .csv, .xlsx |
| Roche LightCycler | `ROCHE_LIGHTCYCLER` | .txt |

## Chromatography (HPLC, LC)

| Instrument | Vendor Enum | File Types |
|------------|-------------|------------|
| Waters Empower | `WATERS_EMPOWER` | .xml |
| Thermo Fisher Chromeleon | `THERMO_FISHER_CHROMELEON` | .xml |
| Agilent ChemStation | `AGILENT_CHEMSTATION` | .csv |

## Electrophoresis

| Instrument | Vendor Enum | File Types |
|------------|-------------|------------|
| Agilent TapeStation | `AGILENT_TAPESTATION` | .csv |
| PerkinElmer LabChip | `PERKIN_ELMER_LABCHIP` | .csv |

## Flow Cytometry

| Instrument | Vendor Enum | File Types |
|------------|-------------|------------|
| BD Biosciences FACSDiva | `BD_BIOSCIENCES_FACSDIVA` | .xml |
| FlowJo | `FLOWJO` | .wsp |

## Solution Analysis

| Instrument | Vendor Enum | File Types |
|------------|-------------|------------|
| Roche Cedex BioHT | `ROCHE_CEDEX_BIOHT` | .xlsx |
| Beckman Coulter Biomek | `BECKMAN_COULTER_BIOMEK` | .csv |

## Auto-Detection Patterns

The skill attempts to identify instrument type from file contents using these patterns:

### Vi-CELL BLU
- Column headers: "Sample ID", "Viable cells (x10^6 cells/mL)", "Viability (%)"
- File structure: CSV with specific column order

### Vi-CELL XR
- Column headers: "Sample", "Total cells/ml", "Viable cells/ml"
- Multiple export formats supported

### NanoDrop
- Column headers: "Sample Name", "Nucleic Acid Conc.", "A260", "A280"
- 260/280 and 260/230 ratio columns

### Plate Readers (General)
- Well identifiers (A1-H12 pattern)
- "Plate", "Well", "Sample" columns
- Block-based structure with metadata headers

### ELISA
- Standard curve data with concentrations
- OD/absorbance readings
- Sample/blank/standard classification

## Using Vendor Enums

```python
from allotropy.parser_factory import Vendor
from allotropy.to_allotrope import allotrope_from_file

# List all supported vendors
for v in Vendor:
    print(f"{v.name}: {v.value}")

# Convert file
asm = allotrope_from_file("data.csv", Vendor.BECKMAN_VI_CELL_BLU)
```

## Checking Supported Status

```python
from allotropy.parser_factory import get_parser

# Check if a vendor/file combo is supported
try:
    parser = get_parser(Vendor.BECKMAN_VI_CELL_BLU)
    print("Supported!")
except Exception as e:
    print(f"Not supported: {e}")
```
