import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";

import { VirtualMessageList } from "@/components/workspace/messages/virtual-message-list";
import type { MessageGroup } from "@/core/messages/utils";

const context = rs.hoisted(() => ({
  scrollRef: { current: null as HTMLDivElement | null },
}));

rs.mock("use-stick-to-bottom", () => ({
  useStickToBottomContext: () => ({
    isAtBottom: false,
    scrollRef: context.scrollRef,
    scrollToBottom: rs.fn(),
    stopScroll: rs.fn(),
  }),
}));

// Isolate the component's own scroll listener from the virtualizer's.
rs.mock("@tanstack/react-virtual", () => ({
  defaultRangeExtractor: (range: { startIndex: number; endIndex: number }) => [
    range.startIndex,
    range.endIndex,
  ],
  useVirtualizer: () => ({
    getVirtualItems: () => [],
    getTotalSize: () => 0,
    scrollToIndex: rs.fn(),
    scrollToOffset: rs.fn(),
    getOffsetForIndex: () => [0],
    scrollOffset: 0,
    measureElement: rs.fn(),
  }),
}));

function makeGroup(id: string): MessageGroup {
  return { id, type: "assistant", messages: [] } as unknown as MessageGroup;
}

function renderGroup() {
  return <div>row</div>;
}

describe("VirtualMessageList active-group tracking", () => {
  afterEach(() => {
    cleanup();
    context.scrollRef.current = null;
  });

  it("does not re-register its scroll listener when streamed chunks change the callback identity", () => {
    const viewport = document.createElement("div");
    document.body.appendChild(viewport);
    context.scrollRef.current = viewport;
    const add = rs.spyOn(viewport, "addEventListener");
    const { rerender, unmount } = render(
      <VirtualMessageList
        groups={[makeGroup("g1")]}
        isLoading={false}
        renderGroup={renderGroup}
        onActiveGroupChange={rs.fn()}
      />,
    );

    const scrollAdds = () =>
      add.mock.calls.filter(([type]) => type === "scroll").length;
    const initial = scrollAdds();
    expect(initial).toBeGreaterThan(0);

    // Same length, new array identity and a fresh callback identity: what the
    // real consumer chain produces for every streamed token.
    rerender(
      <VirtualMessageList
        groups={[makeGroup("g1")]}
        isLoading={false}
        renderGroup={renderGroup}
        onActiveGroupChange={rs.fn()}
      />,
    );

    expect(scrollAdds()).toBe(initial);
    unmount();
    viewport.remove();
  });

  it("re-registers the scroll listener when a group is appended", () => {
    const viewport = document.createElement("div");
    document.body.appendChild(viewport);
    context.scrollRef.current = viewport;
    const add = rs.spyOn(viewport, "addEventListener");
    const { rerender, unmount } = render(
      <VirtualMessageList
        groups={[makeGroup("g1")]}
        isLoading={false}
        renderGroup={renderGroup}
        onActiveGroupChange={rs.fn()}
      />,
    );

    const scrollAdds = () =>
      add.mock.calls.filter(([type]) => type === "scroll").length;
    const initial = scrollAdds();

    rerender(
      <VirtualMessageList
        groups={[makeGroup("g1"), makeGroup("g2")]}
        isLoading={false}
        renderGroup={renderGroup}
        onActiveGroupChange={rs.fn()}
      />,
    );

    expect(scrollAdds()).toBeGreaterThan(initial);
    unmount();
    viewport.remove();
  });
});
