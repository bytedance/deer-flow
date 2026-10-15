import { useCallback, useEffect, useMemo, useRef } from "react";

import { useWorkspaceLifetime } from "./context";

/** A retained callback cannot become current again after A → B → A navigation. */
export function useCurrentWorkspaceView(resourceKey: string | object) {
  const lifetime = useWorkspaceLifetime();
  const identity = useMemo(
    () => ({ lifetime, resourceKey, mounted: true }),
    [lifetime, resourceKey],
  );
  const current = useRef(identity);
  current.current = identity;
  useEffect(() => {
    identity.mounted = true;
    return () => {
      identity.mounted = false;
    };
  }, [identity]);
  return useCallback(
    () =>
      current.current === identity &&
      identity.mounted &&
      !identity.lifetime?.scope.signal.aborted,
    [identity],
  );
}
