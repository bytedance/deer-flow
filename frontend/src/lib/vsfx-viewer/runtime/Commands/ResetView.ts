import type { Viewer } from "../Viewer";

export function resetView(viewer: Viewer) {
  viewer.executeCommand("clearSlices");
  viewer.executeCommand("clearSelected");
  viewer.executeCommand("showAll");
  viewer.executeCommand("collect");
  viewer.executeCommand("zoomToExtents");
  viewer.getVisualizeViewer()?.resetView?.();
  viewer.emit("resetview", undefined);
}
