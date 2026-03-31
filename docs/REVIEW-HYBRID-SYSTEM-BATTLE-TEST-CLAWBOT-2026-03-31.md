# REVIEW-HYBRID-SYSTEM-BATTLE-TEST-CLAWBOT-2026-03-31

## Executive judgment
GO có điều kiện. Bộ tài liệu đủ để bắt đầu build MVP, nhưng chưa đủ chặt ở tầng vận hành thực chiến nếu giữ scope rộng hiện tại.

## What will work
1. DeerFlow-first rollout là đúng để giảm risk tích hợp sớm.
2. Tách Presence (OpenClaw) và Execution (DeerFlow) là đúng bản chất.
3. Có contract + adapter + error policy là nền đúng để chống vỡ integration.
4. Channel ownership policy (OpenClaw own end-user channels khi hybrid) là hợp lý.

## What will likely break
1. Response adapter bị underestimate (điểm vỡ số 1).
2. Heartbeat/progress nếu không đều hoặc không meaningful sẽ gây duplicate submit.
3. Observability chỉ có request_id nhưng thiếu timeline correlation sẽ vẫn khó debug.
4. Phase plan còn thiên về ý tưởng, thiếu runbook operator-level.

## What is underspecified
1. Idempotency contract (retry/duplicate prevention).
2. Artifact lifecycle (lưu ở đâu, retention, access, cleanup).
3. Timeout semantics theo task class.
4. Incident/runbook: fail thì operator làm gì trong 3 bước.
5. KPI threshold pass/fail cụ thể cho decision gates.

## Minimum viable path
- Chỉ làm 1 use case đầu: Deep Research.
- Chỉ DeerFlow-only, explicit deep routing.
- Adapter tối thiểu: accepted/running/completed/failed + short summary + artifacts + top-level error mapping.
- Bắt buộc trong MVP:
  - request_id xuyên suốt
  - idempotency key
  - heartbeat 30-60s cho task >60s
  - timeout + partial result usable
  - dashboard/log truy vết được
- Timebox: 10-14 ngày.

## Recommended cuts
1. Cắt use case B/C khỏi sprint đầu.
2. Cắt memory sync khỏi MVP.
3. Cắt smart routing trước khi có dữ liệu explicit routing.
4. Không build OpenClaw bridge ở sprint 1.

## Go / No-go
- GO nếu giữ đúng vertical slice hẹp + gate đo lường.
- NO-GO nếu làm song song multi-use-case + bridge + UX hardening ngay từ đầu.

## Final recommendation
Bắt đầu build ngay theo DeerFlow-first MVP hẹp. Sau pilot 2 tuần mới mở gate quyết định có bật bridge OpenClaw.
