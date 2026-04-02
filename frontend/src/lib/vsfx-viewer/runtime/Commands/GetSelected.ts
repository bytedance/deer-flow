import type { Viewer } from "../Viewer";

export function getSelected(viewer: Viewer) {
  return viewer.getVisualizeViewer()?.getSelected?.() ?? [];
}
