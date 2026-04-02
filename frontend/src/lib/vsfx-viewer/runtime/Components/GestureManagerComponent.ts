import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { GestureManager } from "../Draggers/Common/GestureManager";

export function installGestureManagerComponent(viewer: IViewer) {
  const manager = new GestureManager(viewer);
  manager.attach();

  return () => {
    manager.dispose();
  };
}
