"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { VsfxArtifactPanelError } from "@/core/artifacts/vsfx/adapter";
import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

export type VsfxHandle = string | number;

type VsfxPanelStateInput<T> = {
  data: T | null;
  error: VsfxArtifactPanelError | null;
  loading: boolean;
};

export type VsfxSharedState = {
  activeDragger: string | null;
  cdaError: VsfxArtifactPanelError | null;
  cdaLoading: boolean;
  cdaTree: unknown | null;
  databaseLoaded: boolean;
  geometryLoaded: boolean;
  hiddenHandles: Set<VsfxHandle>;
  primaryHandle: VsfxHandle | null;
  properties: unknown | null;
  propertiesError: VsfxArtifactPanelError | null;
  propertiesLoading: boolean;
  ready: boolean;
  selectedHandles: VsfxHandle[];
  viewer: IViewer | null;
};

export type VsfxSharedActions = {
  clearHiddenHandles: () => void;
  clearSelection: () => void;
  clearSlices: () => void;
  explode: (index?: number) => void;
  hideSelected: () => void;
  isolateSelected: () => void;
  regenerateAll: () => void;
  resetForArtifact: () => void;
  resetView: () => void;
  selectHandles: (handles: VsfxHandle[]) => void;
  setCdaTreeState: (payload: VsfxPanelStateInput<unknown>) => void;
  setDatabaseLoaded: (loaded: boolean) => void;
  setGeometryLoaded: (loaded: boolean) => void;
  setHandleHidden: (handle: VsfxHandle, hidden: boolean) => void;
  setHandlesHidden: (handles: VsfxHandle[], hidden: boolean) => void;
  setPlaneView: (axis: "x" | "y" | "z") => void;
  setPropertiesState: (payload: VsfxPanelStateInput<unknown>) => void;
  setReady: (ready: boolean) => void;
  setSelectedHandles: (handles: VsfxHandle[]) => void;
  setViewer: (viewer: IViewer | null) => void;
  showAll: () => void;
  zoomToExtents: () => void;
  zoomToSelected: () => void;
};

export type VsfxContextValue = {
  actions: VsfxSharedActions;
  state: VsfxSharedState;
};

const VsfxContext = createContext<VsfxContextValue | undefined>(undefined);

type VsfxContextProviderProps = {
  artifactKey: string;
  children: ReactNode;
};

export function VsfxContextProvider({
  artifactKey,
  children,
}: VsfxContextProviderProps) {
  const detachViewerRef = useRef<() => void>(() => undefined);
  const previousArtifactKeyRef = useRef(artifactKey);
  const stateRef = useRef<VsfxSharedState>(createDefaultState());
  const viewerRef = useRef<IViewer | null>(null);
  const [state, setState] = useState<VsfxSharedState>(createDefaultState);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const updateState = useCallback(
    (updater: (currentState: VsfxSharedState) => VsfxSharedState) => {
      setState((currentState) => {
        const nextState = updater(currentState);
        stateRef.current = nextState;
        return nextState;
      });
    },
    [],
  );

  const detachViewer = useCallback(() => {
    detachViewerRef.current();
    detachViewerRef.current = () => undefined;
    viewerRef.current = null;
  }, []);

  const resetForArtifact = useCallback(() => {
    detachViewer();
    updateState(() => createDefaultState());
  }, [detachViewer, updateState]);

  const setSelectedHandles = useCallback(
    (handles: VsfxHandle[]) => {
      const nextHandles = Array.isArray(handles)
        ? handles.filter(
            (handle): handle is VsfxHandle =>
              typeof handle === "string" || typeof handle === "number",
          )
        : [];

      updateState((currentState) => ({
        ...currentState,
        primaryHandle: nextHandles[0] ?? null,
        selectedHandles: [...nextHandles],
      }));
    },
    [updateState],
  );

  const setHandleHidden = useCallback(
    (handle: VsfxHandle, hidden: boolean) => {
      updateState((currentState) => {
        const nextHiddenHandles = new Set(currentState.hiddenHandles);

        if (hidden) {
          nextHiddenHandles.add(handle);
        }
        else {
          nextHiddenHandles.delete(handle);
        }

        return {
          ...currentState,
          hiddenHandles: nextHiddenHandles,
        };
      });
    },
    [updateState],
  );

  const setHandlesHidden = useCallback(
    (handles: VsfxHandle[], hidden: boolean) => {
      if (handles.length === 0) {
        return;
      }

      updateState((currentState) => {
        const nextHiddenHandles = new Set(currentState.hiddenHandles);

        for (const handle of handles) {
          if (hidden) {
            nextHiddenHandles.add(handle);
          }
          else {
            nextHiddenHandles.delete(handle);
          }
        }

        return {
          ...currentState,
          hiddenHandles: nextHiddenHandles,
        };
      });
    },
    [updateState],
  );

  const clearHiddenHandles = useCallback(() => {
    updateState((currentState) => ({
      ...currentState,
      hiddenHandles: new Set(),
    }));
  }, [updateState]);

  const setCdaTreeState = useCallback(
    (payload: VsfxPanelStateInput<unknown>) => {
      updateState((currentState) => ({
        ...currentState,
        cdaError: payload.error,
        cdaLoading: payload.loading,
        cdaTree: payload.data,
      }));
    },
    [updateState],
  );

  const setPropertiesState = useCallback(
    (payload: VsfxPanelStateInput<unknown>) => {
      updateState((currentState) => ({
        ...currentState,
        properties: payload.data,
        propertiesError: payload.error,
        propertiesLoading: payload.loading,
      }));
    },
    [updateState],
  );

  const setReady = useCallback(
    (ready: boolean) => {
      updateState((currentState) => ({ ...currentState, ready }));
    },
    [updateState],
  );

  const setDatabaseLoaded = useCallback(
    (databaseLoaded: boolean) => {
      updateState((currentState) => ({ ...currentState, databaseLoaded }));
    },
    [updateState],
  );

  const setGeometryLoaded = useCallback(
    (geometryLoaded: boolean) => {
      updateState((currentState) => ({ ...currentState, geometryLoaded }));
    },
    [updateState],
  );

  const runViewerCommand = useCallback((commandName: string, ...args: unknown[]) => {
    viewerRef.current?.executeCommand(commandName, ...args);
  }, []);

  const setViewer = useCallback(
    (viewer: IViewer | null) => {
      detachViewer();
      viewerRef.current = viewer;

      if (!viewer) {
        updateState((currentState) => ({
          ...currentState,
          ready: false,
          viewer: null,
        }));
        return;
      }

      const unsubscribeListeners = [
        viewer.on("changeactivedragger", (activeDragger) => {
          updateState((currentState) => ({
            ...currentState,
            activeDragger,
          }));
        }),
        viewer.on("select", (handles) => {
          setSelectedHandles(handles);
        }),
        viewer.on("clear", () => {
          setSelectedHandles([]);
        }),
        viewer.on("databasechunk", () => {
          updateState((currentState) => ({
            ...currentState,
            databaseLoaded: true,
            geometryLoaded: false,
          }));
        }),
        viewer.on("geometryend", () => {
          updateState((currentState) => ({
            ...currentState,
            geometryLoaded: true,
          }));
        }),
        viewer.on("geometryerror", () => {
          updateState((currentState) => ({
            ...currentState,
            geometryLoaded: false,
          }));
        }),
      ];

      detachViewerRef.current = () => {
        for (const unsubscribe of unsubscribeListeners) {
          unsubscribe();
        }
      };

      updateState((currentState) => ({
        ...currentState,
        activeDragger: "orbit-pan",
        ready: true,
        viewer,
      }));
    },
    [detachViewer, setSelectedHandles, updateState],
  );

  const selectHandles = useCallback(
    (handles: VsfxHandle[]) => {
      if (viewerRef.current) {
        runViewerCommand("setSelected", handles);
        return;
      }

      setSelectedHandles(handles);
    },
    [runViewerCommand, setSelectedHandles],
  );

  const clearSelection = useCallback(() => {
    if (viewerRef.current) {
      runViewerCommand("clearSelected");
      return;
    }

    setSelectedHandles([]);
  }, [runViewerCommand, setSelectedHandles]);

  const hideSelected = useCallback(() => {
    const handles = stateRef.current.selectedHandles;
    setHandlesHidden(handles, true);
    runViewerCommand("hideSelected");
  }, [runViewerCommand, setHandlesHidden]);

  const isolateSelected = useCallback(() => {
    const selectedHandles = stateRef.current.selectedHandles;

    if (selectedHandles.length === 0) {
      return;
    }

    const selectedHandleKeys = new Set(selectedHandles.map((handle) => String(handle)));
    const nextHiddenHandles = new Set<VsfxHandle>();
    const cdaTree = stateRef.current.cdaTree;

    if (typeof cdaTree === "object" && cdaTree !== null && "nodes" in cdaTree) {
      for (const handle of collectTreeHandles((cdaTree as { nodes?: unknown }).nodes)) {
        if (!selectedHandleKeys.has(String(handle))) {
          nextHiddenHandles.add(handle);
        }
      }
    }

    updateState((currentState) => ({
      ...currentState,
      hiddenHandles: nextHiddenHandles,
    }));
    runViewerCommand("isolateSelected");
  }, [runViewerCommand, updateState]);

  const showAll = useCallback(() => {
    clearHiddenHandles();
    runViewerCommand("showAll");
  }, [clearHiddenHandles, runViewerCommand]);

  const zoomToSelected = useCallback(() => {
    runViewerCommand("zoomToSelected");
  }, [runViewerCommand]);

  const zoomToExtents = useCallback(() => {
    runViewerCommand("zoomToExtents");
  }, [runViewerCommand]);

  const resetView = useCallback(() => {
    runViewerCommand("resetView");
  }, [runViewerCommand]);

  const regenerateAll = useCallback(() => {
    runViewerCommand("regenerateAll");
  }, [runViewerCommand]);

  const clearSlices = useCallback(() => {
    runViewerCommand("clearSlices");
  }, [runViewerCommand]);

  const explode = useCallback(
    (index?: number) => {
      runViewerCommand("explode", index);
    },
    [runViewerCommand],
  );

  const setPlaneView = useCallback(
    (axis: "x" | "y" | "z") => {
      if (axis === "x") {
        runViewerCommand("planeViewX");
        return;
      }

      if (axis === "y") {
        runViewerCommand("planeViewY");
        return;
      }

      runViewerCommand("planeViewZ");
    },
    [runViewerCommand],
  );

  useEffect(() => {
    if (previousArtifactKeyRef.current === artifactKey) {
      return;
    }

    previousArtifactKeyRef.current = artifactKey;
    resetForArtifact();
  }, [artifactKey, resetForArtifact]);

  useEffect(() => {
    return () => {
      detachViewer();
    };
  }, [detachViewer]);

  const actions = useMemo<VsfxSharedActions>(
    () => ({
      clearHiddenHandles,
      clearSelection,
      clearSlices,
      explode,
      hideSelected,
      isolateSelected,
      regenerateAll,
      resetForArtifact,
      resetView,
      selectHandles,
      setCdaTreeState,
      setDatabaseLoaded,
      setGeometryLoaded,
      setHandleHidden,
      setHandlesHidden,
      setPlaneView,
      setPropertiesState,
      setReady,
      setSelectedHandles,
      setViewer,
      showAll,
      zoomToExtents,
      zoomToSelected,
    }),
    [
      clearHiddenHandles,
      clearSelection,
      clearSlices,
      explode,
      hideSelected,
      isolateSelected,
      regenerateAll,
      resetForArtifact,
      resetView,
      selectHandles,
      setCdaTreeState,
      setDatabaseLoaded,
      setGeometryLoaded,
      setHandleHidden,
      setHandlesHidden,
      setPlaneView,
      setPropertiesState,
      setReady,
      setSelectedHandles,
      setViewer,
      showAll,
      zoomToExtents,
      zoomToSelected,
    ],
  );

  const value = useMemo<VsfxContextValue>(
    () => ({
      actions,
      state,
    }),
    [actions, state],
  );

  return <VsfxContext.Provider value={value}>{children}</VsfxContext.Provider>;
}

export function useVsfxContext() {
  const context = useContext(VsfxContext);

  if (!context) {
    throw new Error("useVsfxContext must be used within a VsfxContextProvider");
  }

  return context;
}

function createDefaultState(): VsfxSharedState {
  return {
    activeDragger: null,
    cdaError: null,
    cdaLoading: false,
    cdaTree: null,
    databaseLoaded: false,
    geometryLoaded: false,
    hiddenHandles: new Set(),
    primaryHandle: null,
    properties: null,
    propertiesError: null,
    propertiesLoading: false,
    ready: false,
    selectedHandles: [],
    viewer: null,
  };
}

function collectTreeHandles(input: unknown): VsfxHandle[] {
  if (!Array.isArray(input)) {
    return [];
  }

  return input.flatMap((node) => collectTreeNodeHandles(node));
}

function collectTreeNodeHandles(input: unknown): VsfxHandle[] {
  if (typeof input !== "object" || input === null) {
    return [];
  }

  const record = input as {
    children?: unknown;
    handle?: unknown;
  };
  const currentHandle =
    typeof record.handle === "string" || typeof record.handle === "number"
      ? String(record.handle) === "0"
        ? []
        : [record.handle]
      : [];
  const childHandles = Array.isArray(record.children)
    ? record.children.flatMap((child) => collectTreeNodeHandles(child))
    : [];

  return [...currentHandle, ...childHandles];
}
