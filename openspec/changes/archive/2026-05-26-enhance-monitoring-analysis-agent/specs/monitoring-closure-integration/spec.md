## ADDED Requirements

### Requirement: Automatic closure ticket for critical monitoring findings
The agent SHALL call `create_closure_ticket` when monitoring analysis detects anomalies with `severity: "critical"` or findings with `severity: "high"` and `confidence ≥ 0.7`.

#### Scenario: Critical anomaly creates closure ticket
- **WHEN** anomaly detection identifies a vibration spike exceeding alarm threshold with severity "critical"
- **THEN** agent calls `create_closure_ticket(title="<设备名> 振动超标", description="<异常概述>", device_id="<equipment_id>", device_name="<equipment_name>", priority="urgent", severity="critical", source_type="monitoring", source_run_id="<run_id>", source_thread_id="<thread_id>", metadata={findings: [...], confidence: 0.85, evidence_uri: "..."})`

#### Scenario: High-confidence degradation trend creates closure ticket
- **WHEN** trend analysis detects a degradation slope with severity "high" and confidence ≥ 0.7
- **THEN** agent calls `create_closure_ticket` with `priority="important"`, `severity="high"`, and `source_type="monitoring"`

#### Scenario: Low severity does not auto-create ticket
- **WHEN** all findings have severity "info" or "warning" (below "high")
- **THEN** agent does NOT call `create_closure_ticket` but includes a note: "未达自动建单阈值，可在工作台手动登记"

#### Scenario: Duplicate ticket reused
- **WHEN** `create_closure_ticket` returns `created: false`
- **THEN** agent reports "已复用既有闭环单 `ct_xxxxx`" instead of creating a duplicate

### Requirement: Closure ticket metadata follows source_type contract
The agent SHALL populate `metadata` with `source_type="monitoring"` following the closed-loop-agent-integration spec's metadata schema.

#### Scenario: Monitoring metadata structure
- **WHEN** agent creates a monitoring closure ticket
- **THEN** `metadata` contains: `findings` (list of finding descriptions), `confidence` (float 0-1), `evidence_uri` (pointing to the monitoring report artifact), `analysis_type` (trend/anomaly/kpi/correlation), and `monitoring_run_id`

#### Scenario: Evidence URI points to report
- **WHEN** closure ticket is created
- **THEN** `metadata.evidence_uri` equals `/api/threads/<thread_id>/artifacts/mnt/user-data/outputs/monitoring_report.md`

### Requirement: Closure ticket summary in report
When closure tickets are created, the agent SHALL append a "## 闭环跟踪" section to the monitoring report listing each ticket ID, priority, and SLA deadline.

#### Scenario: Closure tracking section with single ticket
- **WHEN** one closure ticket `ct_abc123` is created with priority "urgent"
- **THEN** the report ends with "## 闭环跟踪" containing: "已为该异常登记闭环单 `ct_abc123`，优先级 urgent，SLA 截止 <due_at>。可在 工作台 → 闭环管理 跟进。"

#### Scenario: Multiple tickets listed
- **WHEN** 3 closure tickets are created for 3 different equipment
- **THEN** the closure tracking section lists all 3 tickets in a compact markdown table: ticket ID, equipment, priority, SLA deadline
