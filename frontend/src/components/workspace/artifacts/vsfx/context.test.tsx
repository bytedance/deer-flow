import { useEffect } from "react";
import { describe, expect, test, vi } from "vitest";

import type { VsfxArtifactPanelError } from "@/core/artifacts/vsfx/adapter";
import type { IViewer, ViewerEventMap } from "@/lib/vsfx-viewer/viewer-core";
import { defaultOptions } from "@/lib/vsfx-viewer/viewer-core/options/IOptions";
import { act, render, waitFor } from "@/test/render";

import {
  VsfxContextProvider,
  useVsfxContext,
  type VsfxContextValue,
} from "./context";

type VsfxContextSnapshot = {
  cdaErrorCode: string | null;
  cdaLoading: boolean;
  databaseLoaded: boolean;
  geometryLoaded: boolean;
  hasViewer: boolean;
  hiddenHandles: Array<string | number>;
  primaryHandle: string | number | null;
  propertiesErrorCode: string | null;
  propertiesLoading: boolean;
  ready: boolean;
  selectedHandles: Array<string | number>;
};

class MockViewer implements IViewer {
  readonly executeCommand = vi.fn<(name: string, ...args: unknown[]) => unknown>();

  private readonly listeners = new Map<
    keyof ViewerEventMap,
    Set<(payload: ViewerEventMap[keyof ViewerEventMap]) => void>
  >();

  clearSlices() {
    void 0;
  }

  dispose() {
    void 0;
  }

  emit<TName extends keyof ViewerEventMap>(
    eventName: TName,
    payload: ViewerEventMap[TName],
  ) {
    const listeners = this.listeners.get(eventName);

    if (!listeners) {
      return;
    }

    for (const listener of listeners) {
      listener(payload);
    }
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
    eventName: TName,
    listener: (payload: ViewerEventMap[TName]) => void,
  ) {
    const existing = this.listeners.get(eventName) ?? new Set();
    existing.add(listener as (payload: ViewerEventMap[keyof ViewerEventMap]) => void);
    this.listeners.set(eventName, existing);

    return () => {
      existing.delete(
        listener as (payload: ViewerEventMap[keyof ViewerEventMap]) => void,
      );
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

type ProbeProps = {
  onActionsReady?: (actions: VsfxContextValue["actions"]) => void;
  onStateChange?: (snapshot: VsfxContextSnapshot) => void;
};

function Probe({ onActionsReady, onStateChange }: ProbeProps) {
  const context = useVsfxContext();

  useEffect(() => {
    onActionsReady?.(context.actions);
  }, [context.actions, onActionsReady]);

  useEffect(() => {
    onStateChange?.(createSnapshot(context));
  }, [context, onStateChange]);

  return null;
}

function createSnapshot(context: VsfxContextValue): VsfxContextSnapshot {
  return {
    cdaErrorCode: context.state.cdaError?.code ?? null,
    cdaLoading: context.state.cdaLoading,
    databaseLoaded: context.state.databaseLoaded,
    geometryLoaded: context.state.geometryLoaded,
    hasViewer: context.state.viewer !== null,
    hiddenHandles: Array.from(context.state.hiddenHandles),
    primaryHandle: context.state.primaryHandle,
    propertiesErrorCode: context.state.propertiesError?.code ?? null,
    propertiesLoading: context.state.propertiesLoading,
    ready: context.state.ready,
    selectedHandles: context.state.selectedHandles,
  };
}

function createPanelError(filepath: string, code: VsfxArtifactPanelError["code"]): VsfxArtifactPanelError {
  return {
    code,
    filepath,
    message: `${code}:${filepath}`,
  };
}

describe("VsfxContextProvider", () => {
  test("updates shared selection state exactly once for viewer select and clear events", async () => {
    const viewer = new MockViewer();
    let actions!: VsfxContextValue["actions"];
    const snapshotSpy = vi.fn<(snapshot: VsfxContextSnapshot) => void>();

    render(
      <VsfxContextProvider artifactKey="assembly-a">
        <Probe
          onActionsReady={(nextActions) => {
            actions = nextActions;
          }}
          onStateChange={snapshotSpy}
        />
      </VsfxContextProvider>,
    );

    act(() => {
      actions.setViewer(viewer);
    });

    snapshotSpy.mockClear();

    act(() => {
      viewer.emit("select", [101, 202]);
    });

    await waitFor(() => {
      expect(snapshotSpy).toHaveBeenCalledTimes(1);
    });

    expect(snapshotSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({
        primaryHandle: 101,
        selectedHandles: [101, 202],
      }),
    );

    snapshotSpy.mockClear();

    act(() => {
      viewer.emit("clear", undefined);
    });

    await waitFor(() => {
      expect(snapshotSpy).toHaveBeenCalledTimes(1);
    });

    expect(snapshotSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({
        primaryHandle: null,
        selectedHandles: [],
      }),
    );
  });

  test("tracks viewer readiness and lifecycle flags from bridge events", async () => {
    const viewer = new MockViewer();
    let actions!: VsfxContextValue["actions"];
    let latestSnapshot: VsfxContextSnapshot | undefined;

    render(
      <VsfxContextProvider artifactKey="assembly-a">
        <Probe
          onActionsReady={(nextActions) => {
            actions = nextActions;
          }}
          onStateChange={(snapshot) => {
            latestSnapshot = snapshot;
          }}
        />
      </VsfxContextProvider>,
    );

    act(() => {
      actions.setViewer(viewer);
    });

    await waitFor(() => {
      expect(latestSnapshot).toMatchObject({
        databaseLoaded: false,
        geometryLoaded: false,
        hasViewer: true,
        ready: true,
      });
    });

    act(() => {
      viewer.emit("databasechunk", {
        data: new Uint8Array([1, 2, 3]).buffer,
        filename: "assembly-a.vsfx",
      });
    });

    await waitFor(() => {
      expect(latestSnapshot).toMatchObject({ databaseLoaded: true, geometryLoaded: false });
    });

    act(() => {
      viewer.emit("geometryend", { filename: "assembly-a.vsfx" });
    });

    await waitFor(() => {
      expect(latestSnapshot).toMatchObject({ databaseLoaded: true, geometryLoaded: true });
    });

    act(() => {
      viewer.emit("geometryerror", {
        error: new Error("geometry failed"),
        filename: "assembly-a.vsfx",
      });
    });

    await waitFor(() => {
      expect(latestSnapshot).toMatchObject({ databaseLoaded: true, geometryLoaded: false });
    });
  });

  test("centralizes hidden-handle and panel mutations in context actions", async () => {
    let actions!: VsfxContextValue["actions"];
    let latestSnapshot: VsfxContextSnapshot | undefined;

    render(
      <VsfxContextProvider artifactKey="assembly-a">
        <Probe
          onActionsReady={(nextActions) => {
            actions = nextActions;
          }}
          onStateChange={(snapshot) => {
            latestSnapshot = snapshot;
          }}
        />
      </VsfxContextProvider>,
    );

    act(() => {
      actions.setHandlesHidden([11, 22], true);
      actions.setHandleHidden(11, false);
      actions.setCdaTreeState({
        data: { nodes: [{ handle: 22 }] },
        error: createPanelError("/artifacts/assembly-a.cda.json", "missing"),
        loading: false,
      });
      actions.setPropertiesState({
        data: { byHandle: { 22: { Name: "Bolt" } } },
        error: createPanelError("/artifacts/assembly-a.Properties.json", "invalid-json"),
        loading: true,
      });
    });

    await waitFor(() => {
      expect(latestSnapshot).toMatchObject({
        cdaErrorCode: "missing",
        cdaLoading: false,
        hiddenHandles: [22],
        propertiesErrorCode: "invalid-json",
        propertiesLoading: true,
      });
    });

    act(() => {
      actions.clearHiddenHandles();
    });

    await waitFor(() => {
      expect(latestSnapshot).toMatchObject({ hiddenHandles: [] });
    });
  });

  test("resets model-scoped state on artifact replacement", async () => {
    const viewer = new MockViewer();
    let actions!: VsfxContextValue["actions"];
    let latestSnapshot: VsfxContextSnapshot | undefined;

    const { rerender } = render(
      <VsfxContextProvider artifactKey="assembly-a">
        <Probe
          onActionsReady={(nextActions) => {
            actions = nextActions;
          }}
          onStateChange={(snapshot) => {
            latestSnapshot = snapshot;
          }}
        />
      </VsfxContextProvider>,
    );

    act(() => {
      actions.setViewer(viewer);
      actions.setHandlesHidden([101], true);
      actions.setCdaTreeState({
        data: { nodes: [{ handle: 101 }] },
        error: null,
        loading: false,
      });
      actions.setPropertiesState({
        data: { byHandle: { 101: { Name: "Bracket" } } },
        error: null,
        loading: false,
      });
      viewer.emit("databasechunk", {
        data: new Uint8Array([1]).buffer,
        filename: "assembly-a.vsfx",
      });
      viewer.emit("geometryend", { filename: "assembly-a.vsfx" });
      viewer.emit("select", [101]);
    });

    await waitFor(() => {
      expect(latestSnapshot).toMatchObject({
        cdaLoading: false,
        databaseLoaded: true,
        geometryLoaded: true,
        hasViewer: true,
        hiddenHandles: [101],
        primaryHandle: 101,
        ready: true,
        selectedHandles: [101],
      });
    });

    rerender(
      <VsfxContextProvider artifactKey="assembly-b">
        <Probe
          onActionsReady={(nextActions) => {
            actions = nextActions;
          }}
          onStateChange={(snapshot) => {
            latestSnapshot = snapshot;
          }}
        />
      </VsfxContextProvider>,
    );

    await waitFor(() => {
      expect(latestSnapshot).toMatchObject({
        cdaErrorCode: null,
        cdaLoading: false,
        databaseLoaded: false,
        geometryLoaded: false,
        hasViewer: false,
        hiddenHandles: [],
        primaryHandle: null,
        propertiesErrorCode: null,
        propertiesLoading: false,
        ready: false,
        selectedHandles: [],
      });
    });
  });
});
