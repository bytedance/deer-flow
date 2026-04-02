import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import type { DragDelta } from "./Geometry";

export class OdaGeAction {
  protected readonly viewer: IViewer;

  constructor(viewer: IViewer) {
    this.viewer = viewer;
  }

  orbit(_delta: DragDelta) {
    this.viewer.update();
  }

  pan(_delta: DragDelta) {
    this.viewer.update();
  }

  zoom(_amount: number) {
    this.viewer.update();
  }
}
