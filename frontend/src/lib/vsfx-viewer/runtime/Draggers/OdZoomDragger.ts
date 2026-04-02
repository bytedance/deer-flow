import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { ZoomAction } from "./Actions/ZoomAction";
import { OdBaseDragger } from "./Common/OdBaseDragger";

export class OdZoomDragger extends OdBaseDragger {
  private readonly action: ZoomAction;

  constructor(viewer: IViewer) {
    super(viewer, "zoom");
    this.action = new ZoomAction(viewer);
  }

  activate() {
    this.action.zoom(0);
  }
}
