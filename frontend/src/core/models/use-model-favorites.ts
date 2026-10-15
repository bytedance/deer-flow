import { useCallback, useSyncExternalStore } from "react";

import {
  EMPTY_FAVORITES,
  getFavoritesSnapshot,
  setModelFavorite,
  subscribeFavorites,
} from "./favorites-store";

function getServerSnapshot() {
  return EMPTY_FAVORITES;
}

export function useModelFavorites(userId: string | null) {
  const subscribe = useCallback(
    (listener: () => void) => subscribeFavorites(userId, listener),
    [userId],
  );
  const getSnapshot = useCallback(() => getFavoritesSnapshot(userId), [userId]);
  const snapshot = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );
  const setFavorite = useCallback(
    (name: string, favorite: boolean) =>
      setModelFavorite(userId, name, favorite),
    [userId],
  );

  return {
    names: snapshot.names,
    persistence: snapshot.persistence,
    canEdit: userId !== null,
    setFavorite,
  };
}
