import { useEffect } from "react";
import { describe, expect, test, vi } from "vitest";

import type { IViewer, ViewerInteractionEventMap } from "@/lib/vsfx-viewer/viewer-core";
import { defaultOptions } from "@/lib/vsfx-viewer/viewer-core/options/IOptions";
import { act, fireEvent, render, screen, waitFor } from "@/test/render";

import { VsfxContextProvider, useVsfxContext } from "./context";
import { VsfxToolbar } from "./VsfxToolbar";

type RuntimeViewer = IViewer & {
  setActiveDragger: (name: string) => void;
};

class MockViewer implements RuntimeViewer {
  readonly executeCommand = vi.fn<(name: string, ...args: unknown[]) => unknown>();

  readonly setActiveDragger = vi.fn<(name: string) => void>();

  private readonly listeners = new Map<
    keyof ViewerInteractionEventMap,
    Set<(payload: ViewerInteractionEventMap[keyof ViewerInteractionEventMap]) => void>
  >();

  constructor() {
    this.setActiveDragger.mockImplementation((name) => {
      this.emit("changeactivedragger", name);
    });
  }

  clearSlices() {
    void 0;
  }

  dispose() {
    void 0;
  }

  getContainer() {
    return document.createElement("div");
  }

  getOptions() {
    return defaultOptions();
  }

  getSelected() {
    return [];
  }

  emit<TName extends keyof ViewerInteractionEventMap>(
    eventName: TName,
    payload: ViewerInteractionEventMap[TName],
  ) {
    const listeners = this.listeners.get(eventName);

    if (!listeners) {
      return;
    }

    for (const listener of listeners) {
      listener(payload);
    }
  }

  off<TName extends keyof ViewerInteractionEventMap>(
    eventName: TName,
    listener: (payload: ViewerInteractionEventMap[TName]) => void,
  ) {
    const existing = this.listeners.get(eventName);

    if (!existing) {
      return;
    }

    existing.delete(
      listener as (payload: ViewerInteractionEventMap[keyof ViewerInteractionEventMap]) => void,
    );
  }

  on<TName extends keyof ViewerInteractionEventMap>(
    _eventName: TName,
    listener: (payload: ViewerInteractionEventMap[TName]) => void,
  ) {
    const existing = this.listeners.get(_eventName) ?? new Set();
    existing.add(
      listener as (payload: ViewerInteractionEventMap[keyof ViewerInteractionEventMap]) => void,
    );
    this.listeners.set(_eventName, existing);

    return () => {
      this.off(_eventName, listener);
    };
  }

  open() {
    return Promise.resolve();
  }

  render() {
    void 0;
  }

  resize() {
    void 0;
  }

  update() {
    void 0;
  }
}

function ToolbarHarness({
  selectedHandles = [],
  viewer = new MockViewer(),
}: {
  selectedHandles?: Array<string | number>;
  viewer?: RuntimeViewer;
}) {
  return (
    <VsfxContextProvider artifactKey="widget.vsfx">
      <ToolbarProbe selectedHandles={selectedHandles} viewer={viewer} />
      <VsfxToolbar />
    </VsfxContextProvider>
  );
}

function ToolbarProbe({
  selectedHandles,
  viewer,
}: {
  selectedHandles: Array<string | number>;
  viewer: RuntimeViewer;
}) {
  const { actions } = useVsfxContext();

  useEffect(() => {
    actions.setViewer(viewer);
    actions.setSelectedHandles(selectedHandles);
  }, [actions, selectedHandles, viewer]);

  return null;
}

describe("VsfxToolbar", () => {
  test("renders the trimmed DeerFlow viewer toolbar", () => {
    render(<ToolbarHarness />);

    expect(screen.getByTestId("vsfx-toolbar")).toBeInTheDocument();

    for (const label of ["Pan", "Orbit", "Orbit/Pan", "Zoom"]) {
      expect(screen.getByRole("radio", { name: label })).toBeInTheDocument();
    }

    expect(screen.getByRole("radio", { name: "Walk" })).toBeInTheDocument();

    for (const label of [
      "Measure line",
      "SW",
      "Top",
      "Bottom",
      "Left",
      "Right",
      "Front",
      "Back",
      "Fit",
      "X Slice",
      "Y Slice",
      "Z Slice",
      "Clear cuts",
      "Fit selected",
      "Isolate",
      "Hide",
      "Show all",
      "Unselect",
      "Explode",
      "Collect",
      "Refresh",
      "Reset",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }

  });

  test("disables selection-dependent actions when nothing is selected", () => {
    render(<ToolbarHarness selectedHandles={[]} />);

    expect(screen.getByRole("button", { name: "Fit selected" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Isolate" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Hide" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Unselect" })).toBeDisabled();
  });

  test("calls the corresponding viewer command and dragger APIs exactly once", () => {
    const viewer = new MockViewer();

    render(<ToolbarHarness viewer={viewer} selectedHandles={[101]} />);

    for (const [label, draggerName] of [
      ["Pan", "pan"],
      ["Orbit", "orbit"],
      ["Orbit/Pan", "orbit-pan"],
      ["Walk", "walk"],
      ["Zoom", "zoom"],
    ] as const) {
      fireEvent.click(screen.getByRole("radio", { name: label }));
      expect(viewer.setActiveDragger).toHaveBeenCalledTimes(1);
      expect(viewer.setActiveDragger).toHaveBeenLastCalledWith(draggerName);
      viewer.setActiveDragger.mockClear();
    }

    for (const [label, commandName] of [
      ["X Slice", "planeViewX"],
      ["Y Slice", "planeViewY"],
      ["Z Slice", "planeViewZ"],
      ["Clear cuts", "clearSlices"],
      ["Measure line", "measureLine"],
      ["SW", "k3DViewSW"],
      ["Top", "k3DViewTop"],
      ["Bottom", "k3DViewBottom"],
      ["Left", "k3DViewLeft"],
      ["Right", "k3DViewRight"],
      ["Front", "k3DViewFront"],
      ["Back", "k3DViewBack"],
      ["Fit", "zoomToExtents"],
      ["Fit selected", "zoomToSelected"],
      ["Isolate", "isolateSelected"],
      ["Hide", "hideSelected"],
      ["Show all", "showAll"],
      ["Unselect", "clearSelected"],
      ["Explode", "explode"],
      ["Collect", "collect"],
      ["Refresh", "regenerateAll"],
      ["Reset", "resetView"],
    ] as const) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(viewer.executeCommand).toHaveBeenCalledTimes(1);
      expect(viewer.executeCommand).toHaveBeenLastCalledWith(commandName);
      viewer.executeCommand.mockClear();
    }
  });

  test("does not render markup or preview controls", () => {
    render(<ToolbarHarness />);

    for (const label of ["Markup", "Preview", "Save", "Viewpoints"]) {
      expect(screen.queryByRole("button", { name: label })).not.toBeInTheDocument();
    }
  });

  test("reflects runtime dragger changes coming from the viewer", async () => {
    const viewer = new MockViewer();

    render(<ToolbarHarness viewer={viewer} />);

    act(() => {
      viewer.emit("changeactivedragger", "zoom");
    });

    await waitFor(() => {
      expect(screen.getByRole("radio", { name: "Zoom" })).toHaveAttribute("data-state", "on");
    });

    expect(screen.getByRole("radio", { name: "Orbit/Pan" })).toHaveAttribute("data-state", "off");
  });
});
