import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

export function installResizeCanvasComponent(viewer: IViewer) {
  const container = viewer.getContainer();
  const resizeTarget = container.parentElement ?? container;

  if (typeof ResizeObserver === "function") {
    const observer = new ResizeObserver(() => {
      viewer.resize();
    });
    observer.observe(resizeTarget);

    return () => {
      observer.disconnect();
    };
  }

  const handleResize = () => {
    viewer.resize();
  };

  window.addEventListener("resize", handleResize);

  return () => {
    window.removeEventListener("resize", handleResize);
  };
}
