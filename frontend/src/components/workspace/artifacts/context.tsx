import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useSidebar } from "@/components/ui/sidebar";
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

function readPersistedState(pathname: string): PersistedArtifactsState | null {
  try {
    const raw = window.sessionStorage.getItem(storageKey(pathname));
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

export function ArtifactsProvider({ children }: ArtifactsProviderProps) {
  const [artifacts, setArtifacts] = useState<string[]>([]);
  const [selectedArtifact, setSelectedArtifact] = useState<string | null>(null);
  const [autoSelect, setAutoSelect] = useState(true);
  const [open, setOpen] = useState(
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true",
  );
  const [autoOpen, setAutoOpen] = useState(true);
  const { setOpen: setSidebarOpen } = useSidebar();
  const pathname = usePathname();
  const hydratedPathRef = useRef<string | null>(null);

  useEffect(() => {
    if (!pathname) {
      return;
    }

    const persisted = readPersistedState(pathname);
    setArtifacts(persisted?.artifacts ?? []);
    setSelectedArtifact(persisted?.selectedArtifact ?? null);
    setOpen(persisted?.open ?? env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true");
    setAutoOpen(true);
    setAutoSelect(!persisted?.selectedArtifact);
    hydratedPathRef.current = pathname;
  }, [pathname]);

  useEffect(() => {
    if (!pathname || hydratedPathRef.current !== pathname) {
      return;
    }
    try {
      window.sessionStorage.setItem(
        storageKey(pathname),
        JSON.stringify({ artifacts, selectedArtifact, open }),
      );
    } catch {
      // Browser storage can be disabled or full; panel state must keep working.
    }
  }, [artifacts, open, pathname, selectedArtifact]);

  const select = useCallback(
    (artifact: string, autoSelect = false) => {
      setSelectedArtifact(artifact);
      if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true") {
        setSidebarOpen(false);
      }
      if (!autoSelect) {
        setAutoSelect(false);
      }
    },
    [setSidebarOpen, setSelectedArtifact, setAutoSelect],
  );

  const deselect = useCallback(() => {
    setSelectedArtifact(null);
    setAutoSelect(true);
    setOpen(false);
  }, []);

  const value: ArtifactsContextType = {
    artifacts,
    setArtifacts,

    open,
    autoOpen,
    autoSelect,
    setOpen: (isOpen: boolean) => {
      if (!isOpen && autoOpen) {
        setAutoOpen(false);
        setAutoSelect(false);
      }
      setOpen(isOpen);
    },

    selectedArtifact,
    select,
    deselect,
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
