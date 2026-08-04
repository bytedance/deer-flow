import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, renderHook } from "@testing-library/react";

const mockState = rs.hoisted(() => ({
  mode: "skill" as string | null,
  setInput: rs.fn(),
  threadId: "new",
}));

rs.mock("next/navigation", () => ({
  useParams: () => ({ thread_id: mockState.threadId }),
  useSearchParams: () => ({
    get: (name: string) => (name === "mode" ? mockState.mode : null),
  }),
}));

rs.mock("@/components/ai-elements/prompt-input", () => ({
  usePromptInputController: () => ({
    textInput: { setInput: mockState.setInput },
  }),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: { inputBox: { createSkillPrompt: "Create a skill" } },
  }),
}));

import { useSpecificChatMode } from "@/components/workspace/chats/use-chat-mode";

beforeEach(() => {
  rs.useFakeTimers();
  mockState.mode = "skill";
  mockState.threadId = "new";
  mockState.setInput.mockReset();
});

afterEach(() => {
  cleanup();
  rs.useRealTimers();
});

describe("useSpecificChatMode", () => {
  it("cancels the delayed prompt when navigation leaves skill mode", () => {
    const { rerender } = renderHook(() => useSpecificChatMode());

    mockState.mode = null;
    rerender();
    act(() => {
      rs.advanceTimersByTime(100);
    });

    expect(mockState.setInput).not.toHaveBeenCalled();

    mockState.mode = "skill";
    rerender();
    act(() => {
      rs.advanceTimersByTime(100);
    });

    expect(mockState.setInput).toHaveBeenCalledOnce();
    expect(mockState.setInput).toHaveBeenCalledWith("Create a skill");
  });
});
