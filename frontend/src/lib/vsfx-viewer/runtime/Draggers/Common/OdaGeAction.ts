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
};

type RuntimeVisualizeViewer = {
  activeView?: RuntimeView;
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
  screenToWorld?: (x: number, y: number) => number[];
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
}
