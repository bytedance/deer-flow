import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { ZoomAction } from "./Actions/ZoomAction";
import { OdBaseDragger } from "./Common/OdBaseDragger";

export class OdZoomWheelDragger extends OdBaseDragger {
  private readonly action: ZoomAction;

  constructor(viewer: IViewer) {
    super(viewer, "zoom-wheel");
    this.action = new ZoomAction(viewer);
  }

  handleWheel(deltaY: number) {
    this.action.zoom(deltaY);
  }
}
