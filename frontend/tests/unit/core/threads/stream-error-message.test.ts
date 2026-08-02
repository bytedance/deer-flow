import { describe, expect, it } from "@rstest/core";

import { getStreamErrorMessage } from "@/core/threads/stream-error-message";

describe("getStreamErrorMessage", () => {
  it("turns an HTTP 402 insufficient-credit error into a friendly message", () => {
    const error = new Error(
      'HTTP 402: {"detail":{"code":"INSUFFICIENT_CREDITS","available_credits":1,"required_credits":15}}',
    );

    expect(getStreamErrorMessage(error)).toBe(
      "积分不足：当前可用 1 积分，本次任务至少需要 15 积分。请先充值后重新发起任务。",
    );
  });
});
