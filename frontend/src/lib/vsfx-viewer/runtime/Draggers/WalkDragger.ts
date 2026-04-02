import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import type { Viewer } from "../Viewer";

import { OdBaseDragger } from "./Common/OdBaseDragger";

export class WalkDragger extends OdBaseDragger {
  constructor(viewer: IViewer) {
    super(viewer, "walk");
  }

  activate() {
    const runtimeViewer = (this.viewer as Viewer).getVisualizeViewer() as {
      setActiveDragger?: (name: string) => void;
    } | null;

    runtimeViewer?.setActiveDragger?.("Walk");
  }
}
