import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

export class GestureManager {
  private readonly viewer: IViewer;

  constructor(viewer: IViewer) {
    this.viewer = viewer;
  }

  attach() {
    this.viewer.update();
  }

  detach() {
    void this.viewer;
  }

  dispose() {
    this.detach();
  }
}
