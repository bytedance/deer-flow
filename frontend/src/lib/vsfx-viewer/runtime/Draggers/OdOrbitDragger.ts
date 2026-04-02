import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { OrbitAction } from "./Actions/OrbitAction";
import { OdBaseDragger } from "./Common/OdBaseDragger";

export class OdOrbitDragger extends OdBaseDragger {
  private readonly action: OrbitAction;

  constructor(viewer: IViewer) {
    super(viewer, "orbit");
    this.autoSelect = true;
    this.action = new OrbitAction(viewer, {
      beginInteractivity: this.beginInteractivity,
      endInteractivity: this.endInteractivity,
    });
  }

  protected start(x: number, y: number) {
    this.press = true;
    this.action.beginAction(x, y);
  }

  protected drag(x: number, y: number) {
    if (!this.press) {
      return;
    }

    this.action.action(x, y);
  }

  protected end() {
    this.press = false;
    this.action.endAction();
  }
}
