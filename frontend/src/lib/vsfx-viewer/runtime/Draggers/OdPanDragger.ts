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

  protected start(x: number, y: number, absoluteX: number, absoluteY: number) {
    this.press = true;
    this.action.beginAction(x, y, absoluteX, absoluteY);
  }

  protected drag(x: number, y: number, absoluteX: number, absoluteY: number) {
    if (!this.press) {
      return;
    }

    this.action.action(x, y, absoluteX, absoluteY);
  }

  protected end(_x: number, _y: number, _absoluteX = 0, _absoluteY = 0) {
    this.press = false;
    this.action.endAction();
  }
}
