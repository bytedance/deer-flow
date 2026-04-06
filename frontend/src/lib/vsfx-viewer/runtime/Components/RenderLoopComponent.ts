import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

export function installRenderLoopComponent(viewer: IViewer) {
  if (typeof window === "undefined" || typeof window.requestAnimationFrame !== "function") {
    return undefined;
  }

  let frameId = 0;
  let disposed = false;

  const tick = () => {
    if (disposed) {
      return;
    }
    viewer.render();
    frameId = window.requestAnimationFrame(tick);
  };

  frameId = window.requestAnimationFrame(tick);

  return () => {
    disposed = true;
    window.cancelAnimationFrame(frameId);
  };
}
