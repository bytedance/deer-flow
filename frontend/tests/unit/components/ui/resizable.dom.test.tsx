/**
 * Structure pin for the focus-ring occlusion fix: the handle's :focus-visible
 * ring paints outside its 2px box, where panel chrome (sticky table headers
 * z-10, full-bleed bg panels) paints over it — so the ring state must carry a
 * z-lift, and only the ring state (unfocused stacking stays untouched). Ring
 * geometry itself is real-browser territory; classes are pinned here.
 */
import { beforeAll, describe, expect, it } from "@rstest/core";
import { render } from "@testing-library/react";

import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";

beforeAll(() => {
  if (!("ResizeObserver" in globalThis)) {
    class ResizeObserverStub {
      observe() {
        /* no-op stub */
      }
      unobserve() {
        /* no-op stub */
      }
      disconnect() {
        /* no-op stub */
      }
    }
    (globalThis as Record<string, unknown>).ResizeObserver = ResizeObserverStub;
  }
});

function renderHandle() {
  const { container } = render(
    <ResizablePanelGroup orientation="horizontal">
      <ResizablePanel defaultSize={50}>left</ResizablePanel>
      <ResizableHandle />
      <ResizablePanel defaultSize={50}>right</ResizablePanel>
    </ResizablePanelGroup>,
  );
  return container.querySelector('[data-slot="resizable-handle"]');
}

describe("ResizableHandle", () => {
  it("arms the focus z-lift together with the ring, and only on focus-visible", () => {
    const handle = renderHandle();
    expect(handle).toBeTruthy();
    const cls = handle!.getAttribute("class") ?? "";
    expect(cls).toContain("focus-visible:ring-1");
    expect(cls).toContain("focus-visible:z-30");
    // The lift must be focus-scoped: an always-on z would change stacking
    // (and drag hit-testing vs panel popups) for every unfocused gutter.
    expect(cls).not.toMatch(/(?:^|\s)z-30(?:\s|$)/);
  });
});
