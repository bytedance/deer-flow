import { usePathname } from "next/navigation";
import {
  createContext,
  type Dispatch,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type SetStateAction,
} from "react";

import { useSidebar } from "@/components/ui/sidebar";
import type { ArtifactDraftState } from "@/core/artifacts/editing";
import { useWorkspaceLifetime } from "@/core/workspaces/context";
import { useCurrentWorkspaceView } from "@/core/workspaces/view-lifetime";
import { env } from "@/env";

export interface ArtifactsContextType {
  artifacts: string[];
  setArtifacts: (artifacts: string[]) => void;

  selectedArtifact: string | null;
  autoSelect: boolean;
  select: (artifact: string, autoSelect?: boolean) => void;
  deselect: () => void;

  open: boolean;
  autoOpen: boolean;
  setOpen: (open: boolean) => void;

  drafts: Record<string, ArtifactDraftState>;
  setDrafts: Dispatch<SetStateAction<Record<string, ArtifactDraftState>>>;
  editingPath: string | null;
  setEditingPath: Dispatch<SetStateAction<string | null>>;
}

const ArtifactsContext = createContext<ArtifactsContextType | undefined>(
  undefined,
);

const ARTIFACTS_STORAGE_PREFIX = "deerflow:artifacts:v1";

type PersistedArtifactsState = {
  artifacts: string[];
  selectedArtifact: string | null;
  open: boolean;
};

function storageKey(pathname: string) {
  return `${ARTIFACTS_STORAGE_PREFIX}:${encodeURIComponent(pathname)}`;
}

function readPersistedState(key: string): PersistedArtifactsState | null {
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<PersistedArtifactsState>;
    if (
      !Array.isArray(parsed.artifacts) ||
      !parsed.artifacts.every((artifact) => typeof artifact === "string") ||
      !(
        parsed.selectedArtifact === null ||
        typeof parsed.selectedArtifact === "string"
      ) ||
      typeof parsed.open !== "boolean"
    ) {
      return null;
    }
    return {
      artifacts: parsed.artifacts,
      selectedArtifact: parsed.selectedArtifact,
      open: parsed.open,
    };
  } catch {
    return null;
  }
}

interface ArtifactsProviderProps {
  children: ReactNode;
}

function useGuardedSetter<T>(
  setter: Dispatch<SetStateAction<T>>,
  isCurrent: () => boolean,
): Dispatch<SetStateAction<T>> {
  return useCallback(
    (value: SetStateAction<T>) => {
      if (!isCurrent()) return;
      setter((current) => {
        if (!isCurrent()) return current;
        const next =
          typeof value === "function"
            ? (value as (previous: T) => T)(current)
            : value;
        return isCurrent() ? next : current;
      });
    },
    [setter, isCurrent],
  );
}

export function ArtifactsProvider({ children }: ArtifactsProviderProps) {
  const lifetime = useWorkspaceLifetime();
  const pathname = usePathname();
  const isCurrent = useCurrentWorkspaceView(pathname ?? "");
  const key = lifetime
    ? `deerflow:workspace-artifacts:v1:${encodeURIComponent(lifetime.scope.actorUserId)}:${encodeURIComponent(lifetime.scope.workspaceId)}:${encodeURIComponent(pathname ?? "")}`
    : storageKey(pathname ?? "");
  const [owner, setOwner] = useState(() => isCurrent);
  const initial = useMemo(
    () => (lifetime ? readPersistedState(key) : null),
    [key, lifetime],
  );
  const [artifacts, setArtifactsRaw] = useState<string[]>(
    initial?.artifacts ?? [],
  );
  const [selectedArtifact, setSelectedArtifactRaw] = useState<string | null>(
    initial?.selectedArtifact ?? null,
  );
  const [autoSelect, setAutoSelect] = useState(!initial?.selectedArtifact);
  const [open, setOpenRaw] = useState(
    initial?.open ?? env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true",
  );
  const [autoOpen, setAutoOpen] = useState(true);
  const [drafts, setDraftsRaw] = useState<Record<string, ArtifactDraftState>>(
    {},
  );
  const [editingPath, setEditingPathRaw] = useState<string | null>(null);
  const { setOpen: setSidebarOpen } = useSidebar();
  const setArtifacts = useGuardedSetter(setArtifactsRaw, isCurrent);
  const setSelectedArtifact = useGuardedSetter(
    setSelectedArtifactRaw,
    isCurrent,
  );
  const setOpen = useGuardedSetter(setOpenRaw, isCurrent);
  const setDrafts = useGuardedSetter(setDraftsRaw, isCurrent);
  const setEditingPath = useGuardedSetter(setEditingPathRaw, isCurrent);
  // Reset this provider's state without remounting the live chat/stream subtree.
  if (owner !== isCurrent) {
    setOwner(() => isCurrent);
    const persisted = lifetime ? readPersistedState(key) : null;
    setArtifactsRaw(persisted?.artifacts ?? []);
    setSelectedArtifactRaw(persisted?.selectedArtifact ?? null);
    setOpenRaw(
      persisted?.open ?? env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true",
    );
    setAutoOpen(true);
    setAutoSelect(!persisted?.selectedArtifact);
    setDraftsRaw({});
    setEditingPathRaw(null);
  }
  const hydratedPathRef = useRef<string | null>(null);

  useEffect(() => {
    if (lifetime || !pathname || !isCurrent()) {
      return;
    }

    const persisted = readPersistedState(key);
    setArtifacts(persisted?.artifacts ?? []);
    setSelectedArtifact(persisted?.selectedArtifact ?? null);
    setOpen(persisted?.open ?? env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true");
    setAutoOpen(true);
    setAutoSelect(!persisted?.selectedArtifact);
    setDrafts({});
    setEditingPath(null);
    hydratedPathRef.current = pathname;
  }, [
    pathname,
    key,
    lifetime,
    isCurrent,
    setArtifacts,
    setSelectedArtifact,
    setOpen,
    setDrafts,
    setEditingPath,
  ]);

  useEffect(() => {
    const hasUnsavedDrafts = Object.values(drafts).some(
      (draft) => draft.draftContent !== draft.baselineContent,
    );
    if (!hasUnsavedDrafts) {
      return;
    }
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (isCurrent()) event.preventDefault();
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [drafts, isCurrent]);

  useEffect(() => {
    if (
      !isCurrent() ||
      !pathname ||
      (!lifetime && hydratedPathRef.current !== pathname)
    ) {
      return;
    }
    try {
      window.sessionStorage.setItem(
        key,
        JSON.stringify({ artifacts, selectedArtifact, open }),
      );
    } catch {
      // Browser storage can be disabled or full; panel state must keep working.
    }
  }, [artifacts, open, pathname, selectedArtifact, key, lifetime, isCurrent]);

  const select = useCallback(
    (artifact: string, autoSelect = false) => {
      if (!isCurrent()) return;
      setSelectedArtifact(artifact);
      if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true") {
        setSidebarOpen(false);
      }
      if (!autoSelect) {
        setAutoSelect(false);
      }
    },
    [setSidebarOpen, setSelectedArtifact, setAutoSelect, isCurrent],
  );

  const deselect = useCallback(() => {
    if (!isCurrent()) return;
    setSelectedArtifact(null);
    setAutoSelect(true);
    setOpen(false);
  }, [isCurrent, setSelectedArtifact, setOpen]);

  const value: ArtifactsContextType = {
    artifacts,
    setArtifacts,

    open,
    autoOpen,
    autoSelect,
    setOpen: (isOpen: boolean) => {
      if (!isCurrent()) return;
      if (!isOpen && autoOpen) {
        setAutoOpen(false);
        setAutoSelect(false);
      }
      setOpen(isOpen);
    },

    selectedArtifact,
    select,
    deselect,

    drafts,
    setDrafts,
    editingPath,
    setEditingPath,
  };

  return (
    <ArtifactsContext.Provider value={value}>
      {children}
    </ArtifactsContext.Provider>
  );
}

export function useArtifacts() {
  const context = useContext(ArtifactsContext);
  if (context === undefined) {
    throw new Error("useArtifacts must be used within an ArtifactsProvider");
  }
  return context;
}
