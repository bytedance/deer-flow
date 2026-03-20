# Flattening ASM to 2D CSV

Converting hierarchical ASM JSON to flat 2D tables for LIMS import, spreadsheet analysis, or data engineering pipelines.

## Why Flatten?

ASM is semantically rich but hierarchical. Many systems need flat tables:
- LIMS import (Benchling, STARLIMS, LabWare)
- Excel/CSV analysis
- Database loading
- Quick visual inspection

## Flattening Strategy

### Core Principle
Each **measurement** becomes one **row**. Metadata is repeated per row.

### What's Excluded
The flattening intentionally **omits top-level ASM metadata** such as:
- `$asm.manifest` (model version, schema URIs)
- Root-level fields outside the technique aggregate document

This keeps the output focused on experimental data. If you need schema version tracking for compliance or audit purposes, consider storing the original ASM JSON alongside the flattened CSV, or modify the flattening script to include these fields.

### Hierarchy to Columns
```
ASM Hierarchy                    → Flat Column
─────────────────────────────────────────────────
device-system-document.
  device-identifier              → instrument_serial_number
  model-number                   → instrument_model
  
measurement-aggregate-document.
  analyst                        → analyst
  measurement-time               → measurement_datetime
  
measurement-document[].
  sample-identifier              → sample_id
  viable-cell-density.value      → viable_cell_density
  viable-cell-density.unit       → viable_cell_density_unit
  viability.value                → viability_percent
```

## Column Naming Convention

Use snake_case with descriptive suffixes:

| ASM Field | Flat Column |
|-----------|-------------|
| `viable-cell-density` | `viable_cell_density` |
| `.value` | `_value` (or omit if obvious) |
| `.unit` | `_unit` |
| `measurement-time` | `measurement_datetime` |

## Example: Cell Counting

### ASM Input (simplified)
```json
{
  "cell-counting-aggregate-document": {
    "device-system-document": {
      "device-identifier": "VCB001",
      "model-number": "Vi-CELL BLU"
    },
    "cell-counting-document": [{
      "measurement-aggregate-document": {
        "analyst": "jsmith",
        "measurement-time": "2024-01-15T10:30:00Z",
        "measurement-document": [
          {
            "sample-identifier": "Sample_A",
            "viable-cell-density": {"value": 2500000, "unit": "(cell/mL)"},
            "viability": {"value": 95.2, "unit": "%"}
          },
          {
            "sample-identifier": "Sample_B",
            "viable-cell-density": {"value": 1800000, "unit": "(cell/mL)"},
            "viability": {"value": 88.7, "unit": "%"}
          }
        ]
      }
    }]
  }
}
```

### Flattened Output
```csv
sample_id,viable_cell_density,viable_cell_density_unit,viability_percent,analyst,measurement_datetime,instrument_serial_number,instrument_model
Sample_A,2500000,(cell/mL),95.2,jsmith,2024-01-15T10:30:00Z,VCB001,Vi-CELL BLU
Sample_B,1800000,(cell/mL),88.7,jsmith,2024-01-15T10:30:00Z,VCB001,Vi-CELL BLU
```

## Example: Plate Reader

### ASM Input (simplified)
```json
{
  "plate-reader-aggregate-document": {
    "plate-reader-document": [{
      "measurement-aggregate-document": {
        "plate-identifier": "ELISA_001",
        "measurement-document": [
          {"well-location": "A1", "absorbance": {"value": 0.125, "unit": "mAU"}},
          {"well-location": "A2", "absorbance": {"value": 0.892, "unit": "mAU"}},
          {"well-location": "A3", "absorbance": {"value": 1.456, "unit": "mAU"}}
        ]
      }
    }]
  }
}
```

### Flattened Output
```csv
plate_id,well_position,absorbance,absorbance_unit
ELISA_001,A1,0.125,mAU
ELISA_001,A2,0.892,mAU
ELISA_001,A3,1.456,mAU
```

## Handling Data Cubes

Data cubes (time series, spectra) need special handling:

### Option 1: Expand to rows
Each point becomes a row:
```csv
sample_id,time_seconds,absorbance
Sample_A,0,0.100
Sample_A,60,0.125
Sample_A,120,0.150
```

### Option 2: Wide format
Measurements as columns:
```csv
sample_id,abs_0s,abs_60s,abs_120s
Sample_A,0.100,0.125,0.150
```

### Option 3: JSON array in cell
Keep as array (some systems support this):
```csv
sample_id,absorbance_timeseries
Sample_A,"[0.100,0.125,0.150]"
```

## Standard Column Sets by Technique

### Cell Counting
```
sample_id, viable_cell_density, viable_cell_density_unit, total_cell_count,
viability_percent, average_cell_diameter, average_cell_diameter_unit,
analyst, measurement_datetime, instrument_serial_number
```

### Spectrophotometry
```
sample_id, wavelength_nm, absorbance, pathlength_cm, concentration,
concentration_unit, a260_a280_ratio, a260_a230_ratio,
analyst, measurement_datetime, instrument_serial_number
```

### Plate Reader / ELISA
```
plate_id, well_position, sample_type, sample_id, absorbance, absorbance_unit,
concentration, concentration_unit, dilution_factor, cv_percent,
analyst, measurement_datetime, instrument_serial_number
```

### qPCR
```
sample_id, target_name, well_position, ct_value, ct_mean, ct_sd,
quantity, quantity_unit, amplification_efficiency,
analyst, measurement_datetime, instrument_serial_number
```

## Python Implementation

```python
import json
import pandas as pd

def flatten_asm(asm_dict, technique="cell-counting"):
    """
    Flatten ASM JSON to pandas DataFrame.
    
    Args:
        asm_dict: Parsed ASM JSON
        technique: ASM technique type
        
    Returns:
        pandas DataFrame with one row per measurement
    """
    rows = []
    
    # Get aggregate document
    agg_key = f"{technique}-aggregate-document"
    agg_doc = asm_dict.get(agg_key, {})
    
    # Extract device info
    device = agg_doc.get("device-system-document", {})
    device_info = {
        "instrument_serial_number": device.get("device-identifier"),
        "instrument_model": device.get("model-number")
    }
    
    # Get technique documents
    doc_key = f"{technique}-document"
    for doc in agg_doc.get(doc_key, []):
        meas_agg = doc.get("measurement-aggregate-document", {})
        
        # Extract common metadata
        common = {
            "analyst": meas_agg.get("analyst"),
            "measurement_datetime": meas_agg.get("measurement-time"),
            **device_info
        }
        
        # Extract each measurement
        for meas in meas_agg.get("measurement-document", []):
            row = {**common}
            
            # Flatten measurement fields
            for key, value in meas.items():
                if isinstance(value, dict) and "value" in value:
                    # Value datum pattern
                    col = key.replace("-", "_")
                    row[col] = value["value"]
                    if "unit" in value:
                        row[f"{col}_unit"] = value["unit"]
                else:
                    row[key.replace("-", "_")] = value
            
            rows.append(row)
    
    return pd.DataFrame(rows)

# Usage
with open("asm_output.json") as f:
    asm = json.load(f)

df = flatten_asm(asm, "cell-counting")
df.to_csv("flattened_output.csv", index=False)
```

## LIMS Import Considerations

When importing flattened data into a LIMS:
- Match column names to your LIMS schema field names
- Use ISO 8601 date format for timestamps
- Ensure sample IDs match existing LIMS sample identifiers
- Check if your LIMS expects units in separate columns or embedded in values
