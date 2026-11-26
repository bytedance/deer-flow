import { describe, expect, it } from "@rstest/core";

import { enUS } from "@/core/i18n/locales/en-US";
import { getStreamErrorToastMessage } from "@/core/threads/hooks";

describe("getStreamErrorToastMessage", () => {
  it("says sandboxes are temporarily unavailable for a capacity run error", () => {
    // The SDK turns the run's error event into an Error named after the
    // backend exception; the message holds the provider's raw details.
    const error = new Error(
      "All sandbox replica slots are in use (code=SANDBOX_CAPACITY_EXCEEDED, retry_after_seconds=30.0)",
    );
    error.name = "SandboxCapacityExceededError";

    expect(getStreamErrorToastMessage(error, enUS)).toBe(
      enUS.conversation.sandboxBusy,
    );
  });

  it("says sandboxes are temporarily unavailable for a raw frame with the code", () => {
    expect(
      getStreamErrorToastMessage(
        { message: "raw", code: "SANDBOX_CAPACITY_EXCEEDED" },
        enUS,
      ),
    ).toBe(enUS.conversation.sandboxBusy);
  });

  it("keeps other run errors' messages", () => {
    const error = new Error("boom");
    error.name = "RuntimeError";

    expect(getStreamErrorToastMessage(error, enUS)).toBe("boom");
  });
});
