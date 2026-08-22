import { describe, expect, it } from "@rstest/core";

import {
  type BackgroundTaskDetail,
  shouldPollBackgroundTaskDetail,
} from "@/core/background-tasks/types";

const TERMINAL_TASK: BackgroundTaskDetail = {
  task_id: "task-1",
  task_name: "Generate report",
  status: "completed",
  created_at: "2026-08-08T00:00:00+00:00",
  updated_at: "2026-08-08T00:01:00+00:00",
  error: null,
  tracking_degraded: false,
  cancel_requested: false,
  last_polled_at: "2026-08-08T00:01:00+00:00",
  last_poll_error: null,
  last_cancel_error: null,
  cancel_attempt_count: 0,
  notification_status: "retry",
  notification_error: "Agent notification failed",
  notification_attempt_count: 2,
  result: { done: true },
  result_preview: null,
  result_truncated: false,
  result_artifact: null,
  input_required: null,
};

describe("background task detail polling", () => {
  it.each(["pending", "claimed", "retry", "dispatched"] as const)(
    "keeps polling a terminal task while notification status is %s",
    (notificationStatus) => {
      expect(
        shouldPollBackgroundTaskDetail({
          ...TERMINAL_TASK,
          notification_status: notificationStatus,
        }),
      ).toBe(true);
    },
  );

  it.each(["none", "delivered", "dead_letter"] as const)(
    "stops polling a terminal task when notification status is %s",
    (notificationStatus) => {
      expect(
        shouldPollBackgroundTaskDetail({
          ...TERMINAL_TASK,
          notification_status: notificationStatus,
        }),
      ).toBe(false);
    },
  );

  it("keeps polling active tasks independently of notification state", () => {
    expect(
      shouldPollBackgroundTaskDetail({
        ...TERMINAL_TASK,
        status: "working",
        notification_status: "none",
      }),
    ).toBe(true);
  });
});
