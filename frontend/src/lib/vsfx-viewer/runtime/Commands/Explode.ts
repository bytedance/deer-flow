import type { Viewer } from "../Viewer";

export function explode(viewer: Viewer, index = 0) {
  viewer.getVisualizeViewer()?.explode?.(index);
  viewer.emit("explode", index);
  viewer.update();
}

export function collect(viewer: Viewer) {
  const visualizeViewer = viewer.getVisualizeViewer();

  if (typeof visualizeViewer?.collect === "function") {
    visualizeViewer.collect();
    viewer.emit("explode", 0);
    viewer.update();
    return;
  }

  explode(viewer, 0);
}
