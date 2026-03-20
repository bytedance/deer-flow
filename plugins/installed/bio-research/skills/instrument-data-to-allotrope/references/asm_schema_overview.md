# ASM Schema Overview

The Allotrope Simple Model (ASM) is a JSON-based standard for representing laboratory instrument data with semantic consistency.

## Core Concepts

### Structure
ASM uses a hierarchical document structure:
- **Manifest** - Links to ontologies and schemas
- **Data** - The actual measurement data organized by technique

### Key Components

```json
{
  "$asm.manifest": {
    "vocabulary": ["http://purl.allotrope.org/voc/afo/REC/2023/09/"],
    "contexts": ["http://purl.allotrope.org/json-ld/afo-context-REC-2023-09.jsonld"]
  },
  "<technique>-aggregate-document": {
    "device-system-document": { ... },
    "<technique>-document": [
      {
        "measurement-aggregate-document": {
          "measurement-document": [ ... ]
        }
      }
    ]
  }
}
```

## Required Metadata Documents

### data system document
Every ASM output MUST include this document with:
- `ASM file identifier`: Output filename
- `data system instance identifier`: System ID or "N/A"
- `file name`: Source input filename
- `UNC path`: Path to source file
- `ASM converter name`: Parser identifier (e.g., "allotropy_beckman_coulter_biomek")
- `ASM converter version`: Version string
- `software name`: Instrument software that generated the source file

### device system document
Every ASM output MUST include this document with:
- `equipment serial number`: Main instrument serial
- `product manufacturer`: Vendor name
- `device document`: Array of sub-components (probes, pods, etc.)
  - `device type`: Standardized type (e.g., "liquid handler probe head")
  - `device identifier`: Logical name (e.g., "Pod1", not serial number)
  - `equipment serial number`: Component serial
  - `product manufacturer`: Component vendor

## Available ASM Techniques

The official ASM repository includes **65 technique schemas**:

```
absorbance, automated-reactors, balance, bga, binding-affinity, bulk-density,
cell-counting, cell-culture-analyzer, chromatography, code-reader, conductance,
conductivity, disintegration, dsc, dvs, electronic-lab-notebook,
electronic-spectrometry, electrophoresis, flow-cytometry, fluorescence,
foam-height, foam-qualification, fplc, ftir, gas-chromatography, gc-ms, gloss,
hot-tack, impedance, lc-ms, light-obscuration, liquid-chromatography,
loss-on-drying, luminescence, mass-spectrometry, metabolite-analyzer,
multi-analyte-profiling, nephelometry, nmr, optical-imaging, optical-microscopy,
osmolality, oven-kf, pcr, ph, plate-reader, pressure-monitoring, psd, pumping,
raman, rheometry, sem, solution-analyzer, specific-rotation, spectrophotometry,
stirring, surface-area-analysis, tablet-hardness, temperature-monitoring,
tensile-test, thermogravimetric-analysis, titration, ultraviolet-absorbance,
x-ray-powder-diffraction
```

See: https://gitlab.com/allotrope-public/asm/-/tree/main/json-schemas/adm

## Common ASM Schemas by Technique

Below are details for frequently-used techniques:

### Cell Counting
Schema: `cell-counting/REC/2024/09/cell-counting.schema.json`

Key fields:
- `viable-cell-density` (cells/mL)
- `viability` (percentage)
- `total-cell-count`
- `dead-cell-count`
- `cell-diameter-distribution-datum`

### Spectrophotometry (UV-Vis)
Schema: `spectrophotometry/REC/2024/06/spectrophotometry.schema.json`

Key fields:
- `absorbance` (dimensionless)
- `wavelength` (nm)
- `transmittance` (percentage)
- `pathlength` (cm)
- `concentration` with units

### Plate Reader
Schema: `plate-reader/REC/2024/06/plate-reader.schema.json`

Key fields:
- `absorbance`
- `fluorescence`
- `luminescence`
- `well-location` (A1-H12)
- `plate-identifier`

### qPCR
Schema: `pcr/REC/2024/06/pcr.schema.json`

Key fields:
- `cycle-threshold-result`
- `amplification-efficiency`
- `melt-curve-datum`
- `target-DNA-description`

### Chromatography
Schema: `liquid-chromatography/REC/2023/09/liquid-chromatography.schema.json`

Key fields:
- `retention-time` (minutes)
- `peak-area`
- `peak-height`
- `peak-width`
- `chromatogram-data-cube`

## Data Patterns

### Value Datum
Simple value with unit:
```json
{
  "value": 1.5,
  "unit": "mL"
}
```

### Aggregate Datum
Collection of related values:
```json
{
  "measurement-aggregate-document": {
    "measurement-document": [
      { "viable-cell-density": {"value": 2.5e6, "unit": "(cell/mL)"} },
      { "viability": {"value": 95.2, "unit": "%"} }
    ]
  }
}
```

### Data Cube
Multi-dimensional array data:
```json
{
  "cube-structure": {
    "dimensions": [{"@componentDatatype": "double", "concept": "elapsed time"}],
    "measures": [{"@componentDatatype": "double", "concept": "absorbance"}]
  },
  "data": {
    "dimensions": [[0, 1, 2, 3, 4]],
    "measures": [[0.1, 0.2, 0.3, 0.4, 0.5]]
  }
}
```

## Validation

Validate ASM output against official schemas:

```python
import json
import jsonschema
from urllib.request import urlopen

# Load ASM output
with open("output.json") as f:
    asm = json.load(f)

# Get schema URL from manifest
schema_url = asm.get("$asm.manifest", {}).get("$ref")

# Validate (simplified - real validation more complex)
# Note: Full validation requires resolving $ref references
```

## Schema Repository

Official schemas: https://gitlab.com/allotrope-public/asm/-/tree/main/json-schemas/adm

Schema structure:
```
json-schemas/adm/
├── cell-counting/
│   └── REC/2024/09/
│       └── cell-counting.schema.json
├── spectrophotometry/
│   └── REC/2024/06/
│       └── spectrophotometry.schema.json
├── plate-reader/
│   └── REC/2024/06/
│       └── plate-reader.schema.json
└── ...
```

## Common Issues

### Missing Fields
Not all instrument exports contain all ASM fields. Report completeness:
```python
def report_completeness(asm, expected_fields):
    found = set(extract_all_fields(asm))
    missing = expected_fields - found
    return len(found) / len(expected_fields) * 100
```

### Unit Variations
Instruments may use different unit formats. The allotropy library normalizes these:
- "cells/mL" → "(cell/mL)"
- "%" → "%"
- "nm" → "nm"

### Date Formats
ASM uses ISO 8601: `2024-01-15T10:30:00Z`
