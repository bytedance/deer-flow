import type { Viewer } from "../Viewer";

export function setSelected(viewer: Viewer, handles: Array<string | number> = []) {
  const visualizeViewer = viewer.getVisualizeViewer();
  const visualizeLibrary = viewer.getVisualizeLibrary() as VisualizeLibraryLike | null;

  if (
    visualizeViewer
    && typeof visualizeViewer.getEntityByOriginalHandle === "function"
    && typeof visualizeViewer.setSelected === "function"
    && typeof visualizeLibrary?.OdTvSelectionSet === "function"
  ) {
    const selectionSet = new visualizeLibrary.OdTvSelectionSet();

    try {
      for (const handle of handles) {
        const entityId = visualizeViewer.getEntityByOriginalHandle(String(handle));

        if (isNonNullVisualizeEntity(entityId)) {
          selectionSet.appendEntity?.(entityId);
        }
      }

      visualizeViewer.setSelected(selectionSet);
    }
    finally {
      selectionSet.delete?.();
    }
  }
  else {
    visualizeViewer?.setSelected?.(handles);
  }

  viewer.emit("select", handles);
  viewer.update();
}

type VisualizeLibraryLike = {
  OdTvSelectionSet?: new () => {
    appendEntity?: (entity: unknown) => void;
    delete?: () => void;
  };
};

function isNonNullVisualizeEntity(entity: unknown) {
  if (!entity || typeof entity !== "object") {
    return false;
  }

  const candidate = entity as { isNull?: () => boolean };

  return typeof candidate.isNull === "function" ? !candidate.isNull() : true;
}
