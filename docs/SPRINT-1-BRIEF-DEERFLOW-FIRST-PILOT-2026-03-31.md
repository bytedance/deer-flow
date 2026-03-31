# Sprint 1 Brief: DeerFlow-first Pilot

## 1. Mục tiêu sprint

Chứng minh rằng `DeerFlow` một mình đã có thể tạo ra giá trị thực cho deep task trước khi đầu tư vào hybrid integration.

Sprint này không nhằm xây platform hoàn chỉnh. Sprint này nhằm trả lời:

- output có dùng được không?
- latency có chấp nhận được không?
- execution flow có đủ ổn định không?

## 2. Use case duy nhất

**Deep Research**

Ví dụ bài toán:

- phân tích đối thủ
- tổng hợp tài liệu dài
- tạo executive brief
- tạo report có artifact rõ

Không làm code review và account intelligence trong sprint đầu.

## 3. Deliverables bắt buộc

### Functional

- chạy được 5 deep research tasks thật
- có artifact đầu ra cho từng task
- có short summary đủ gọn để dùng ở tầng presence sau này

### Technical

- adapter v0.1:
  - `accepted`
  - `running`
  - `completed`
  - `failed`
  - `short_summary`
  - `artifacts`
  - top-level error mapping
- request_id xuyên suốt
- idempotency key
- heartbeat 30-60 giây cho task dài hơn 60 giây
- timeout policy
- partial-result usable policy

### Operational

- log hoặc dashboard đủ để operator truy vết task
- pilot template để ghi latency, quality, cost estimate

## 4. Non-goals

- không build OpenClaw bridge
- không build smart routing
- không build memory sync
- không build multi-use-case pilot
- không build enterprise observability stack

## 5. Acceptance criteria

Sprint được coi là thành công nếu:

1. 5 task deep research chạy được end-to-end
2. Mỗi task đều có artifact đầu ra
3. Có thể trace từng task bằng request_id
4. Không có duplicate submit không kiểm soát
5. Có thể phân loại output:
   - dùng được ngay
   - cần sửa ít
   - cần sửa nhiều
6. Có báo cáo pilot đủ để ra decision gate

## 6. Timebox

**10-14 ngày**

Nếu quá timebox mà vẫn chưa có 5 pilot usable:

- không mở rộng scope
- không thêm hybrid bridge
- review lại execution quality trước

## 7. Quy tắc vận hành sprint

- ưu tiên value trước abstraction
- adapter v0.1 phải nhỏ, không framework hóa sớm
- mọi thứ chưa đo được thì chưa được coi là “ổn”
- failure phải được ghi lại, không che đi

## 8. Sprint review questions

Cuối sprint phải trả lời được:

1. DeerFlow-only có đủ tạo ra value không?
2. Chất lượng output có đáng để đầu tư tiếp không?
3. Có thật sự cần OpenClaw bridge ngay không?
4. Điểm nghẽn lớn nhất nằm ở execution quality, latency, hay UX?

## 9. Quyết định sau sprint

Chỉ có 3 lựa chọn hợp lệ:

- `Continue DeerFlow-only`
- `Refine DeerFlow-first and rerun pilot`
- `Approve OpenClaw bridge Sprint 2`

Không có lựa chọn “vừa chưa chứng minh xong value vừa mở rộng scope”.

