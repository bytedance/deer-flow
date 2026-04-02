import type { Viewer } from "../Viewer";

export function setSelected(viewer: Viewer, handles: Array<string | number> = []) {
  viewer.getVisualizeViewer()?.setSelected?.(handles);
  viewer.emit("select", handles);
  viewer.update();
}
