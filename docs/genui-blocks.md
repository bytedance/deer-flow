# GenUI Blocks — Schema Reference for Backend Skill Authors

> Audience: backend skill authors writing under `skills/custom/`. The frontend
> ships a small set of generic block primitives; your skill emits them in its
> stream and the workspace renders them automatically.
>
> All blocks share a top-level envelope:
>
> ```json
> { "type": "<block-name>", "version": "1.0", "props": { ... } }
> ```
>
> The `version` field follows semver-ish rules — major bumps require a
> frontend update; the major version supported by the current frontend is
> declared in `frontend/src/core/genui/registry.ts`.

This document only covers the **EHM industrial primitives** introduced
alongside the EHM AI Workspace rebrand. For the upstream blocks (`chart`,
`echart`, `table`, `card`, `form`, `confirm`, `code`, `timeline`, `layout`,
`markdown`, `image`) refer to the registry.

---

## `gauge`

Half-circle gauge for engineering readouts (health index, vibration RMS,
bearing temperature, …). Threshold breach automatically maps to the alarm
palette.

| Prop | Type | Notes |
|---|---|---|
| `value` | number (required) | Current reading. |
| `min` | number | Default `0`. |
| `max` | number | Default `100`. |
| `unit` | string | e.g. `"mm/s"`, `"°C"`, `"bar"`. |
| `label` | string | Tag or short caption (e.g. `"P-101A 振动有效值"`). |
| `precision` | integer 0–8 | Decimal places to render (default `2`). |
| `thresholds.warn` | number | Below this stays primary blue. |
| `thresholds.error` | number | Beyond this fills `--alarm-medium`. |
| `thresholds.critical` | number | Beyond this fills `--alarm-critical`. |

```json
{
  "type": "gauge",
  "version": "1.0",
  "props": {
    "value": 4.8,
    "min": 0,
    "max": 10,
    "unit": "mm/s",
    "label": "P-101A 振动有效值",
    "thresholds": { "warn": 4.5, "error": 7.1, "critical": 9.0 }
  }
}
```

---

## `alarm`

List of process alarms following IEC 62682 / ISA-18.2 priorities. The frontend
only renders — there is no client-side ack/suppress. If your skill needs an
acknowledgment action, follow up with a `form` or `confirm` block.

| Prop | Type | Notes |
|---|---|---|
| `title` | string | Optional section title. |
| `items` | array (required, ≤ 500) | Alarm entries (see below). |

Alarm item:

| Field | Type | Notes |
|---|---|---|
| `level` | `"critical" \| "high" \| "medium" \| "low" \| "journal"` | Priority. |
| `message` | string (≤ 2000) | Human-readable description. |
| `tag` | string | Optional process tag, e.g. `"TI-101A-B1"`. |
| `time` | string | ISO timestamp or formatted local time. |
| `source` | string | Origin (sensor, rule, agent name). |
| `acked` | boolean | Whether the alarm has been acknowledged. |

```json
{
  "type": "alarm",
  "version": "1.0",
  "props": {
    "title": "P-101A 当前报警",
    "items": [
      {
        "level": "high",
        "message": "轴承温度超阈",
        "tag": "TI-101A-B1",
        "time": "2026-05-17 09:14:00"
      },
      { "level": "journal", "message": "操作员确认报警", "acked": true }
    ]
  }
}
```

---

## `metric`

Engineering readout for a single tag. Numeric formatting is locked to
`tabular-nums`, so columns of metrics align across rows.

| Prop | Type | Notes |
|---|---|---|
| `tag` | string | Process tag or identifier. |
| `label` | string | Friendly description. |
| `value` | number \| string (required) | Current reading. Strings are accepted for sentinel values like `"N/A"`. |
| `unit` | string | Engineering unit. |
| `precision` | integer 0–8 | Decimal places when `value` is numeric. |
| `setpoint` | number | Optional setpoint (rendered as `SP n`). |
| `range.ll / l / h / hh` | number | Low-low, low, high, high-high process limits. |
| `delta.value` | number \| string | Difference vs a baseline. |
| `delta.direction` | `"up" \| "down" \| "flat"` | Tone of the delta. |
| `delta.vs` | string | Baseline label (e.g. `"上一周期"`). |
| `status` | one of the six status kinds | Optional contextual marker. |

```json
{
  "type": "metric",
  "version": "1.0",
  "props": {
    "tag": "FI-101",
    "label": "进料流量",
    "value": 128.4,
    "unit": "t/h",
    "precision": 1,
    "setpoint": 130,
    "range": { "ll": 100, "l": 110, "h": 145, "hh": 155 },
    "delta": { "value": "-1.2", "direction": "down", "vs": "上一周期" }
  }
}
```

---

## `status`

Operating-state badge for a single piece of equipment. Six canonical states:

| `status` | Label (zh-CN) | CSS variable |
|---|---|---|
| `running` | 运行 | `--status-running` |
| `stopped` | 停机 | `--status-stopped` |
| `maint` | 维修 | `--status-maint` |
| `standby` | 备用 | `--status-standby` |
| `fault` | 故障 | `--status-fault` |
| `comm-loss` | 失联 | `--status-comm-loss` |

| Prop | Type | Notes |
|---|---|---|
| `status` | one of the six (required) | Maps to the `--status-*` palette. |
| `tag` | string | Optional tag. |
| `label` | string | Optional friendly description. |

`comm-loss` is rendered with a slow pulse so the operator notices stale
data; under `prefers-reduced-motion: reduce` the pulse is automatically
disabled (handled globally in `globals.css`).

```json
{
  "type": "status",
  "version": "1.0",
  "props": { "status": "running", "tag": "P-101A", "label": "原油泵 A" }
}
```

---

## Color contract — what skills should NOT do

- **Do not write hard-coded hex colors** in chart series, alarm rows, or any
  other block. The Tailwind palette already exposes `--color-alarm-*` and
  `--color-status-*` (and the standard shadcn tokens) as utility classes,
  e.g. `bg-alarm-high text-alarm-foreground`. Hard-coded hex values break
  theme switching (industrial-dark / industrial-light / light / dark).
- **Do not assume a specific viewport size**. Blocks render inside the
  workspace message stream and inside multi-column layouts; rely on the
  responsive defaults of the block itself.
- **Do not embed motion**. Industrial HMIs (ISA-101 §6.6) want static
  surfaces by default; motion is reserved for state transitions and is
  governed globally by `prefers-reduced-motion`.

---

## Adding a new industrial primitive

If a future skill needs a primitive that the four above cannot express:

1. Add a component file at `frontend/src/components/genui/<NameBlock>.tsx`
   following the conventions in this folder.
2. Register it in `frontend/src/core/genui/registry.ts`.
3. Whitelist its props in `frontend/src/core/genui/sanitizer.ts`.
4. Add a Zod schema and entry in `frontend/src/core/genui/validator.ts`.
5. Document the schema in this file.
6. Add unit tests under `frontend/tests/unit/components/genui/`.

Keeping the block list small and **truly generic** is intentional —
business semantics live in skills, not in frontend components.
