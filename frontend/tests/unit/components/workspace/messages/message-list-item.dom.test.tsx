import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";

import { MessageListItem } from "@/components/workspace/messages/message-list-item";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import * as messageUtils from "@/core/messages/utils";

// The unit under test is the row's copy-data memo, not message rendering.
// Stubbing the markdown pipeline also removes its first-render suspension:
// when a settled body suspends, React restarts the render attempt and
// legitimately re-runs useMemo factories, which would make call counts
// depend on microtask timing instead of the memo's own deps.
rs.mock("@/components/workspace/messages/markdown-content", () => ({
  MarkdownContent: () => null,
}));

// Count calls to the copy-data derivation itself. The render path reads the
// message content for the body (markdown, reasoning, tasks), so content
// getters cannot distinguish rendering reads from copy derivation — the spy
// on the derived entry point can.
const copyDataCalls = rs.spyOn(messageUtils, "getMessageCopyData");

function makeMessage(type: "human" | "ai"): Message {
  return {
    id: `${type}-1`,
    type,
    content: "copy me",
  } as unknown as Message;
}

function withI18n(ui: React.ReactElement) {
  return (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      {ui}
    </I18nContext.Provider>
  );
}

function renderRow(
  message: Message,
  {
    showCopyButton,
    isLoading = false,
  }: { showCopyButton: boolean; isLoading?: boolean },
) {
  return render(
    withI18n(
      <MessageListItem
        message={message}
        threadId="thread-1"
        showCopyButton={showCopyButton}
        isLoading={isLoading}
      />,
    ),
  );
}

afterEach(cleanup);
afterEach(() => {
  copyDataCalls.mockClear();
});

describe("MessageListItem copy-data derivation guard", () => {
  it("derives no copy data for an assistant row that never renders the toolbar", () => {
    const message = makeMessage("ai");

    const view = renderRow(message, { showCopyButton: false });
    expect(copyDataCalls).toHaveBeenCalledTimes(0);

    // The sole call site passes showCopyButton only for non-assistant rows;
    // the memo must stay gated so settled assistant rows skip the derivation
    // entirely (the pre-memo call sat behind the same toolbar guard).
    view.rerender(
      withI18n(
        <MessageListItem
          message={message}
          threadId="thread-1"
          showCopyButton={false}
          isLoading={false}
        />,
      ),
    );
    expect(copyDataCalls).toHaveBeenCalledTimes(0);
  });

  it("derives a human row's copy data once and reuses it across re-renders", () => {
    const message = makeMessage("human");

    const view = renderRow(message, { showCopyButton: true });
    // One memo serves both editing and the toolbar — not one derivation per
    // consumer.
    expect(copyDataCalls).toHaveBeenCalledTimes(1);

    view.rerender(
      withI18n(
        <MessageListItem
          message={message}
          threadId="thread-1"
          showCopyButton={true}
          isLoading={false}
        />,
      ),
    );
    expect(copyDataCalls).toHaveBeenCalledTimes(1);
  });

  it("still derives for a human row while loading (editing needs it)", () => {
    const message = makeMessage("human");

    renderRow(message, { showCopyButton: true, isLoading: true });

    expect(copyDataCalls.mock.calls.length).toBeGreaterThan(0);
  });
});
