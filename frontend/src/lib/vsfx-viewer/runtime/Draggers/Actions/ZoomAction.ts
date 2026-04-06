import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { OdaGeAction } from "../Common/OdaGeAction";

export class ZoomAction extends OdaGeAction {
  constructor(viewer: IViewer) {
    super(viewer);
  }

  action(x: number, y: number, zoomFactor: number) {
    const runtimeViewer = this.getViewer();

    if (!runtimeViewer) {
      return;
    }

    if (runtimeViewer.zoomAt) {
      runtimeViewer.zoomAt(zoomFactor, x, y);
      this.subject.update();
      return;
    }

    const params = this.getViewParams();

    if (!params) {
      return;
    }

    params.viewFieldWidth *= zoomFactor;
    params.viewFieldHeight *= zoomFactor;

    this.setViewParams(params);
    this.subject.update();
  }
}
