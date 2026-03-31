# Task Brief for Clawbot: Battle-Test Review `OpenClaw + DeerFlow`

## 1. Bối cảnh

Chúng tôi đang xem xét kiến trúc:

- `OpenClaw` làm presence layer
- `DeerFlow` làm deep execution layer

Các tài liệu đầu vào:

- `docs/HYBRID-SYSTEM-BLUEPRINT-OPENCLAW-DEERFLOW-v2-2026-03-31.md`
- `docs/IMPLEMENTATION-PLAN-HYBRID-SYSTEM-v1-2026-03-31.md`
- `docs/VALUE-REALIZATION-MAP-HYBRID-SYSTEM-2026-03-31.md`

## 2. Vai trò review của Clawbot

Hãy review như một người chịu trách nhiệm biến ý tưởng thành hệ thống chạy được ngoài đời.

Trọng tâm của Clawbot không phải là “kiến trúc đẹp”, mà là:

- buildability
- operability
- battle-test realism
- failure under real conditions

## 3. Câu hỏi Clawbot cần trả lời

1. Kế hoạch hiện tại có triển khai được theo từng phase hay vẫn còn quá lý tưởng?
2. Chỗ nào sẽ vỡ đầu tiên khi đưa vào dùng thật?
3. Chỗ nào đang thiếu specification vận hành?
4. MVP nào là nhỏ nhất nhưng vẫn chứng minh được giá trị?
5. Nên cắt bớt điều gì để giảm risk mà không làm mất lõi chiến lược?

## 4. Những góc Clawbot phải pressure-test

### 4.1. Battle-test realism

- deep task có bị quá chậm không?
- progress heartbeat có đủ chưa?
- retry / timeout / partial-result policy có usable chưa?

### 4.2. Operational viability

- logging, tracing, auth đã đủ để debug chưa?
- request_id flow có đủ chặt chưa?
- nếu một task fail giữa chừng, người vận hành có biết phải nhìn vào đâu không?

### 4.3. Integration practicality

- response adapter layer có đang bị underestimate không?
- bridge giữa OpenClaw và DeerFlow có cần chia thành nhiều bước nhỏ hơn không?
- ownership của channel, session, artifact có rõ chưa?

### 4.4. Rollout sanity

- phase nào nên giữ
- phase nào nên cắt
- phase nào nên nhập lại
- phase nào chỉ nên làm nếu pilot đã chứng minh ROI

## 5. Kỳ vọng đầu ra

Hãy trả lời theo cấu trúc:

- `Executive judgment`
- `What will work`
- `What will likely break`
- `What is underspecified`
- `Minimum viable path`
- `Recommended cuts`
- `Go / No-go from an implementation realism perspective`

## 6. Guardrails

- Không khen xã giao.
- Không review kiểu “nghe hợp lý”.
- Phải chỉ ra điểm nào khó build, khó vận hành, khó bảo trì.
- Nếu thấy roadmap vẫn còn quá rộng, hãy đề xuất bản hẹp hơn.

## 7. Mục tiêu của vòng review này

Mục tiêu là biết:

- liệu hệ thống này có thể trở thành một cỗ máy thực chiến hay không
- MVP nào đáng build nhất
- và complexity nào đang xuất hiện quá sớm

