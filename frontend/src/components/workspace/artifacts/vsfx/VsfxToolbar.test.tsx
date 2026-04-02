import { useEffect } from "react";
import { describe, expect, test, vi } from "vitest";

import type { IViewer, ViewerEventMap } from "@/lib/vsfx-viewer/viewer-core";
import { defaultOptions } from "@/lib/vsfx-viewer/viewer-core/options/IOptions";
import { fireEvent, render, screen } from "@/test/render";

import { VsfxContextProvider, useVsfxContext } from "./context";
import { VsfxToolbar } from "./VsfxToolbar";

type RuntimeViewer = IViewer & {
  setActiveDragger: (name: string) => void;
};

class MockViewer implements RuntimeViewer {
  readonly executeCommand = vi.fn<(name: string, ...args: unknown[]) => unknown>();

  readonly setActiveDragger = vi.fn<(name: string) => void>();

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

  on<TName extends keyof ViewerEventMap>(
    _eventName: TName,
    _listener: (payload: ViewerEventMap[TName]) => void,
  ) {
    return () => undefined;
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

    for (const label of [
      "X Slice",
      "Y Slice",
      "Z Slice",
      "Clear cuts",
      "Fit",
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
});
