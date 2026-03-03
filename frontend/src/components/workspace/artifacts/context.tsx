import {
  createContext,
  useCallback,
  useContext,
  useMemo,
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

interface ArtifactsProviderProps {
  children: ReactNode;
}

export function ArtifactsProvider({ children }: ArtifactsProviderProps) {
  const [artifacts, setArtifacts] = useState<string[]>([]);
  const [selectedArtifact, setSelectedArtifact] = useState<string | null>(null);
  const [autoSelect, setAutoSelect] = useState(true);
  const [open, setOpen] = useState(
    env.VITE_STATIC_WEBSITE_ONLY === "true",
  );
  const [autoOpen, setAutoOpen] = useState(true);
  const { setOpen: setSidebarOpen } = useSidebar();

  const select = useCallback(
    (artifact: string, isAutoSelect = false) => {
      setSelectedArtifact(artifact);
      if (env.VITE_STATIC_WEBSITE_ONLY !== "true") {
        setSidebarOpen(false);
      }
      if (!isAutoSelect) {
        setAutoSelect(false);
      }
    },
    [setSidebarOpen],
  );

  const deselect = useCallback(() => {
    setSelectedArtifact(null);
    setAutoSelect(true);
  }, []);

  const autoOpenRef = useRef(autoOpen);
  autoOpenRef.current = autoOpen;

  const handleSetOpen = useCallback((isOpen: boolean) => {
    if (!isOpen && autoOpenRef.current) {
      setAutoOpen(false);
      setAutoSelect(false);
    }
    setOpen(isOpen);
  }, []);

  const value = useMemo<ArtifactsContextType>(
    () => ({
      artifacts,
      setArtifacts,
      open,
      autoOpen,
      autoSelect,
      setOpen: handleSetOpen,
      selectedArtifact,
      select,
      deselect,
    }),
    [
      artifacts,
      open,
      autoOpen,
      autoSelect,
      handleSetOpen,
      selectedArtifact,
      select,
      deselect,
    ],
  );

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
