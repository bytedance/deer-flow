import type { Viewer } from "../Viewer";

export function isolateSelected(viewer: Viewer) {
  const handles = viewer.getSelected();
  viewer.getVisualizeViewer()?.isolateSelected?.();
  viewer.emit("isolate", handles);
  viewer.update();
}
