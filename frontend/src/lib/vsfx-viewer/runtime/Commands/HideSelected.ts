import type { Viewer } from "../Viewer";

export function hideSelected(viewer: Viewer) {
  const handles = viewer.getSelected();
  viewer.getVisualizeViewer()?.hideSelected?.();
  viewer.emit("hide", handles);
  viewer.update();
}
