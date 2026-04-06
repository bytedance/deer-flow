import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import type { Viewer } from "../../Viewer";

export type ViewParams = {
  perspective: boolean;
  position: number[];
  target: number[];
  upVector: number[];
  viewFieldHeight: number;
  viewFieldWidth: number;
};

type RuntimeView = {
  delete?: () => void;
  perspective: boolean;
  upVector: number[];
  viewFieldHeight: number;
  viewFieldWidth: number;
  viewPosition: number[];
  viewTarget: number[];
  vportRect?: [number, number, number, number];
};

type RuntimeExtent = {
  addExt?: (extent: RuntimeExtent) => void;
  center?: () => number[] | { x: number; y: number; z: number };
  delete?: () => void;
};

type RuntimeSelectionSet = {
  getIterator?: () => {
    delete?: () => void;
    done: () => boolean;
    getEntity: () => {
      delete?: () => void;
      getWCSExtents?: () => RuntimeExtent;
    };
    step: () => void;
  };
  isNull?: () => boolean;
  numItems?: () => number;
};

type RuntimeVisualizeViewer = {
  activeView?: RuntimeView;
  getActiveExtents?: () => RuntimeExtent;
  getActiveTvExtendedView?: () => {
    delete?: () => void;
    setView?: (
      position: number[],
      target: number[],
      upVector: number[],
      viewFieldWidth: number,
      viewFieldHeight: number,
      perspective: boolean,
    ) => void;
  };
  getEnableAutoSelect?: () => boolean;
  getSelected?: () => RuntimeSelectionSet | Array<string | number>;
  screenToWorld?: (x: number, y: number) => number[];
  setEnableAutoSelect?: (enabled: boolean) => void;
  zoomAt?: (zoomFactor: number, x: number, y: number) => void;
};

export class OdaGeAction {
  protected readonly subject: Viewer;

  constructor(viewer: IViewer) {
    this.subject = viewer as Viewer;
  }

  protected getViewer(): RuntimeVisualizeViewer | null {
    return this.subject.getVisualizeViewer() as RuntimeVisualizeViewer | null;
  }

  protected getViewParams(): ViewParams | null {
    const view = this.getViewer()?.activeView;

    if (!view) {
      return null;
    }

    const params: ViewParams = {
      perspective: view.perspective,
      position: [...view.viewPosition],
      target: [...view.viewTarget],
      upVector: [...view.upVector],
      viewFieldHeight: view.viewFieldHeight,
      viewFieldWidth: view.viewFieldWidth,
    };

    view.delete?.();

    return params;
  }

  protected screenToWorld(x: number, y: number) {
    return this.getViewer()?.screenToWorld?.(x, y) ?? [x, y, 0];
  }

  protected getAutoSelectEnabled(defaultValue: boolean) {
    return this.getViewer()?.getEnableAutoSelect?.() ?? defaultValue;
  }

  protected setAutoSelectEnabled(enabled: boolean) {
    this.getViewer()?.setEnableAutoSelect?.(enabled);
  }

  protected getOrbitCenter(fallback: number[] = [0, 0, 0]) {
    const viewer = this.getViewer();
    const selected = viewer?.getSelected?.();
    const selectionCenter = this.getSelectionCenter(selected);

    if (selectionCenter) {
      return selectionCenter;
    }

    return this.toPointArray(viewer?.getActiveExtents?.()?.center?.()) ?? fallback;
  }

  protected setViewParams(params: ViewParams) {
    const extView = this.getViewer()?.getActiveTvExtendedView?.();

    extView?.setView?.(
      params.position,
      params.target,
      params.upVector,
      params.viewFieldWidth,
      params.viewFieldHeight,
      params.perspective,
    );
    extView?.delete?.();
  }

  private getSelectionCenter(selected: RuntimeSelectionSet | Array<string | number> | undefined) {
    if (!selected || Array.isArray(selected)) {
      return null;
    }

    if (selected.isNull?.() || (selected.numItems?.() ?? 0) === 0) {
      return null;
    }

    const iterator = selected.getIterator?.();

    if (!iterator) {
      return null;
    }

    let mergedExtent: RuntimeExtent | null = null;

    try {
      for (; !iterator.done(); iterator.step()) {
        const entity = iterator.getEntity();
        const extent = entity.getWCSExtents?.();

        if (!extent) {
          entity.delete?.();
          continue;
        }

        if (mergedExtent?.addExt) {
          mergedExtent.addExt(extent);
          extent.delete?.();
        }
        else {
          mergedExtent = extent;
        }

        entity.delete?.();
      }

      return this.toPointArray(mergedExtent?.center?.()) ?? null;
    }
    finally {
      mergedExtent?.delete?.();
      iterator.delete?.();
    }
  }

  private toPointArray(point: number[] | { x: number; y: number; z: number } | undefined | null) {
    if (Array.isArray(point)) {
      return [point[0] ?? 0, point[1] ?? 0, point[2] ?? 0];
    }

    if (!point || typeof point !== "object") {
      return null;
    }

    return [point.x ?? 0, point.y ?? 0, point.z ?? 0];
  }
}
