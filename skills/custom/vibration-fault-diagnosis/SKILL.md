---
name: vibration-fault-diagnosis
description: Industrial rotating machinery vibration fault diagnosis using user-provided rule sets and plant data tools. Use when the user wants a one-off or repeatable diagnosis for汽轮机、离心/轴流压缩机、多轴齿轮式压缩机、螺杆式压缩机、齿轮箱, including trend review, waveform/spectrum analysis, shaft orbit checks, operating condition identification, rule matching, and structured fault reports.
metadata:
  emoji: "🩺"
---

# Vibration Fault Diagnosis

Use this skill to diagnose rotating machinery faults with the user's rule base and data tools.

## Workflow

1. Confirm the target machine, time window, and whether the user wants a one-off diagnosis or a quick screening.
2. Determine equipment type from machine/component naming and available measurements.
3. Use the plant inspection toolchain first to locate the machine, inspect component hierarchy, and identify key points:
   - speed / rpm
   - shaft vibration X/Y at both bearings
   - axial displacement if available
   - bearing / thrust bearing temperatures if available
   - process variables relevant to surge / rotating stall if available
4. Judge operating condition before fault typing:
   - startup / warm-up
   - shutdown / coastdown
   - steady state
   - unstable process disturbance
5. Build an evidence chain in this order unless data is missing:
   - overall trend and alarm behavior
   - speed correlation
   - waveform shape
   - spectrum dominant components
   - shaft orbit / centerline behavior
   - process correlation (flow / pressure / anti-surge valve / temperatures)
6. Match observed behavior against the bundled rule reference.
7. Output a structured conclusion with:
   - machine info
   - operating condition
   - abnormal points
   - evidence
   - primary diagnosis
   - alternative diagnoses / exclusions
   - confidence
   - operation advice
   - maintenance advice

## Required diagnostic style

- Prefer evidence-based language.
- If evidence is incomplete, give a tendency diagnosis rather than pretending certainty.
- Distinguish clearly between:
  - confirmed by current evidence
  - likely / suspected
  - not supported by current data
- Do not force a diagnosis when only one feature matches weakly.

## Rule matching guidance

Read `references/diagnosis-rules.md` and match by:
- equipment type
- fault type / subtype
- required chart types
- time window context
- key features
- typical features
- recommended actions

When several fault types seem plausible, rank them by how well they explain the full set of observations:
1. operating condition fit
2. dominant frequency features
3. waveform morphology
4. orbit behavior
5. multi-point consistency
6. process-variable correlation

## Practical heuristics

Apply these heuristics while using the rule base:

- If vibration rises mainly during startup/shutdown while passing a speed band, is 1X-dominant, waveform is sinusoidal, and response falls after passing the band, prefer **large critical response**.
- If vibration is 1X-dominant and stays relatively high/stable over long periods or tracks speed synchronously across operation, prefer **unbalance**.
- If coupling-side channels on coupled machines are both high and 1X-dominant, prefer **misalignment**.
- If waveform shows clipping, burrs, or added fractional / harmonic content with unstable orbit behavior, consider **rub / seal rub**.
- If low-frequency components become prominent, waveform/orbit loses repeatability, and process variables such as inlet flow or anti-surge action change together, consider **rotating stall / surge**.
- If low-speed or turning-gear conditions already show high values with characteristic once-per-cycle downward spikes and X/Y phase separation, consider **runout / measurement effect**.
- If axial displacement is abnormally high after maintenance while thrust temperatures remain reasonable and stable, consider **axial displacement zero calibration issue**.
- If bearing or thrust temperatures are high from startup and remain high but flat, consider **assembly / design related temperature abnormality** rather than progressive deterioration.
- For thermal bend vs critical response, pay attention to whether coastdown retraces startup behavior. If it does not retrace and remains elevated until near stop, thermal bend becomes more plausible.

## Output template

Use a concise report structure:

### 1. Machine and task
- machine name
- equipment type
- diagnosis window
- current operation phase

### 2. Key abnormal findings
- abnormal points
- maximum values and timestamps
- alarm status

### 3. Evidence chain
- trend evidence
- spectrum evidence
- waveform evidence
- orbit / centerline evidence
- process / temperature / axial evidence

### 4. Diagnosis
- primary fault type / subtype
- confidence: high / medium / low
- why it matches

### 5. Differential diagnosis
- alternative candidates
- why they are weaker
- what data is still missing

### 6. Recommendations
- operation recommendations
- maintenance recommendations

## Tooling notes

If the request is specifically about browsing machine trees, trends, waveforms, spectra, or shaft orbit in the plant system, first use the plant inspection workflow already available in the workspace. This skill adds the diagnosis logic and reporting standard on top of that data access.

## References

- Main rule base: `references/diagnosis-rules.md`
