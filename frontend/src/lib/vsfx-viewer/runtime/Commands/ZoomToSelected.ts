import type { Viewer } from "../Viewer";

export function zoomToSelected(viewer: Viewer) {
  viewer.getVisualizeViewer()?.zoomToSelected?.();
  viewer.emit("zoom", "selected");
  viewer.update();
}
