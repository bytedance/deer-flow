import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { ZoomAction } from "./Actions/ZoomAction";
import { OdBaseDragger } from "./Common/OdBaseDragger";

const INTERACTIVITY_TIME_OUT = 100;
const ZOOM_SCALE = 0.925;

export class OdZoomWheelDragger extends OdBaseDragger {
  private endInteractivityTimeOutId: ReturnType<typeof setTimeout> | undefined;
  private isEnableInteractivityMode = false;
  private readonly action: ZoomAction;

  constructor(viewer: IViewer) {
    super(viewer, "zoom-wheel");
    this.canvasEvents = ["wheel"];
    this.action = new ZoomAction(viewer);
  }

  override dispose() {
    if (this.endInteractivityTimeOutId) {
      clearTimeout(this.endInteractivityTimeOutId);
      this.endInteractivity();
      this.isEnableInteractivityMode = false;
      this.endInteractivityTimeOutId = undefined;
    }

    super.dispose();
  }

  protected wheel(event: WheelEvent) {
    if (!this.viewer.getOptions().enableZoomWheel) {
      return;
    }

    try {
      event.preventDefault();
    }
    catch {
      // noop
    }

    const zoomIn = this.viewer.getOptions().reverseZoomWheel ? ZOOM_SCALE : 1 / ZOOM_SCALE;
    const zoomOut = this.viewer.getOptions().reverseZoomWheel ? 1 / ZOOM_SCALE : ZOOM_SCALE;
    const zoomFactor = event.deltaY < 0 ? zoomIn : zoomOut;
    const x = event.offsetX * window.devicePixelRatio;
    const y = event.offsetY * window.devicePixelRatio;

    this.action.action(x, y, zoomFactor);

    if (!this.isEnableInteractivityMode) {
      this.isEnableInteractivityMode = true;
      this.beginInteractivity();
    }

    if (this.endInteractivityTimeOutId) {
      clearTimeout(this.endInteractivityTimeOutId);
    }

    this.endInteractivityTimeOutId = setTimeout(() => {
      this.endInteractivityTimeOutId = undefined;
      this.endInteractivity();
      this.isEnableInteractivityMode = false;
    }, INTERACTIVITY_TIME_OUT);
  }
}
