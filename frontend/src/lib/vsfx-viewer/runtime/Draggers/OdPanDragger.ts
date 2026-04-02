import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { PanAction } from "./Actions/PanAction";
import { OdBaseDragger } from "./Common/OdBaseDragger";

export class OdPanDragger extends OdBaseDragger {
  private readonly action: PanAction;

  constructor(viewer: IViewer) {
    super(viewer, "pan");
    this.action = new PanAction(viewer);
  }

  activate() {
    this.action.pan({ dx: 0, dy: 0 });
  }
}
