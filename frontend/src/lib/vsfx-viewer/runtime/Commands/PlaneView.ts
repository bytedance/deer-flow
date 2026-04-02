import { normalizeAxisPositions, type AxisKey } from "@/lib/vsfx-viewer/viewer-core";

import type { Viewer } from "../Viewer";

const planeViewCycleState = new WeakMap<Viewer, Record<AxisKey, number>>();

export function planeViewX(viewer: Viewer) {
  applyPlaneView(viewer, "x");
}

export function planeViewY(viewer: Viewer) {
  applyPlaneView(viewer, "y");
}

export function planeViewZ(viewer: Viewer) {
  applyPlaneView(viewer, "z");
}

export function resetPlaneViewCycle(viewer: Viewer) {
  planeViewCycleState.delete(viewer);
}

function applyPlaneView(viewer: Viewer, axis: AxisKey) {
  const visualizeViewer = viewer.getVisualizeViewer();
  const methodName = `planeView${axis.toUpperCase()}` as const;
  const axisPositions = normalizeAxisPositions(viewer.getOptions().data?.axisPositions);
  const cycleState = planeViewCycleState.get(viewer) ?? { x: 0, y: 0, z: 0 };
  const positions = axisPositions[axis];
  const nextIndex = positions.length > 0 ? cycleState[axis] % positions.length : 0;
  const label =
    positions[nextIndex]?.label ??
    (axis === "x" ? "X direction" : axis === "y" ? "Y direction" : "Z direction");

  planeViewCycleState.set(viewer, {
    ...cycleState,
    [axis]: nextIndex + 1,
  });

  visualizeViewer?.[methodName]?.();
  viewer.emit("planeviewlabel", { axis, label });
  viewer.update();
}
