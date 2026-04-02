import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { ZoomAction } from "./Actions/ZoomAction";
import { OdBaseDragger } from "./Common/OdBaseDragger";

const ZOOM_SPEED = 0.975;

export class OdZoomDragger extends OdBaseDragger {
  private readonly action: ZoomAction;
  private absoluteX = 0;
  private absoluteY = 0;
  private pressX = 0;
  private pressY = 0;
  private prevY = 0;

  constructor(viewer: IViewer) {
    super(viewer, "zoom");
    this.autoSelect = true;
    this.action = new ZoomAction(viewer);
  }

  protected start(x: number, y: number, absoluteX = 0, absoluteY = 0) {
    this.press = true;
    this.pressX = x;
    this.pressY = y;
    this.absoluteX = absoluteX;
    this.absoluteY = absoluteY;
    this.prevY = y;
    this.beginInteractivity();
  }

  protected drag(_x: number, y: number) {
    if (!this.press) {
      return;
    }

    const deltaY = y - this.prevY;

    if (Math.abs(deltaY) <= Number.EPSILON) {
      return;
    }

    this.prevY = y;
    this.action.action(
      this.pressX,
      this.pressY,
      deltaY > 0 ? 1 / ZOOM_SPEED : ZOOM_SPEED,
    );
  }

  protected end() {
    this.press = false;
    this.endInteractivity();
  }
}
