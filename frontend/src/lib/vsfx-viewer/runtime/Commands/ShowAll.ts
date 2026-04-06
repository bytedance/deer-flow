import type { Viewer } from "../Viewer";

export function showAll(viewer: Viewer) {
  viewer.getVisualizeViewer()?.showAll?.();
  viewer.emit("showall", undefined);
  viewer.update();
}
