import type { SidecarContext } from "./context";

export type SidecarReferenceStateItem = {
  id: number;
  context: SidecarContext;
};

export function isSameSidecarContext(
  left: SidecarContext,
  right: SidecarContext,
) {
  return (
    left.type === right.type &&
    left.role === right.role &&
    left.messageId === right.messageId &&
    left.content === right.content
  );
}

export function appendSidecarReference<
  TReference extends SidecarReferenceStateItem,
>(references: TReference[], nextReference: TReference) {
  if (
    references.some((reference) =>
      isSameSidecarContext(reference.context, nextReference.context),
    )
  ) {
    return references;
  }
  return [...references, nextReference];
}

export function getNextSidecarOpenState<
  TReference extends SidecarReferenceStateItem,
>({
  open,
  sidecarThreadId,
  activeReferences,
  nextReference,
}: {
  open: boolean;
  sidecarThreadId: string | null;
  activeReferences: TReference[];
  nextReference: TReference;
}) {
  const shouldAppendToCurrentSidecar =
    open && (Boolean(sidecarThreadId) || activeReferences.length > 0);

  return {
    sidecarThreadId,
    activeReferences: shouldAppendToCurrentSidecar
      ? appendSidecarReference(activeReferences, nextReference)
      : [nextReference],
  };
}
