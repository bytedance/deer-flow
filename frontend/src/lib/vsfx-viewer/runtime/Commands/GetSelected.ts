import type { Viewer } from "../Viewer";

export function getSelected(viewer: Viewer) {
  const selected = viewer.getVisualizeViewer()?.getSelected?.();

  return normalizeSelectedHandles(selected);
}

type SelectionSetLike = {
  getIterator?: () => {
    delete?: () => void;
    done: () => boolean;
    getEntity: () => {
      delete?: () => void;
      getType?: () => number;
      openObject?: () => {
        delete?: () => void;
        getNativeDatabaseHandle?: () => string | number;
      } | null;
      openObjectAsInsert?: () => {
        delete?: () => void;
        getNativeDatabaseHandle?: () => string | number;
      } | null;
    };
    step: () => void;
  };
  isNull?: () => boolean;
  numItems?: () => number;
};

export function normalizeSelectedHandles(selected: unknown): Array<string | number> {
  if (Array.isArray(selected)) {
    return selected.filter(
      (handle): handle is string | number =>
        typeof handle === "string" || typeof handle === "number",
    );
  }

  if (!selected || typeof selected !== "object") {
    return [];
  }

  const selectionSet = selected as SelectionSetLike;

  if (selectionSet.isNull?.() || (selectionSet.numItems?.() ?? 0) === 0) {
    return [];
  }

  const iterator = selectionSet.getIterator?.();

  if (!iterator) {
    return [];
  }

  const handles: Array<string | number> = [];

  try {
    for (; !iterator.done(); iterator.step()) {
      const entityId = iterator.getEntity();
      const entity =
        entityId.getType?.() === 1
          ? entityId.openObject?.()
          : entityId.getType?.() === 2
            ? entityId.openObjectAsInsert?.()
            : null;
      const handle = entity?.getNativeDatabaseHandle?.();

      if (
        (typeof handle === "string" || typeof handle === "number")
        && `${handle}` !== "-1"
      ) {
        handles.push(handle);
      }

      entity?.delete?.();
      entityId.delete?.();
    }
  }
  finally {
    iterator.delete?.();
  }

  return handles;
}
