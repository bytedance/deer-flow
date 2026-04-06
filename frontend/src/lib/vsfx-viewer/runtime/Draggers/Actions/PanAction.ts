import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { OdaGeAction } from "../Common/OdaGeAction";

type PanCallbacks = {
  beginInteractivity: () => void;
  endInteractivity: () => void;
};

export class PanAction extends OdaGeAction {
  private readonly beginInteractivity: () => void;
  private readonly endInteractivity: () => void;
  private deltaScreenPosition = { x: 0, y: 0 };
  private startWorld = [0, 0, 0];

  constructor(viewer: IViewer, callbacks: PanCallbacks) {
    super(viewer);
    this.beginInteractivity = callbacks.beginInteractivity;
    this.endInteractivity = callbacks.endInteractivity;
  }

  beginAction(x: number, y: number, absoluteX: number, absoluteY: number) {
    this.startWorld = this.screenToWorld(x, y);
    this.deltaScreenPosition = { x: absoluteX, y: absoluteY };
    this.beginInteractivity();
  }

  action(x: number, y: number, absoluteX: number, absoluteY: number) {
    const params = this.getViewParams();

    if (!params) {
      return;
    }

    const point = this.screenToWorld(x, y);
    const delta = this.startWorld.map((value, index) => value - (point[index] ?? 0));

    params.position = params.position.map((value, index) => value + (delta[index] ?? 0));
    params.target = params.target.map((value, index) => value + (delta[index] ?? 0));

    this.setViewParams(params);
    this.deltaScreenPosition = { x: absoluteX, y: absoluteY };
  }

  endAction() {
    this.endInteractivity();
  }
}
