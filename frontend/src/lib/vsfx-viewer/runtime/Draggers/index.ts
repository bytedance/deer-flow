import { draggersRegistry, type IDraggersRegistry } from "@/lib/vsfx-viewer/viewer-core";

import type { Viewer } from "../Viewer";

import { OdOrbitDragger } from "./OdOrbitDragger";
import { OdOrbitPanDragger } from "./OdOrbitPanDragger";
import { OdPanDragger } from "./OdPanDragger";
import { OdZoomDragger } from "./OdZoomDragger";
import { OdZoomWheelDragger } from "./OdZoomWheelDragger";
import { WalkDragger } from "./WalkDragger";

export const viewerDraggers: IDraggersRegistry<Viewer> = draggersRegistry<Viewer>();

viewerDraggers.registerDragger("pan", (viewer) => new OdPanDragger(viewer));
viewerDraggers.registerDragger("orbit", (viewer) => new OdOrbitDragger(viewer));
viewerDraggers.registerDragger("orbit-pan", (viewer) => new OdOrbitPanDragger(viewer));
viewerDraggers.registerDragger("walk", (viewer) => new WalkDragger(viewer));
viewerDraggers.registerDragger("zoom", (viewer) => new OdZoomDragger(viewer));
viewerDraggers.registerDragger("zoom-wheel", (viewer) => new OdZoomWheelDragger(viewer));
