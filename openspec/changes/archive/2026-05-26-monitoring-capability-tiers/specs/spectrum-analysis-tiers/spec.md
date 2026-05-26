## ADDED Requirements

### Requirement: Basic spectrum — FFT display
At Basic tier, the system SHALL compute the FFT amplitude spectrum from raw waveform data and render a frequency-domain bar/line chart.

#### Scenario: FFT spectrum rendered
- **WHEN** spectrum analysis runs with valid waveform data
- **THEN** the system SHALL render an ECharts with frequency (Hz) on x-axis and amplitude on y-axis

### Requirement: Pro spectrum — envelope + cepstrum + bearing fault matching
At Pro tier, the system SHALL additionally compute Hilbert envelope spectrum, cepstrum for harmonic family detection, match spectral peaks against known bearing fault frequencies (BPFO/BPFI/BSF/FTF), and identify sideband patterns.

#### Scenario: Envelope spectrum reveals bearing fault
- **WHEN** the raw waveform contains amplitude modulation at a bearing fault frequency
- **THEN** the envelope spectrum SHALL show a clear peak at the BPFO frequency, and findings SHALL include the bearing fault type

#### Scenario: Cepstrum detects harmonic family
- **WHEN** the spectrum contains evenly spaced peaks every 25 Hz
- **THEN** the cepstrum SHALL show a peak at the corresponding quefrency

#### Scenario: Bearing fault frequency matched
- **WHEN** an envelope peak at 78.3 Hz matches BPFO of SKF 6306 at 1800 RPM (expected 78.5 Hz, within ±2%)
- **THEN** findings SHALL include `bearing_fault_match: {bearing_model, fault_type, confidence: "high"}`

### Requirement: Ultra spectrum — CNN classification + automated fault verdict + evolution tracking
At Ultra tier, the system SHALL additionally classify spectra via ONNX CNN, synthesize CNN + rule-based results into a final fault verdict, and track fault indicator evolution across multiple timestamps.

#### Scenario: CNN classifies inner race fault
- **WHEN** the spectrum is passed through the CNN classifier
- **THEN** output SHALL include `cnn_classification: {top_predictions: [{fault_type, probability}]}`

#### Scenario: CNN and rules agree — high confidence verdict
- **WHEN** CNN top prediction matches rule-based bearing fault match with prob ≥0.8
- **THEN** `fault_verdict.confidence` SHALL be `"high"` with `agreement: "cnn_and_rules_agree"`

#### Scenario: Fault evolution worsening
- **WHEN** spectrum snapshots at T1, T2, T3 show BPFO amplitude increasing [0.12, 0.28, 0.51]
- **THEN** output SHALL include `fault_evolution: {trend: "worsening", estimated_time_to_alarm: Y days}`
