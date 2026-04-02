import { beforeEach, describe, expect, test, vi } from "vitest";

import { fireEvent, render, screen } from "@/test/render";

import { VsfxTreeView, type VsfxTreeNodeData } from "./VsfxTreeView";

const scrollIntoViewSpy = vi.fn();

const sampleTree: VsfxTreeNodeData[] = [
  {
    children: [
      {
        children: [
          {
            children: [],
            handle: 42,
            name: "Bolt",
          },
        ],
        handle: 10,
        name: "Sub Assembly",
      },
    ],
    handle: 0,
    name: "Assembly",
  },
];

describe("VsfxTreeView", () => {
  beforeEach(() => {
    scrollIntoViewSpy.mockReset();
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoViewSpy,
      writable: true,
    });
  });

  test("clicking a node selects its handles and double-clicking zooms to the selection", () => {
    const onSelectHandles = vi.fn();
    const onToggleVisibility = vi.fn();
    const onZoomToSelection = vi.fn();

    render(
      <VsfxTreeView
        hiddenHandles={new Set()}
        nodes={sampleTree}
        onSelectHandles={onSelectHandles}
        onToggleVisibility={onToggleVisibility}
        onZoomToSelection={onZoomToSelection}
        selectedHandles={[]}
      />, 
    );

    fireEvent.click(screen.getByRole("button", { name: "Toggle Assembly" }));
    fireEvent.click(screen.getByRole("button", { name: "Toggle Sub Assembly" }));
    fireEvent.click(screen.getByRole("button", { name: "Bolt" }));
    expect(onSelectHandles).toHaveBeenCalledWith([42]);

    fireEvent.doubleClick(screen.getByRole("button", { name: "Bolt" }));
    expect(onZoomToSelection).toHaveBeenCalledTimes(1);
  });

  test("auto-expands the selected path and scrolls the primary node into view", () => {
    render(
      <VsfxTreeView
        hiddenHandles={new Set()}
        nodes={sampleTree}
        onSelectHandles={vi.fn()}
        onToggleVisibility={vi.fn()}
        onZoomToSelection={vi.fn()}
        selectedHandles={[42]}
      />,
    );

    expect(screen.getByRole("button", { name: "Assembly" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sub Assembly" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bolt" })).toBeInTheDocument();
    expect(screen.getByLabelText("Toggle Assembly")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Toggle Sub Assembly")).toHaveAttribute("aria-expanded", "true");
    expect(scrollIntoViewSpy).toHaveBeenCalledTimes(1);
  });

  test("forwards hide and show requests for the matching handles", () => {
    const onToggleVisibility = vi.fn();

    const { rerender } = render(
      <VsfxTreeView
        hiddenHandles={new Set()}
        nodes={sampleTree}
        onSelectHandles={vi.fn()}
        onToggleVisibility={onToggleVisibility}
        onZoomToSelection={vi.fn()}
        selectedHandles={[]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Toggle Assembly" }));
    fireEvent.click(screen.getByRole("button", { name: "Toggle Sub Assembly" }));
    fireEvent.click(screen.getByRole("button", { name: "Hide Bolt" }));
    expect(onToggleVisibility).toHaveBeenCalledWith([42], true);

    rerender(
      <VsfxTreeView
        hiddenHandles={new Set([42])}
        nodes={sampleTree}
        onSelectHandles={vi.fn()}
        onToggleVisibility={onToggleVisibility}
        onZoomToSelection={vi.fn()}
        selectedHandles={[]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Show Bolt" }));
    expect(onToggleVisibility).toHaveBeenLastCalledWith([42], false);
  });
});
