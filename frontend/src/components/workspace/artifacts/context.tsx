import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

import { useSidebar } from "@/components/ui/sidebar";
import { browseDirectory, type DirectoryEntry } from "@/core/filesystem/api";
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

  directoryEntries: Record<string, DirectoryEntry[]>;
  expandedFolders: Set<string>;
  currentPath: string;
  isLoadingDirectory: boolean;
  directoryError: string | null;
  setDirectoryEntries: (path: string, entries: DirectoryEntry[]) => void;
  toggleFolder: (path: string) => void;
  loadDirectory: (path: string) => Promise<void>;
  navigateUp: () => void;
}

const ArtifactsContext = createContext<ArtifactsContextType | undefined>(
  undefined,
);

interface ArtifactsProviderProps {
  children: ReactNode;
  threadId: string;
}

export function ArtifactsProvider({
  children,
  threadId,
}: ArtifactsProviderProps) {
  const [artifacts, setArtifacts] = useState<string[]>([]);
  const [selectedArtifact, setSelectedArtifact] = useState<string | null>(null);
  const [autoSelect, setAutoSelect] = useState(true);
  const [open, setOpen] = useState(
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true",
  );
  const [autoOpen, setAutoOpen] = useState(true);
  const { setOpen: setSidebarOpen } = useSidebar();

  const [directoryEntries, setDirectoryEntriesMap] = useState<
    Record<string, DirectoryEntry[]>
  >({});
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(
    new Set(),
  );
  const [currentPath, setCurrentPath] = useState("/mnt/user-data/workspace");
  const [isLoadingDirectory, setIsLoadingDirectory] = useState(false);
  const [directoryError, setDirectoryError] = useState<string | null>(null);

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

  const setDirectoryEntries = useCallback(
    (path: string, entries: DirectoryEntry[]) => {
      setDirectoryEntriesMap((prev) => ({ ...prev, [path]: entries }));
    },
    [],
  );

  const toggleFolder = useCallback((path: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  const loadDirectory = useCallback(
    async (path: string) => {
      setCurrentPath(path);
      setIsLoadingDirectory(true);
      setDirectoryError(null);
      try {
        const entries = await browseDirectory(threadId, path);
        setDirectoryEntries(path, entries);
        setExpandedFolders((prev) => {
          const next = new Set(prev);
          next.add(path);
          return next;
        });
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Failed to load directory";
        setDirectoryError(message);
        console.error("Failed to load directory:", error);
      } finally {
        setIsLoadingDirectory(false);
      }
    },
    [threadId, setDirectoryEntries],
  );

  const navigateUp = useCallback(() => {
    const parent = currentPath.substring(0, currentPath.lastIndexOf("/"));
    if (parent) {
      void loadDirectory(parent);
    }
  }, [currentPath, loadDirectory]);

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

    directoryEntries,
    expandedFolders,
    currentPath,
    isLoadingDirectory,
    directoryError,
    setDirectoryEntries,
    toggleFolder,
    loadDirectory,
    navigateUp,
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
