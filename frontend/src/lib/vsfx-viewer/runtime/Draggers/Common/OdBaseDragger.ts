import type { IDragger, IViewer } from "@/lib/vsfx-viewer/viewer-core";

export abstract class OdBaseDragger implements IDragger {
  protected readonly viewer: IViewer;

  readonly id: string;

  constructor(viewer: IViewer, id: string) {
    this.viewer = viewer;
    this.id = id;
  }

  activate() {
    void this.id;
  }

  deactivate() {
    void this.id;
  }

  dispose() {
    void this.viewer;
  }
}
