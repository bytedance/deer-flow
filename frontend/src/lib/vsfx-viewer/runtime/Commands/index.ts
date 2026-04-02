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
  "setSelected",
  "getSelected",
  "clearSelected",
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

viewerCommands.registerCommand("setSelected", setSelected);
viewerCommands.registerCommand("getSelected", getSelected);
viewerCommands.registerCommand("clearSelected", clearSelected);
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
