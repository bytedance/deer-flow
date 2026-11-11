// The acceptance matrix behind `sendMessage` resolving: a frame may retire a
// send only when it can own the run that produced it. The new-chat case is the
// one that regressed (#8039): the page passes a placeholder id, the frame names
// the server's real thread, and the send must still accept it — but not when a
// second unnamed send could own the same frame.
import { describe, expect, it } from "@rstest/core";

import { shouldAcceptPendingSend } from "@/core/threads/hooks";

const base = {
  frameThreadId: "thread-1",
  pendingThreadId: "thread-1",
  pendingNewThread: false,
  retiredReleased: false,
  otherUnnamedReleased: false,
};

describe("shouldAcceptPendingSend", () => {
  it("accepts a frame naming the pending thread", () => {
    expect(shouldAcceptPendingSend(base)).toBe(true);
  });

  it("rejects a frame naming another thread for an existing conversation", () => {
    expect(
      shouldAcceptPendingSend({ ...base, frameThreadId: "thread-2" }),
    ).toBe(false);
  });

  it("accepts anything for a send that has no thread id yet", () => {
    expect(shouldAcceptPendingSend({ ...base, pendingThreadId: "" })).toBe(
      true,
    );
  });

  it("lets a new-chat send adopt the thread its own frame names", () => {
    expect(
      shouldAcceptPendingSend({
        ...base,
        frameThreadId: "thread-new",
        pendingThreadId: "placeholder-thread",
        pendingNewThread: true,
      }),
    ).toBe(true);
  });

  it("does not let that frame also retire a second unnamed send", () => {
    expect(
      shouldAcceptPendingSend({
        ...base,
        frameThreadId: "thread-new",
        pendingThreadId: "placeholder-thread",
        pendingNewThread: true,
        otherUnnamedReleased: true,
      }),
    ).toBe(false);
  });

  it("does not settle a new-chat send after the frame retired another one", () => {
    expect(
      shouldAcceptPendingSend({
        ...base,
        frameThreadId: "thread-new",
        pendingThreadId: "placeholder-thread",
        pendingNewThread: true,
        retiredReleased: true,
      }),
    ).toBe(false);
  });

  it("treats an id-less frame as no acceptance at all", () => {
    expect(shouldAcceptPendingSend({ ...base, frameThreadId: "" })).toBe(false);
  });
});
