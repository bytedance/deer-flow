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
      try {
        const nextBundle = await request.promise;

        if (requestIdRef.current !== requestId) {
          return;
        }

        setBundle(nextBundle);

        if (!nextBundle.primaryUrl || nextBundle.errors.primary) {
          setPrimaryError(nextBundle.errors.primary);
          setPrimaryLoading(false);
          return;
        }

        const response = await fetch(nextBundle.primaryUrl, {
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
        setPrimaryLoading(false);
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
          cdaTree={bundle.cdaTree}
          cdaTreeError={bundle.errors.cdaTree}
          filepath={filepath}
          onPrimaryError={(error) => {
            setPrimaryError(normalizePrimaryError(error, filepath));
          }}
          primaryData={primaryData}
          properties={bundle.properties}
          propertiesError={bundle.errors.properties}
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
  cdaTree: unknown | null;
  cdaTreeError: VsfxArtifactPanelError | null;
  filepath: string;
  onPrimaryError: (error: unknown) => void;
  primaryData: ArrayBuffer;
  properties: unknown | null;
  propertiesError: VsfxArtifactPanelError | null;
};

function VsfxArtifactViewerRuntime(props: VsfxArtifactViewerRuntimeProps) {
  return (
    <VsfxContextProvider artifactKey={props.filepath}>
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
}: VsfxArtifactViewerRuntimeProps) {
  const { actions } = useVsfxContext();

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

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden">
      <div className="border-b p-2">
        <VsfxToolbar />
      </div>
      <div className="relative min-h-0 flex-1 overflow-hidden">
        <VisualizeViewer
          className="size-full"
          data={primaryData}
          filename={getFilename(filepath)}
          onError={onPrimaryError}
          onReady={actions.setViewer}
        />
        <VsfxTreeWindow />
        <VsfxPropertiesWindow />
      </div>
    </div>
  );
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
