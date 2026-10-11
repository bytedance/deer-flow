"use client";

import {
  createContext,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useState,
} from "react";

import type { ArtifactDraftState } from "@/core/artifacts/editing";

type Drafts = Record<string, ArtifactDraftState>;
type RouteDrafts = Record<string, Drafts>;
type DraftStore = {
  owner: string | null;
  generation: number;
  routes: RouteDrafts;
};
const EMPTY_DRAFTS: Drafts = {};
const useClientLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

const ArtifactDraftsContext = createContext<DraftStore | null>(null);
const ArtifactDraftsSetterContext = createContext<Dispatch<
  SetStateAction<DraftStore>
> | null>(null);

// RootLayout survives chat navigation and workspace layout replacement.
// File bodies stay in React memory, never in browser storage or a module cache.
export function ArtifactDraftsProvider({ children }: { children: ReactNode }) {
  const [store, setStore] = useState<DraftStore>({
    owner: null,
    generation: 0,
    routes: {},
  });
  const hasUnsavedDrafts = Object.values(store.routes).some((drafts) =>
    Object.values(drafts).some(
      (draft) => draft.draftContent !== draft.baselineContent,
    ),
  );

  useEffect(() => {
    if (!hasUnsavedDrafts) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasUnsavedDrafts]);

  return (
    <ArtifactDraftsSetterContext.Provider value={setStore}>
      <ArtifactDraftsContext.Provider value={store}>
        {children}
      </ArtifactDraftsContext.Provider>
    </ArtifactDraftsSetterContext.Provider>
  );
}

// Every AuthProvider (including login pages) clears drafts when its owner
// changes. Unmounting an auth layout to visit home deliberately retains them.
export function useArtifactDraftOwner(owner: string | null | undefined) {
  const setStore = useContext(ArtifactDraftsSetterContext);
  useClientLayoutEffect(() => {
    // An unavailable auth probe is not a logout or account change.
    if (owner === undefined) return;
    setStore?.((current) =>
      current.owner === owner
        ? current
        : { owner, generation: current.generation + 1, routes: {} },
    );
  }, [owner, setStore]);
}

export function useArtifactDrafts(pathname: string, owner: string | null) {
  const store = useContext(ArtifactDraftsContext);
  const setStore = useContext(ArtifactDraftsSetterContext);
  if (!store || !setStore) {
    throw new Error("ArtifactsProvider must be inside ArtifactDraftsProvider");
  }
  const generation = store.generation;
  const setDrafts: Dispatch<SetStateAction<Drafts>> = useCallback(
    (update) => {
      setStore((current) => {
        // A save/refetch completing after an account change cannot repopulate
        // another account's store with the previous owner's file content.
        if (current.owner !== owner || current.generation !== generation)
          return current;
        const drafts =
          typeof update === "function"
            ? update(current.routes[pathname] ?? EMPTY_DRAFTS)
            : update;
        return {
          ...current,
          routes: { ...current.routes, [pathname]: drafts },
        };
      });
    },
    [generation, owner, pathname, setStore],
  );
  // Never expose the previous owner's drafts, including the render before
  // AuthProvider's layout effect binds the new owner.
  return {
    drafts:
      store.owner === owner
        ? (store.routes[pathname] ?? EMPTY_DRAFTS)
        : EMPTY_DRAFTS,
    setDrafts,
  };
}
