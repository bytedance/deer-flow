import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { OrbitAction } from "./Actions/OrbitAction";
import { PanAction } from "./Actions/PanAction";
import { OdBaseDragger } from "./Common/OdBaseDragger";

export class OdOrbitPanDragger extends OdBaseDragger {
  private readonly orbitAction: OrbitAction;
  private readonly panAction: PanAction;

  constructor(viewer: IViewer) {
    super(viewer, "orbit-pan");
    this.orbitAction = new OrbitAction(viewer);
    this.panAction = new PanAction(viewer);
  }

  activate() {
    this.orbitAction.orbit({ dx: 0, dy: 0 });
    this.panAction.pan({ dx: 0, dy: 0 });
  }
}
