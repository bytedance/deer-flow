import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { OdZoomWheelDragger } from "../Draggers/OdZoomWheelDragger";

export function installZoomWheelComponent(viewer: IViewer) {
  const container = viewer.getContainer();
  const dragger = new OdZoomWheelDragger(viewer);
  const handleWheel = (event: WheelEvent) => {
    dragger.handleWheel(event.deltaY);
  };

  container.addEventListener("wheel", handleWheel, { passive: true });

  return () => {
    container.removeEventListener("wheel", handleWheel);
    dragger.dispose();
  };
}
