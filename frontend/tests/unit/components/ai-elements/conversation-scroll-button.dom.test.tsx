import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ConversationScrollButton } from "@/components/ai-elements/conversation";

const stickToBottomContext = {
  isAtBottom: true,
  scrollToBottom: rs.fn(),
};

rs.mock("use-stick-to-bottom", () => ({
  useStickToBottomContext: () => stickToBottomContext,
}));

describe("ConversationScrollButton", () => {
  afterEach(() => {
    cleanup();
    stickToBottomContext.isAtBottom = true;
    stickToBottomContext.scrollToBottom = rs.fn();
  });

  it("does not render when the conversation is at the bottom", () => {
    render(<ConversationScrollButton />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("renders and scrolls to the bottom when the conversation is scrolled up", () => {
    stickToBottomContext.isAtBottom = false;
    render(<ConversationScrollButton />);
    const button = screen.getByRole("button");
    fireEvent.click(button);
    expect(stickToBottomContext.scrollToBottom).toHaveBeenCalledTimes(1);
  });

  it("passes an accessible name through to the button", () => {
    stickToBottomContext.isAtBottom = false;
    render(<ConversationScrollButton aria-label="Scroll to bottom" />);
    expect(
      screen.getByRole("button", { name: "Scroll to bottom" }),
    ).toBeDefined();
  });
});
