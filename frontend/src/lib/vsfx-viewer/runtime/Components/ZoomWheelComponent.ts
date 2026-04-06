import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { OdZoomWheelDragger } from "../Draggers/OdZoomWheelDragger";

export function installZoomWheelComponent(viewer: IViewer) {
  const dragger = new OdZoomWheelDragger(viewer);
  dragger.initialize();

  return () => {
    dragger.dispose();
  };
}
