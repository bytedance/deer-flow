"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  createInitialVsfxArtifactBundle,
  createVsfxArtifactBundleRequest,
  isVsfxArtifactAbortError,
  type VsfxArtifactBundle,
  type VsfxArtifactPanelError,
} from "@/core/artifacts/vsfx/adapter";
import { cn } from "@/lib/utils";
import { VisualizeViewer } from "@/lib/vsfx-viewer/components/VisualizeViewer";

import { VsfxContextProvider, useVsfxContext } from "./context";
import { VsfxPropertiesWindow } from "./properties/VsfxPropertiesWindow";
import { VsfxTreeWindow } from "./tree/VsfxTreeWindow";
import { VsfxToolbar } from "./VsfxToolbar";

type VsfxArtifactViewerProps = {
  artifacts: string[];
  className?: string;
  filepath: string;
  isMock?: boolean;
  threadId: string;
};

export function VsfxArtifactViewer({
  artifacts,
  className,
  filepath,
  isMock = false,
  threadId,
}: VsfxArtifactViewerProps) {
  const requestIdRef = useRef(0);
  const viewerContainerRef = useRef<HTMLDivElement | null>(null);
  const initialBundle = useMemo(
    () => createInitialVsfxArtifactBundle(threadId, filepath, isMock),
    [filepath, isMock, threadId],
  );
  const [bundle, setBundle] = useState<VsfxArtifactBundle>(initialBundle);
  const [primaryData, setPrimaryData] = useState<ArrayBuffer | null>(null);
  const [primaryLoading, setPrimaryLoading] = useState(initialBundle.loading);
  const [primaryError, setPrimaryError] = useState<VsfxArtifactPanelError | null>(
    initialBundle.errors.primary,
  );
  const [artifactVersion, setArtifactVersion] = useState(0);

  useEffect(() => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;

    const request = createVsfxArtifactBundleRequest(
      threadId,
      filepath,
      artifacts,
      isMock,
    );
    const primaryController = new AbortController();

    setBundle(request.initial);
    setPrimaryData(null);
    setPrimaryError(request.initial.errors.primary);
    setPrimaryLoading(Boolean(request.initial.primaryUrl) && !request.initial.errors.primary);

    const load = async () => {
      const loadPrimaryArtifact = async () => {
        if (!request.initial.primaryUrl || request.initial.errors.primary) {
          if (requestIdRef.current === requestId) {
            setPrimaryError(request.initial.errors.primary);
            setPrimaryLoading(false);
          }
          return;
        }

        const response = await fetch(request.initial.primaryUrl, {
          signal: primaryController.signal,
        });

        if (!response.ok) {
          throw new Error(`Failed to load primary VSFX artifact: ${filepath}`);
        }

        const nextPrimaryData = await response.arrayBuffer();

        if (requestIdRef.current !== requestId) {
          return;
        }

        setPrimaryData(nextPrimaryData);
        setArtifactVersion((current) => current + 1);
        setPrimaryLoading(false);
      };

      const loadSiblingMetadata = async () => {
        const nextBundle = await request.promise;

        if (requestIdRef.current !== requestId) {
          return;
        }

        setBundle(nextBundle);
      };

      try {
        await Promise.all([
          loadPrimaryArtifact(),
          loadSiblingMetadata(),
        ]);
      }
      catch (error) {
        if (requestIdRef.current !== requestId || isVsfxArtifactAbortError(error)) {
          return;
        }

        const nextPrimaryError = normalizePrimaryError(error, filepath);
        setPrimaryError(nextPrimaryError);
        setPrimaryLoading(false);
        setBundle((currentBundle) => ({
          ...currentBundle,
          loading: false,
          errors: {
            ...currentBundle.errors,
            primary: nextPrimaryError,
          },
        }));
      }
    };

    void load();

    return () => {
      request.cancel();
      primaryController.abort();
    };
  }, [artifacts, filepath, isMock, threadId]);

  const isLoading = bundle.loading || primaryLoading;
  const fatalError = primaryError ?? bundle.errors.primary;

  return (
      <div
        className={cn(
          "bg-background relative flex h-full min-h-64 w-full overflow-hidden rounded-md border",
          className,
        )}
        data-testid="vsfx-viewer-root"
        ref={viewerContainerRef}
      >
      {isLoading ? (
        <div
          className="text-muted-foreground flex h-full w-full items-center justify-center px-6 text-sm"
          data-testid="vsfx-loading"
        >
          Preparing VSFX artifact…
        </div>
      ) : fatalError ? (
        <div
          className="text-destructive flex h-full w-full items-center justify-center px-6 text-center text-sm"
          data-testid="vsfx-error"
          role="alert"
        >
          {fatalError.message}
        </div>
      ) : primaryData ? (
        <VsfxArtifactViewerRuntime
          artifactKey={`${filepath}:${artifactVersion}`}
          cdaTree={bundle.cdaTree}
          cdaTreeError={bundle.errors.cdaTree}
          filepath={filepath}
          onPrimaryError={(error) => {
            setPrimaryError(normalizePrimaryError(error, filepath));
          }}
          primaryData={primaryData}
          properties={bundle.properties}
          propertiesError={bundle.errors.properties}
          viewerContainerElement={viewerContainerRef.current}
        />
      ) : (
        <div
          className="text-destructive flex h-full w-full items-center justify-center px-6 text-center text-sm"
          data-testid="vsfx-error"
          role="alert"
        >
          Unable to prepare the VSFX artifact.
        </div>
      )}
    </div>
  );
}

type VsfxArtifactViewerRuntimeProps = {
  artifactKey: string;
  cdaTree: unknown | null;
  cdaTreeError: VsfxArtifactPanelError | null;
  filepath: string;
  onPrimaryError: (error: unknown) => void;
  primaryData: ArrayBuffer;
  properties: unknown | null;
  propertiesError: VsfxArtifactPanelError | null;
  viewerContainerElement: HTMLDivElement | null;
};

function VsfxArtifactViewerRuntime(props: VsfxArtifactViewerRuntimeProps) {
  return (
    <VsfxContextProvider artifactKey={props.artifactKey}>
      <VsfxArtifactViewerSurface {...props} />
    </VsfxContextProvider>
  );
}

function VsfxArtifactViewerSurface({
  cdaTree,
  cdaTreeError,
  filepath,
  onPrimaryError,
  primaryData,
  properties,
  propertiesError,
  viewerContainerElement,
}: VsfxArtifactViewerRuntimeProps) {
  const { actions, state } = useVsfxContext();
  const openedArtifactRef = useRef<{
    data: ArrayBuffer;
    filepath: string;
  } | null>(null);
  const [treeWindowState, setTreeWindowState] = useState(() => createInitialFloatingWindowState());
  const [propertiesWindowState, setPropertiesWindowState] = useState(() => createInitialFloatingWindowState());

  useEffect(() => {
    actions.setCdaTreeState({
      data: cdaTree,
      error: cdaTreeError,
      loading: false,
    });
    actions.setPropertiesState({
      data: properties,
      error: propertiesError,
      loading: false,
    });
  }, [actions, cdaTree, cdaTreeError, properties, propertiesError]);

  useEffect(() => {
    const viewer = state.viewer;

    if (!viewer) {
      openedArtifactRef.current = null;
      return;
    }

    if (
      openedArtifactRef.current?.filepath === filepath
      && openedArtifactRef.current.data === primaryData
    ) {
      return;
    }

    let active = true;
    openedArtifactRef.current = { data: primaryData, filepath };

    const openArtifact = async () => {
      try {
        await viewer.open({
          data: primaryData,
          filename: getFilename(filepath),
        });
      } catch (error) {
        if (!active) {
          return;
        }

        openedArtifactRef.current = null;
        onPrimaryError(error);
      }
    };

    void openArtifact();

    return () => {
      active = false;
    };
  }, [filepath, onPrimaryError, primaryData, state.viewer]);

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden">
      <div className="border-b p-2">
        <VsfxToolbar />
      </div>
      <div className="relative min-h-0 flex-1 overflow-hidden">
        <VisualizeViewer
          className="size-full"
          onError={onPrimaryError}
          onReady={actions.setViewer}
        />
        <VsfxTreeWindow
          containerElement={viewerContainerElement}
          minimized={treeWindowState.minimized}
          offset={treeWindowState.offset}
          onOffsetChange={(offset) => {
            setTreeWindowState((current) => ({ ...current, offset }));
          }}
          onToggleMinimized={() => {
            setTreeWindowState((current) => ({
              ...current,
              minimized: !current.minimized,
            }));
          }}
        />
        <VsfxPropertiesWindow
          containerElement={viewerContainerElement}
          minimized={propertiesWindowState.minimized}
          offset={propertiesWindowState.offset}
          onOffsetChange={(offset) => {
            setPropertiesWindowState((current) => ({ ...current, offset }));
          }}
          onToggleMinimized={() => {
            setPropertiesWindowState((current) => ({
              ...current,
              minimized: !current.minimized,
            }));
          }}
        />
      </div>
    </div>
  );
}

function createInitialFloatingWindowState() {
  return {
    minimized: true,
    offset: { x: 0, y: 0 },
  };
}

function createLoadFailedError(filepath: string, message: string): VsfxArtifactPanelError {
  return {
    code: "load-failed",
    filepath,
    message,
  };
}

function getFilename(filepath: string) {
  const lastSlashIndex = filepath.lastIndexOf("/");

  return lastSlashIndex === -1 ? filepath : filepath.slice(lastSlashIndex + 1);
}

function normalizePrimaryError(error: unknown, filepath: string): VsfxArtifactPanelError {
  if (isVsfxArtifactPanelError(error)) {
    return error;
  }

  return createLoadFailedError(
    filepath,
    error instanceof Error ? error.message : `Failed to load primary VSFX artifact: ${filepath}`,
  );
}

function isVsfxArtifactPanelError(error: unknown): error is VsfxArtifactPanelError {
  return typeof error === "object" && error !== null && "code" in error && "message" in error;
}
