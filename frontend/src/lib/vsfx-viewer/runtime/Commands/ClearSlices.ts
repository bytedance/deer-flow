import type { Viewer } from "../Viewer";

import { resetPlaneViewCycle } from "./PlaneView";

export function clearSlices(viewer: Viewer) {
  viewer.clearSlices();
  resetPlaneViewCycle(viewer);
  viewer.update();
}
