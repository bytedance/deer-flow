import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { PanAction } from "./Actions/PanAction";
import { OdBaseDragger } from "./Common/OdBaseDragger";

export class OdPanDragger extends OdBaseDragger {
  private readonly action: PanAction;

  constructor(viewer: IViewer) {
    super(viewer, "pan");
    this.autoSelect = true;
    this.action = new PanAction(viewer, {
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
