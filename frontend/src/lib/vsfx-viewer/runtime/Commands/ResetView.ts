import type { Viewer } from "../Viewer";

export function resetView(viewer: Viewer) {
  viewer.executeCommand("clearSlices");
  viewer.executeCommand("clearSelected");
  viewer.executeCommand("showAll");
  viewer.executeCommand("collect");
  viewer.executeCommand("zoomToExtents");
  viewer.executeCommand("k3DViewSW");
  viewer.getVisualizeViewer()?.resetView?.();
  viewer.update();
  viewer.emit("resetview", undefined);
}
