/* @vitest-environment jsdom */

import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useDocumentVisible } from "@/hooks/use-document-visible";

function VisibilityProbe({
  snapshots,
}: {
  snapshots: boolean[];
}) {
  const visible = useDocumentVisible();
  snapshots.push(visible);
  return React.createElement("div", null, String(visible));
}

describe("useDocumentVisible", () => {
  let container: HTMLDivElement;
  let root: Root;
  let originalVisibilityState: DocumentVisibilityState;

  beforeEach(() => {
    originalVisibilityState = document.visibilityState;
    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      writable: true,
      configurable: true,
    });
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    React.act(() => {
      root.unmount();
    });
    container.remove();
    Object.defineProperty(document, "visibilityState", {
      value: originalVisibilityState,
      writable: true,
      configurable: true,
    });
  });

  function setVisibility(state: DocumentVisibilityState) {
    Object.defineProperty(document, "visibilityState", {
      value: state,
      writable: true,
      configurable: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  }

  it("returns true when document is visible", async () => {
    const snapshots: boolean[] = [];
    await React.act(async () => {
      root.render(React.createElement(VisibilityProbe, { snapshots }));
    });
    await Promise.resolve();
    expect(snapshots.at(-1)).toBe(true);
  });

  it("returns false when document is hidden", async () => {
    setVisibility("hidden");
    const snapshots: boolean[] = [];
    await React.act(async () => {
      root.render(React.createElement(VisibilityProbe, { snapshots }));
    });
    await Promise.resolve();
    expect(snapshots.at(-1)).toBe(false);
  });

  it("updates when visibility changes from visible to hidden", async () => {
    const snapshots: boolean[] = [];
    await React.act(async () => {
      root.render(React.createElement(VisibilityProbe, { snapshots }));
    });
    await Promise.resolve();
    expect(snapshots.at(-1)).toBe(true);

    await React.act(async () => {
      setVisibility("hidden");
      await Promise.resolve();
    });
    expect(snapshots.at(-1)).toBe(false);
  });

  it("transitions back to visible", async () => {
    setVisibility("hidden");
    const snapshots: boolean[] = [];
    await React.act(async () => {
      root.render(React.createElement(VisibilityProbe, { snapshots }));
    });
    await Promise.resolve();
    expect(snapshots.at(-1)).toBe(false);

    await React.act(async () => {
      setVisibility("visible");
      await Promise.resolve();
    });
    expect(snapshots.at(-1)).toBe(true);
  });
});
