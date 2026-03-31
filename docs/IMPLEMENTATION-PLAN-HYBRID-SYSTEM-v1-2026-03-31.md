# Implementation Plan v1: Hybrid System `OpenClaw + DeerFlow`

## 1. Mục tiêu

Chuyển blueprint v2 thành một lộ trình build thực thi được, theo hướng:

- giảm rủi ro sớm
- chứng minh giá trị sớm
- tránh over-engineering

## 2. Nguyên tắc triển khai

- `DeerFlow-first`, không hybrid hóa ngay từ ngày đầu
- implementation phải bám contract
- mọi tích hợp sau này với OpenClaw phải đi qua bridge rõ ràng
- task nào chưa có observability tối thiểu thì chưa coi là production-worthy

## 3. Workstreams

### WS1. Contract and adapter

Mục tiêu:

- chuẩn hóa request / response / error
- xây response adapter cho DeerFlow output

Deliverables:

- schema v1
- adapter spec
- artifact manifest format

Acceptance criteria:

- một DeerFlow run có thể được map sang status chuẩn
- artifact list đọc được bằng máy
- failure có thể map vào error contract

### WS2. DeerFlow-first execution path

Mục tiêu:

- chạy 2 use case đầu hoàn toàn trong DeerFlow

Deliverables:

- pilot runbook
- prompt templates
- task input templates

Acceptance criteria:

- deep research chạy được end-to-end
- code review chạy được end-to-end
- có output đủ để đánh giá latency, chất lượng, chi phí

### WS3. Auth and observability baseline

Mục tiêu:

- không để integration path trở thành black box

Deliverables:

- request_id tracing
- structured logs
- timeout policy
- minimal auth

Acceptance criteria:

- truy được một task từ input đến output bằng request_id
- biết task fail ở đâu
- biết task mất bao lâu

### WS4. Async UX model

Mục tiêu:

- xử lý deep task như async workflow thật sự

Deliverables:

- accepted / running / partial / completed / failed states
- progress heartbeat spec
- partial result policy

Acceptance criteria:

- user không bị rơi vào trạng thái im lặng kéo dài
- long-run task có thể báo tiến độ

### WS5. OpenClaw bridge readiness

Mục tiêu:

- chỉ chuẩn bị cho hybrid, chưa bắt buộc build ngay

Deliverables:

- bridge interface spec
- channel ownership policy
- routing policy

Acceptance criteria:

- đủ rõ để bắt đầu build khi pilot chứng minh cần hybrid

## 4. Phase-by-phase backlog

### Phase 0. Architecture finalization

Tasks:

- chốt blueprint v2
- chốt request contract
- chốt response contract
- chốt error contract
- chốt channel ownership policy
- chốt success metrics cho pilot

Definition of done:

- có tài liệu final v2
- không còn ambiguity ở contract và ownership

### Phase 1. DeerFlow-first MVP

Tasks:

- chọn 2 use case đầu
- viết input template cho từng use case
- xây response adapter spec
- thêm basic tracing format
- định nghĩa timeout và partial-result behavior

Definition of done:

- có thể chạy use case bằng DeerFlow-only
- output map được sang contract
- có evidence về duration và artifact quality

### Phase 2. Pilot execution

Tasks:

- chạy deep research pilot
- chạy code review pilot
- ghi lại latency, failure modes, cost estimate
- tổng hợp lessons learned

Definition of done:

- có pilot report
- biết DeerFlow-only có cover đủ use case hay không

### Phase 3. Decision gate

Decision cần trả lời:

- DeerFlow-only đã đủ chưa?
- Có thật sự cần OpenClaw integration ngay không?
- Nhu cầu channel bổ sung có đủ mạnh để justify hybrid overhead không?

Definition of done:

- ra quyết định rõ: tiếp tục DeerFlow-only hay mở bridge sang OpenClaw

### Phase 4. OpenClaw bridge MVP

Chỉ vào phase này nếu gate ở Phase 3 cho kết quả `YES`.

Tasks:

- tạo execution bridge
- gửi request packet từ OpenClaw sang DeerFlow
- nhận structured output đã qua adapter
- trả kết quả về kênh gốc

Definition of done:

- OpenClaw nhận task
- DeerFlow xử lý
- OpenClaw trả kết quả đúng kênh

### Phase 5. Smart routing and optional memory sync

Tasks:

- suggest routing
- confirm flow
- nghiên cứu selective memory sync nếu thật sự cần

Definition of done:

- routing không phá UX
- memory sync không gây contamination

## 5. Risk register for implementation

### Risk A. Adapter underestimated

Nguy cơ:

- team nghĩ adapter chỉ là formatter đơn giản
- thực tế nó là lớp chuẩn hóa output quan trọng

Mitigation:

- xem adapter như workstream riêng
- không dồn sang cuối phase

### Risk B. Pilot không đo được gì

Nguy cơ:

- chạy thử có vẻ “hay”
- nhưng không có số liệu latency, cost, quality

Mitigation:

- bắt buộc log request_id, duration, status
- pilot report phải có số liệu tối thiểu

### Risk C. Tích hợp OpenClaw quá sớm

Nguy cơ:

- build bridge trước khi DeerFlow-only chứng minh giá trị

Mitigation:

- giữ decision gate rõ sau Phase 2

### Risk D. Channel ownership mơ hồ

Nguy cơ:

- user-facing channel bị overlap giữa hai hệ thống

Mitigation:

- policy rõ ngay từ đầu
- chỉ một hệ thống own end-user channels trong hybrid mode

## 6. Deliverables nên có trước khi code

- blueprint v2
- implementation plan
- pilot success criteria
- data capture template cho latency / cost / failure
- decision gate checklist cho hybrid escalation

## 7. Khuyến nghị hành động tiếp theo

Bước tiếp theo hợp lý nhất:

1. dùng bản v2 này làm canonical architecture
2. bắt đầu Phase 1 theo hướng DeerFlow-first
3. sau pilot, mới quyết định có kích hoạt bridge sang OpenClaw hay không

Đây là con đường ít rủi ro nhất nhưng vẫn giữ được end-state toàn diện.

