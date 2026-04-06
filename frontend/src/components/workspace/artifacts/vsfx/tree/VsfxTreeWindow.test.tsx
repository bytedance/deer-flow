import { useEffect } from "react";
import { describe, expect, test, vi } from "vitest";

import type { IViewer, ViewerInteractionEventMap } from "@/lib/vsfx-viewer/viewer-core";
import { defaultOptions } from "@/lib/vsfx-viewer/viewer-core/options/IOptions";
import { fireEvent, render, screen, waitFor } from "@/test/render";

import { VsfxContextProvider, useVsfxContext } from "../context";

import { VsfxTreeWindow } from "./VsfxTreeWindow";

class MockViewer implements IViewer {
  readonly executeCommand = vi.fn<(name: string, ...args: unknown[]) => unknown>();

  readonly update = vi.fn();

  readonly visViewer = {
    getEntityByOriginalHandle: vi.fn((handle: string) => ({
      delete: vi.fn(),
      getOwnerModel: () => ({
        delete: vi.fn(),
        hide: ownerHideSpy,
        isNull: () => false,
        unHide: ownerShowSpy,
      }),
      isNull: () => false,
      originalHandle: handle,
    })),
  };

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

  getVisualizeViewer() {
    return this.visViewer;
  }

  on<TName extends keyof ViewerInteractionEventMap>(
    _eventName: TName,
    _listener: (payload: ViewerInteractionEventMap[TName]) => void,
  ) {
    return () => undefined;
  }

  off<TName extends keyof ViewerInteractionEventMap>(
    _eventName: TName,
    _listener: (payload: ViewerInteractionEventMap[TName]) => void,
  ) {
    void 0;
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
}

const ownerHideSpy = vi.fn();
const ownerShowSpy = vi.fn();
const EMPTY_HANDLES: Array<string | number> = [];

type HarnessProps = {
  cdaError?: { code: "invalid-json" | "load-failed" | "missing"; filepath: string; message: string } | null;
  cdaLoading?: boolean;
  cdaTree?: unknown;
  hiddenHandles?: Array<string | number>;
  selectedHandles?: Array<string | number>;
  viewer?: IViewer | null;
};

function StateHarness({
  cdaError = null,
  cdaLoading = false,
  cdaTree = null,
  hiddenHandles = EMPTY_HANDLES,
  selectedHandles = EMPTY_HANDLES,
  viewer = null,
}: HarnessProps) {
  const { actions } = useVsfxContext();

  useEffect(() => {
    actions.setViewer(viewer);
    actions.clearHiddenHandles();
    actions.setSelectedHandles(selectedHandles);
    actions.setHandlesHidden(hiddenHandles, true);
    actions.setCdaTreeState({
      data: cdaTree,
      error: cdaError,
      loading: cdaLoading,
    });
  }, [actions, cdaError, cdaLoading, cdaTree, hiddenHandles, selectedHandles, viewer]);

  return null;
}

function renderTreeWindow(props?: HarnessProps) {
  return render(
    <VsfxContextProvider artifactKey="assembly-a">
      <div data-testid="vsfx-viewer-root">Viewer root</div>
      <StateHarness {...props} />
      <VsfxTreeWindow
        containerElement={null}
        minimized={false}
        offset={{ x: 0, y: 0 }}
        onOffsetChange={() => undefined}
        onToggleMinimized={() => undefined}
      />
    </VsfxContextProvider>,
  );
}

describe("VsfxTreeWindow", () => {
  test("renders an unavailable state without touching the viewer shell", async () => {
    renderTreeWindow({
      cdaError: {
        code: "missing",
        filepath: "/artifacts/assembly-a.cda.json",
        message: "Construct tree metadata is unavailable.",
      },
    });

    expect(await screen.findByTestId("vsfx-tree-window")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Construct tree metadata is unavailable.");
    expect(screen.getByTestId("vsfx-viewer-root")).toBeInTheDocument();
  });

  test("renders loading and empty states inside the floating shell", async () => {
    const { rerender } = render(
      <VsfxContextProvider artifactKey="assembly-a">
        <div data-testid="vsfx-viewer-root">Viewer root</div>
        <StateHarness cdaLoading />
        <VsfxTreeWindow
          containerElement={null}
          minimized={false}
          offset={{ x: 0, y: 0 }}
          onOffsetChange={() => undefined}
          onToggleMinimized={() => undefined}
        />
      </VsfxContextProvider>,
    );

    expect(await screen.findByText("Loading construct tree…")).toBeInTheDocument();

    rerender(
      <VsfxContextProvider artifactKey="assembly-a">
        <div data-testid="vsfx-viewer-root">Viewer root</div>
        <StateHarness cdaTree={{ nodes: [] }} />
        <VsfxTreeWindow
          containerElement={null}
          minimized={false}
          offset={{ x: 0, y: 0 }}
          onOffsetChange={() => undefined}
          onToggleMinimized={() => undefined}
        />
      </VsfxContextProvider>,
    );

    expect(await screen.findByText("No construct tree data is available for this artifact."))
      .toBeInTheDocument();
  });

  test("mutates hidden-handle state and updates the viewer once per hide-show action", async () => {
    ownerHideSpy.mockReset();
    ownerShowSpy.mockReset();
    const viewer = new MockViewer();

    renderTreeWindow({
      cdaTree: {
        nodes: [
          {
            children: [],
            handle: 42,
            name: "Bolt",
          },
        ],
      },
      viewer: viewer as unknown as IViewer,
    });

    fireEvent.click(await screen.findByRole("button", { name: "Hide Bolt" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Show Bolt" })).toBeInTheDocument();
    });

    expect(ownerHideSpy).toHaveBeenCalledTimes(1);
    expect(viewer.update).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Show Bolt" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Hide Bolt" })).toBeInTheDocument();
    });

    expect(ownerShowSpy).toHaveBeenCalledTimes(1);
    expect(viewer.update).toHaveBeenCalledTimes(2);
  });
});
