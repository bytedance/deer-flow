import type { Viewer } from "../Viewer";

export function zoomToExtents(viewer: Viewer) {
  viewer.getVisualizeViewer()?.zoomToExtents?.();
  viewer.emit("zoom", "extents");
  viewer.update();
}
