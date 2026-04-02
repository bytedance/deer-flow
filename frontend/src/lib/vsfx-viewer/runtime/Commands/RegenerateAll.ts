import type { Viewer } from "../Viewer";

export function regenerateAll(viewer: Viewer) {
  viewer.getVisualizeViewer()?.regenerateAll?.();
  viewer.emit("regenerateall", undefined);
  viewer.update();
}
