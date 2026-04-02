import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { OrbitAction } from "./Actions/OrbitAction";
import { OdBaseDragger } from "./Common/OdBaseDragger";

export class OdOrbitDragger extends OdBaseDragger {
  private readonly action: OrbitAction;

  constructor(viewer: IViewer) {
    super(viewer, "orbit");
    this.action = new OrbitAction(viewer);
  }

  activate() {
    this.action.orbit({ dx: 0, dy: 0 });
  }
}
