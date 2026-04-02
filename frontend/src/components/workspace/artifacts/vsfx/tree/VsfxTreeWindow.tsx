"use client";

import { useCallback, useMemo } from "react";

import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { useVsfxContext, type VsfxHandle } from "../context";
import { VsfxFloatingWindow } from "../VsfxFloatingWindow";

import { VsfxTreeView, type VsfxTreeNodeData } from "./VsfxTreeView";

export function VsfxTreeWindow() {
  const { actions, state } = useVsfxContext();
  const treeNodes = useMemo(() => normalizeTreeNodes(state.cdaTree), [state.cdaTree]);

  const handleToggleVisibility = useCallback(
    (handles: Array<string | number>, hidden: boolean) => {
      const normalizedHandles = Array.from(
        new Set(handles.filter((handle) => handle != null && String(handle) !== "0")),
      );

      if (normalizedHandles.length === 0) {
        return;
      }

      const processedHandles = mutateViewerVisibility(state.viewer, normalizedHandles, hidden);
      actions.setHandlesHidden(processedHandles.length > 0 ? processedHandles : normalizedHandles, hidden);
    },
    [actions, state.viewer],
  );

  let content: React.ReactNode;

  if (state.cdaLoading) {
    content = (
      <div className="text-muted-foreground flex h-full items-center justify-center px-4 text-sm">
        Loading construct tree…
      </div>
    );
  }
  else if (state.cdaError) {
    content = (
      <div
        className="text-destructive flex h-full items-center justify-center px-4 text-center text-sm"
        role="alert"
      >
        {state.cdaError.message}
      </div>
    );
  }
  else if (treeNodes.length === 0) {
    content = (
      <div className="text-muted-foreground flex h-full items-center justify-center px-4 text-center text-sm">
        No construct tree data is available for this artifact.
      </div>
    );
  }
  else {
    content = (
      <VsfxTreeView
        hiddenHandles={state.hiddenHandles}
        nodes={treeNodes}
        onSelectHandles={actions.selectHandles}
        onToggleVisibility={handleToggleVisibility}
        onZoomToSelection={actions.zoomToSelected}
        selectedHandles={state.selectedHandles}
      />
    );
  }

  return (
    <VsfxFloatingWindow
      className="left-4 right-auto"
      contentClassName="min-h-0 flex-1"
      data-testid="vsfx-tree-window"
      description="Select parts, zoom to them, and toggle their visibility."
      title="Construct tree"
    >
      {content}
    </VsfxFloatingWindow>
  );
}

type VisualizeEntity = {
  delete?: () => void;
  getOwnerModel?: () => VisualizeOwnerModel | null;
  isNull?: () => boolean;
};

type VisualizeOwnerModel = {
  delete?: () => void;
  hide?: (entity: VisualizeEntity, hidden: boolean) => void;
  isNull?: () => boolean;
  unHide?: (entity: VisualizeEntity, includeNested: boolean, redraw: boolean) => void;
};

type VisualizeViewerLike = {
  getEntityByOriginalHandle?: (handle: string) => VisualizeEntity | null;
};

function mutateViewerVisibility(
  viewer: IViewer | null,
  handles: VsfxHandle[],
  hidden: boolean,
) {
  const visualizeViewer = getVisualizeViewer(viewer);

  if (!visualizeViewer) {
    return [];
  }

  const processedHandles: VsfxHandle[] = [];

  for (const handle of handles) {
    const entity = visualizeViewer.getEntityByOriginalHandle?.(String(handle));

    if (!entity || entity.isNull?.()) {
      continue;
    }

    const ownerModel = entity.getOwnerModel?.();

    if (!ownerModel || ownerModel.isNull?.()) {
      entity.delete?.();
      continue;
    }

    if (hidden) {
      ownerModel.hide?.(entity, true);
    }
    else {
      ownerModel.unHide?.(entity, false, true);
    }

    processedHandles.push(handle);
    entity.delete?.();
    ownerModel.delete?.();
  }

  if (processedHandles.length > 0) {
    viewer?.update();
  }

  return processedHandles;
}

function getVisualizeViewer(viewer: IViewer | null) {
  if (!viewer || !("getVisualizeViewer" in viewer)) {
    return null;
  }

  const visualizeViewer = viewer.getVisualizeViewer;

  if (typeof visualizeViewer !== "function") {
    return null;
  }

  return visualizeViewer.call(viewer) as VisualizeViewerLike | null;
}

function normalizeTreeNodes(input: unknown): VsfxTreeNodeData[] {
  const candidateNodes = Array.isArray(input)
    ? input
    : isRecord(input) && Array.isArray(input.nodes)
      ? input.nodes
      : [];

  return candidateNodes.flatMap((node) => normalizeTreeNode(node));
}

function normalizeTreeNode(input: unknown): VsfxTreeNodeData[] {
  if (!isRecord(input) || (typeof input.handle !== "string" && typeof input.handle !== "number")) {
    return [];
  }

  const children = Array.isArray(input.children)
    ? input.children.flatMap((childNode) => normalizeTreeNode(childNode))
    : [];

  return [
    {
      children,
      handle: input.handle,
      name: typeof input.name === "string" && input.name.trim().length > 0
        ? input.name
        : String(input.handle),
    },
  ];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
