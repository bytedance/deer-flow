import { commandsRegistry, type ICommandsRegistry } from "@/lib/vsfx-viewer/viewer-core";

import type { Viewer } from "../Viewer";

import { clearSelected } from "./ClearSelected";
import { clearSlices } from "./ClearSlices";
import { collect, explode } from "./Explode";
import { getSelected } from "./GetSelected";
import { hideSelected } from "./HideSelected";
import { isolateSelected } from "./IsolateSelected";
import { planeViewX, planeViewY, planeViewZ } from "./PlaneView";
import { regenerateAll } from "./RegenerateAll";
import { resetView } from "./ResetView";
import { setSelected } from "./SetSelected";
import { showAll } from "./ShowAll";
import { zoomToExtents } from "./ZoomToExtents";
import { zoomToSelected } from "./ZoomToSelected";

export const approvedCommandNames = [
  "measureLine",
  "setSelected",
  "getSelected",
  "clearSelected",
  "k3DViewSW",
  "k3DViewTop",
  "k3DViewBottom",
  "k3DViewLeft",
  "k3DViewRight",
  "k3DViewFront",
  "k3DViewBack",
  "zoomToSelected",
  "zoomToExtents",
  "hideSelected",
  "isolateSelected",
  "showAll",
  "explode",
  "collect",
  "resetView",
  "regenerateAll",
  "clearSlices",
  "planeViewX",
  "planeViewY",
  "planeViewZ",
] as const;

export const viewerCommands: ICommandsRegistry<Viewer> = commandsRegistry<Viewer>();

viewerCommands.registerCommand("measureLine", (viewer) => {
  viewer.getVisualizeViewer()?.measureLine?.();
});
viewerCommands.registerCommand("setSelected", setSelected);
viewerCommands.registerCommand("getSelected", getSelected);
viewerCommands.registerCommand("clearSelected", clearSelected);
viewerCommands.registerCommand("k3DViewSW", (viewer) => {
  viewer.getVisualizeViewer()?.k3DViewSW?.();
  viewer.update();
});
viewerCommands.registerCommand("k3DViewTop", (viewer) => {
  viewer.getVisualizeViewer()?.k3DViewTop?.();
  viewer.update();
});
viewerCommands.registerCommand("k3DViewBottom", (viewer) => {
  viewer.getVisualizeViewer()?.k3DViewBottom?.();
  viewer.update();
});
viewerCommands.registerCommand("k3DViewLeft", (viewer) => {
  viewer.getVisualizeViewer()?.k3DViewLeft?.();
  viewer.update();
});
viewerCommands.registerCommand("k3DViewRight", (viewer) => {
  viewer.getVisualizeViewer()?.k3DViewRight?.();
  viewer.update();
});
viewerCommands.registerCommand("k3DViewFront", (viewer) => {
  viewer.getVisualizeViewer()?.k3DViewFront?.();
  viewer.update();
});
viewerCommands.registerCommand("k3DViewBack", (viewer) => {
  viewer.getVisualizeViewer()?.k3DViewBack?.();
  viewer.update();
});
viewerCommands.registerCommand("zoomToSelected", zoomToSelected);
viewerCommands.registerCommand("zoomToExtents", zoomToExtents);
viewerCommands.registerCommand("hideSelected", hideSelected);
viewerCommands.registerCommand("isolateSelected", isolateSelected);
viewerCommands.registerCommand("showAll", showAll);
viewerCommands.registerCommand("explode", explode);
viewerCommands.registerCommand("collect", collect);
viewerCommands.registerCommand("resetView", resetView);
viewerCommands.registerCommand("regenerateAll", regenerateAll);
viewerCommands.registerCommand("clearSlices", clearSlices);
viewerCommands.registerCommand("planeViewX", planeViewX);
viewerCommands.registerCommand("planeViewY", planeViewY);
viewerCommands.registerCommand("planeViewZ", planeViewZ);
