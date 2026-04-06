import {
  componentsRegistry,
  type IComponentsRegistry,
} from "@/lib/vsfx-viewer/viewer-core";

import type { Viewer } from "../Viewer";

import { installGestureManagerComponent } from "./GestureManagerComponent";
import { installRenderLoopComponent } from "./RenderLoopComponent";
import { installResizeCanvasComponent } from "./ResizeCanvasComponent";
import { installZoomWheelComponent } from "./ZoomWheelComponent";

export const viewerComponents: IComponentsRegistry<Viewer> =
  componentsRegistry<Viewer>();

viewerComponents.registerComponent("render-loop", installRenderLoopComponent);
viewerComponents.registerComponent("resize-canvas", installResizeCanvasComponent);
viewerComponents.registerComponent("zoom-wheel", installZoomWheelComponent);
viewerComponents.registerComponent("gesture-manager", installGestureManagerComponent);
