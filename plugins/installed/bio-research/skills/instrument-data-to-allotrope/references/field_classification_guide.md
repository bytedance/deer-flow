# Field Classification Guide

This guide helps classify instrument data fields into the correct ASM document locations. Use this when mapping raw instrument output to Allotrope Simple Model structure.

## ASM Document Hierarchy

```
<technique>-aggregate-document
├── device-system-document          # Instrument hardware info
├── data-system-document            # Software/conversion info
├── <technique>-document[]          # Per-run/sequence data
│   ├── analyst                     # Who performed the analysis
│   ├── measurement-aggregate-document
│   │   ├── measurement-time
│   │   ├── measurement-document[]  # Individual measurements
│   │   │   ├── sample-document
│   │   │   ├── device-control-aggregate-document
│   │   │   └── [measurement fields]
│   │   └── [aggregate-level metadata]
│   ├── processed-data-aggregate-document
│   │   └── processed-data-document[]
│   │       ├── data-processing-document
│   │       └── [processed results]
│   └── calculated-data-aggregate-document
│       └── calculated-data-document[]
```

## Field Classification Categories

### 1. Device/Instrument Information → `device-system-document`

Hardware and firmware details about the physical instrument.

| Field Type | ASM Field | Examples |
|------------|-----------|----------|
| Instrument name | `model-number` | "Vi-CELL BLU", "NanoDrop One" |
| Serial number | `equipment-serial-number` | "VCB-12345", "SN001234" |
| Manufacturer | `product-manufacturer` | "Beckman Coulter", "Thermo Fisher" |
| Firmware version | `firmware-version` | "v2.1.3" |
| Device ID | `device-identifier` | "Instrument_01" |
| Brand | `brand-name` | "Beckman Coulter" |

**Rule:** If the value describes the physical instrument and doesn't change between runs, it goes in `device-system-document`.

---

### 2. Software/Data System Information → `data-system-document`

Information about software used for acquisition, analysis, or conversion.

| Field Type | ASM Field | Examples |
|------------|-----------|----------|
| Software name | `software-name` | "Chromeleon", "Gen5" |
| Software version | `software-version` | "7.3.2" |
| File name | `file-name` | "experiment_001.xlsx" |
| File path | `file-identifier` | "/data/runs/2024-01-15/" |
| Database ID | `ASM-converter-name` | "allotropy v0.1.55" |

**Rule:** If the value describes software, file metadata, or data provenance, it goes in `data-system-document`.

---

### 3. Sample Information → `sample-document`

Metadata about the biological/chemical sample being analyzed.

| Field Type | ASM Field | Examples |
|------------|-----------|----------|
| Sample ID | `sample-identifier` | "Sample_A", "LIMS-001234" |
| Sample name | `written-name` | "CHO Cell Culture Day 5" |
| Sample type/role | `sample-role-type` | "unknown sample role", "control sample role" |
| Batch ID | `batch-identifier` | "Batch-2024-001" |
| Description | `description` | "Protein expression sample" |
| Well position | `location-identifier` | "A1", "B3" |

**Rule:** If the value identifies or describes what was measured (not how), it goes in `sample-document`.

---

### 4. Device Control Settings → `device-control-aggregate-document`

Instrument settings and parameters used during measurement.

| Field Type | ASM Field | Examples |
|------------|-----------|----------|
| Injection volume | `sample-volume-setting` | 10 µL |
| Wavelength | `detector-wavelength-setting` | 254 nm |
| Temperature | `compartment-temperature` | 37°C |
| Flow rate | `flow-rate` | 1.0 mL/min |
| Exposure time | `exposure-duration-setting` | 500 ms |
| Detector gain | `detector-gain-setting` | 1.5 |
| Illumination | `illumination-setting` | 80% |

**Rule:** If the value is a configurable instrument parameter that affects measurement, it goes in `device-control-aggregate-document`.

---

### 5. Environmental Conditions → `device-control-document` or technique-specific

Ambient or controlled environmental parameters during measurement.

| Field Type | ASM Field | Examples |
|------------|-----------|----------|
| Ambient temperature | `ambient-temperature` | 22.5°C |
| Humidity | `ambient-relative-humidity` | 45% |
| Column temperature | `compartment-temperature` | 30°C |
| Sample temperature | `sample-temperature` | 4°C |
| Electrophoresis temp | (technique-specific) | 26.4°C |

**Rule:** Environmental conditions that affect measurement quality go with device control or in technique-specific locations.

---

### 6. Raw Measurement Data → `measurement-document`

Direct instrument readings - the "ground truth" data.

| Field Type | ASM Field | Examples |
|------------|-----------|----------|
| Absorbance | `absorbance` | 0.523 AU |
| Fluorescence | `fluorescence` | 12500 RFU |
| Cell count | `total-cell-count` | 2.5e6 cells |
| Peak area | `peak-area` | 1234.5 mAU·min |
| Retention time | `retention-time` | 5.67 min |
| Ct value | `cycle-threshold-result` | 24.5 |
| Concentration (measured) | `mass-concentration` | 1.5 mg/mL |

**Rule:** If the value is a direct instrument reading that wasn't computed from other values in this analysis, it goes in `measurement-document`.

---

### 7. Calculated/Derived Data → `calculated-data-aggregate-document`

Values computed from raw measurements.

| Field Type | ASM Field | Examples |
|------------|-----------|----------|
| Viability % | `calculated-result` | 95.2% |
| Concentration (from std curve) | `calculated-result` | 125 ng/µL |
| Ratio (260/280) | `calculated-result` | 1.89 |
| Relative quantity | `calculated-result` | 2.5x |
| % Recovery | `calculated-result` | 98.7% |
| CV% | `calculated-result` | 2.3% |

**Calculated data document structure:**
```json
{
  "calculated-data-name": "viability",
  "calculated-result": {"value": 95.2, "unit": "%"},
  "calculation-description": "viable cells / total cells * 100"
}
```

**Rule:** If the value was computed from other measurements in this analysis, it goes in `calculated-data-aggregate-document`. Include `calculation-description` when possible.

---

### 8. Processed/Analyzed Data → `processed-data-aggregate-document`

Results from data processing algorithms (peak integration, cell classification, etc.).

| Field Type | ASM Field | Examples |
|------------|-----------|----------|
| Peak list | `peak-list` | Integrated peak results |
| Cell size distribution | `cell-diameter-distribution` | Histogram data |
| Baseline-corrected data | (in processed-data-document) | Corrected spectra |
| Fitted curve | (in processed-data-document) | Standard curve fit |

**Associated `data-processing-document`:**
```json
{
  "cell-type-processing-method": "trypan blue exclusion",
  "cell-density-dilution-factor": {"value": 2, "unit": "(unitless)"},
  "minimum-cell-diameter-setting": {"value": 5, "unit": "µm"},
  "maximum-cell-diameter-setting": {"value": 50, "unit": "µm"}
}
```

**Rule:** If the value results from an algorithm or processing method applied to raw data, it goes in `processed-data-aggregate-document` with its processing parameters in `data-processing-document`.

---

### 9. Timing/Timestamps → Various locations

| Timestamp Type | Location | ASM Field |
|----------------|----------|-----------|
| Measurement time | `measurement-document` | `measurement-time` |
| Run start time | `analysis-sequence-document` | `analysis-sequence-start-time` |
| Run end time | `analysis-sequence-document` | `analysis-sequence-end-time` |
| Data export time | `data-system-document` | (custom) |

**Rule:** Use ISO 8601 format: `2024-01-15T10:30:00Z`

---

### 10. Analyst/Operator Information → `<technique>-document`

| Field Type | ASM Field | Examples |
|------------|-----------|----------|
| Operator name | `analyst` | "jsmith" |
| Reviewer | (custom or extension) | "Pending" |

**Rule:** Analyst goes at the technique-document level, not in individual measurements.

---

## Decision Tree

```
Is this field about...

THE INSTRUMENT ITSELF?
├── Hardware specs → device-system-document
└── Software/files → data-system-document

THE SAMPLE?
└── Sample ID, name, type, batch → sample-document

INSTRUMENT SETTINGS?
└── Configurable parameters → device-control-aggregate-document

ENVIRONMENTAL CONDITIONS?
└── Temp, humidity, etc. → device-control-document

A DIRECT READING?
└── Raw instrument output → measurement-document

A COMPUTED VALUE?
├── From other measurements → calculated-data-document
└── From processing algorithm → processed-data-document

TIMING?
├── When measured → measurement-document.measurement-time
└── When run started/ended → analysis-sequence-document

WHO DID IT?
└── Operator/analyst → <technique>-document.analyst
```

## Common Instrument-to-ASM Mappings

> **Note:** These mappings are derived from the [Benchling allotropy library](https://github.com/Benchling-Open-Source/allotropy/tree/main/src/allotropy/parsers). For authoritative mappings, consult the parser source code for your specific instrument.

### Cell Counter (Vi-CELL BLU)
*Source: `allotropy/parsers/beckman_vi_cell_blu/vi_cell_blu_structure.py`*

| Instrument Field | ASM Field |
|-----------------|-----------|
| Sample ID | `sample_identifier` |
| Analysis date/time | `measurement_time` |
| Analysis by | `analyst` |
| Viability (%) | `viability` |
| Viable (x10^6) cells/mL | `viable_cell_density` |
| Total (x10^6) cells/mL | `total_cell_density` |
| Cell count | `total_cell_count` |
| Viable cells | `viable_cell_count` |
| Average diameter (μm) | `average_total_cell_diameter` |
| Average viable diameter (μm) | `average_live_cell_diameter` |
| Average circularity | `average_total_cell_circularity` |
| Cell type | `cell_type_processing_method` (data-processing) |
| Dilution | `cell_density_dilution_factor` (data-processing) |
| Min/Max Diameter | `minimum/maximum_cell_diameter_setting` (data-processing) |

### Spectrophotometer (NanoDrop)
| Instrument Field | ASM Field |
|-----------------|-----------|
| Sample Name | `sample_identifier` |
| A260, A280 | `absorbance` (with wavelength) |
| Concentration | `mass_concentration` |
| 260/280 ratio | `a260_a280_ratio` |
| Pathlength | `pathlength` |

### Plate Reader
| Instrument Field | ASM Field |
|-----------------|-----------|
| Well | `location_identifier` |
| Sample Type | `sample_role_type` |
| Absorbance/OD | `absorbance` |
| Fluorescence | `fluorescence` |
| Plate ID | `container_identifier` |

### Chromatography (HPLC)
| Instrument Field | ASM Field |
|-----------------|-----------|
| Sample ID | `sample_identifier` |
| Injection Volume | `injection_volume` |
| Retention Time | `retention_time` |
| Peak Area | `peak_area` |
| Peak Height | `peak_height` |
| Column Temp | `column_oven_temperature` |
| Flow Rate | `flow_rate` |

## Unit Handling

Only use units explicitly present in source data. If a value has no unit specified:
- Use `(unitless)` as the unit value
- Do NOT infer units based on domain knowledge

## Calculated Data Traceability

When creating calculated values, always link them to their source data using `data-source-aggregate-document`:

```json
{
    "calculated-data-name": "DIN",
    "calculated-result": {"value": 5.8, "unit": "(unitless)"},
    "calculated-data-identifier": "TEST_ID_147",
    "data-source-aggregate-document": {
        "data-source-document": [{
            "data-source-identifier": "TEST_ID_145",
            "data-source-feature": "sample"
        }]
    }
}
```

This declares: "DIN 5.8 was calculated from the sample at `TEST_ID_145`."

**Why this matters:**
- **Audits**: Prove a value came from specific raw data
- **Debugging**: Trace unexpected results back to their source
- **Reprocessing**: Know which inputs to re-analyze if algorithms change

**Assign unique IDs to:**
- Measurements, peaks, regions, and calculated values
- Use a consistent naming pattern (e.g., `INSTRUMENT_TYPE_TEST_ID_N`)

This enables bidirectional traversal: trace from calculated → raw, or raw → all derived values.

---

## Nested Document Structure (Critical)

A common mistake is "flattening" fields directly onto measurement documents when they should be wrapped in nested structures. This breaks schema compliance and loses semantic context.

### Why Nesting Matters

ASM uses nested documents for semantic grouping:

| Document | Purpose | Contains |
|----------|---------|----------|
| `sample document` | What was measured | Sample ID, locations, plate identifiers |
| `device control aggregate document` | How instrument operated | Settings, parameters, techniques |
| `custom information document` | Vendor-specific fields | Non-standard fields that don't map to ASM |

### Sample Document Fields

These fields MUST be inside `sample document`, not flattened on measurement:

```json
// ❌ WRONG - Fields flattened on measurement
{
  "measurement identifier": "TEST_001",
  "sample identifier": "Sample_A",
  "location identifier": "A1",
  "absorbance": {"value": 0.5, "unit": "(unitless)"}
}

// ✅ CORRECT - Fields nested in sample document
{
  "measurement identifier": "TEST_001",
  "sample document": {
    "sample identifier": "Sample_A",
    "location identifier": "A1",
    "well plate identifier": "96WP001"
  },
  "absorbance": {"value": 0.5, "unit": "(unitless)"}
}
```

**Fields belonging in sample document:**
- `sample identifier` - Sample ID/name
- `written name` - Descriptive sample name
- `batch identifier` - Batch/lot number
- `sample role type` - Standard, blank, control, unknown
- `location identifier` - Well position (A1, B3, etc.)
- `well plate identifier` - Plate barcode
- `description` - Sample description

### Device Control Document Fields

Instrument settings MUST be inside `device control aggregate document`:

```json
// ❌ WRONG - Device settings flattened
{
  "measurement identifier": "TEST_001",
  "device identifier": "Pod1",
  "technique": "Custom",
  "volume": {"value": 26, "unit": "μL"}
}

// ✅ CORRECT - Settings nested in device control
{
  "measurement identifier": "TEST_001",
  "device control aggregate document": {
    "device control document": [{
      "device type": "liquid handler",
      "device identifier": "Pod1"
    }]
  },
  "aspiration volume": {"value": 26, "unit": "μL"}
}
```

**Fields belonging in device control:**
- `device type` - Type of device
- `device identifier` - Device ID
- `detector wavelength setting` - Wavelength for detection
- `compartment temperature` - Temperature setting
- `sample volume setting` - Volume setting
- `flow rate` - Flow rate setting

### Custom Information Document

Vendor-specific fields that don't map to standard ASM terms go in `custom information document`:

```json
"device control document": [{
  "device type": "liquid handler",
  "custom information document": {
    "probe": "2",
    "pod": "Pod1",
    "source labware name": "Inducer",
    "destination labware name": "GRP1"
  }
}]
```

### Liquid Handler: Transfer Pairing

For liquid handlers, a measurement represents a complete transfer (aspirate + dispense), not separate operations:

```json
// ❌ WRONG - Separate records for aspirate and dispense
[
  {"measurement identifier": "OP_001", "transfer type": "Aspirate", "volume": {"value": 26, "unit": "μL"}},
  {"measurement identifier": "OP_002", "transfer type": "Dispense", "volume": {"value": 26, "unit": "μL"}}
]

// ✅ CORRECT - Single record with source and destination
{
  "measurement identifier": "TRANSFER_001",
  "sample document": {
    "source well location identifier": "1",
    "destination well location identifier": "2",
    "source well plate identifier": "96WP001",
    "destination well plate identifier": "96WP002"
  },
  "aspiration volume": {"value": 26, "unit": "μL"},
  "transfer volume": {"value": 26, "unit": "μL"}
}
```

**Pairing logic:**
1. Match aspirate and dispense operations by probe number
2. Create one measurement per matched pair
3. Use `source_*` fields for aspirate location
4. Use `destination_*` fields for dispense location
5. Include both `aspiration volume` and `transfer volume`

### Quick Reference: Nesting Decision

```
Is this field about...

THE SAMPLE BEING MEASURED?
├── Sample ID, name, batch → sample document
├── Well position → sample document.location identifier
├── Plate barcode → sample document.well plate identifier
└── Source/destination locations → sample document (with prefixes)

INSTRUMENT SETTINGS?
├── Standard settings → device control aggregate document
└── Vendor-specific → custom information document

A MEASUREMENT VALUE?
└── Direct on measurement document (e.g., absorbance, volume)

TRANSFER OPERATION TYPE?
└── DON'T use "transfer type" - pair into single measurement
    with source/destination fields instead
```

### Validation

Use `validate_asm.py` to check for nesting issues:
```bash
python scripts/validate_asm.py output.json --reference known_good.json
```

The validator checks for:
- Fields incorrectly flattened on measurements
- Missing `sample document` wrapper
- Missing `device control aggregate document` wrapper
- Missing `custom information document` for vendor fields
- Liquid handler: separate transfer types instead of paired records

## Sources

- [Allotrope Simple Model Introduction](https://www.allotrope.org/introduction-to-allotrope-simple-model)
- [Benchling allotropy library](https://github.com/Benchling-Open-Source/allotropy)
- [Allotrope Foundation ASM Overview](https://www.allotrope.org/asm)
