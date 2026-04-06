import type { Viewer } from "../Viewer";

export function clearSelected(viewer: Viewer) {
  viewer.getVisualizeViewer()?.clearSelected?.();
  viewer.emit("select", []);
  viewer.update();
}
