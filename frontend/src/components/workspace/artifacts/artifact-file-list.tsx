import {
  ChevronRightIcon,
  FolderIcon,
  FolderOpenIcon,
  Loader2Icon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { getFileIcon } from "@/core/utils/files";
import { cn } from "@/lib/utils";

import { useArtifacts } from "./context";

export function ArtifactFileList({
  className,
  threadId,
}: {
  className?: string;
  threadId: string;
}) {
  const {
    directoryEntries,
    expandedFolders,
    currentPath,
    isLoadingDirectory,
    select,
    toggleFolder,
    loadDirectory,
    navigateUp,
  } = useArtifacts();

  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    console.log(
      "📂 ArtifactFileList mounted, loading directory for thread:",
      threadId,
    );
    setError(null);
    void loadDirectory("/mnt/user-data/workspace").catch((err) => {
      console.error("❌ Failed to load workspace directory:", err);
      setError(
        "Failed to connect to backend API. Make sure the backend server is running.",
      );
    });
  }, [threadId, loadDirectory]);

  const entries = directoryEntries[currentPath] ?? [];
  const hasParent = currentPath !== "/mnt/user-data/workspace";

  const handleSelect = useCallback(
    (file: string) => {
      select(`workspace:${file}`);
    },
    [select],
  );

  const handleToggleFolder = useCallback(
    (path: string) => {
      toggleFolder(path);
      if (!expandedFolders.has(path) && !directoryEntries[path]) {
        void loadDirectory(path);
      }
    },
    [toggleFolder, expandedFolders, directoryEntries, loadDirectory],
  );

  const renderEntry = (
    entry: { name: string; path: string; isDirectory: boolean },
    depth = 0,
  ) => {
    const isExpanded = expandedFolders.has(entry.path);
    const paddingLeft = depth * 16 + 8;

    if (entry.isDirectory) {
      return (
        <div key={entry.path}>
          <div
            className={cn(
              "hover:bg-accent flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5",
            )}
            style={{ paddingLeft }}
            onClick={() => handleToggleFolder(entry.path)}
          >
            {isExpanded ? (
              <FolderOpenIcon className="text-muted-foreground h-4 w-4 shrink-0" />
            ) : (
              <FolderIcon className="text-muted-foreground h-4 w-4 shrink-0" />
            )}
            <span className="truncate text-sm font-medium">{entry.name}</span>
            <ChevronRightIcon
              className={cn(
                "text-muted-foreground ml-auto h-4 w-4 shrink-0 transition-transform",
                isExpanded && "rotate-90",
              )}
            />
          </div>
          {isExpanded && directoryEntries[entry.path] && (
            <div>
              {directoryEntries[entry.path].map((child) =>
                renderEntry(child, depth + 1),
              )}
            </div>
          )}
        </div>
      );
    }

    return (
      <div
        key={entry.path}
        className={cn(
          "hover:bg-accent flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5",
        )}
        style={{ paddingLeft }}
        onClick={() => handleSelect(entry.path)}
      >
        {getFileIcon(entry.name, "h-4 w-4 shrink-0")}
        <span className="truncate text-sm">{entry.name}</span>
      </div>
    );
  };

  return (
    <div className={cn("size-full overflow-auto", className)}>
      {/* Navigation bar */}
      <div className="bg-background sticky top-0 z-10 flex items-center gap-2 border-b px-2 py-2">
        {hasParent && (
          <Button
            variant="ghost"
            size="sm"
            onClick={navigateUp}
            className="h-7 px-2 text-xs"
          >
            ↑ Up
          </Button>
        )}
        <span className="text-muted-foreground truncate text-xs">
          {currentPath}
        </span>
      </div>

      {/* Content */}
      <div className="p-2">
        {isLoadingDirectory ? (
          <div className="text-muted-foreground flex items-center justify-center gap-2 py-8 text-sm">
            <Loader2Icon className="h-4 w-4 animate-spin" />
            Loading...
          </div>
        ) : error ? (
          <div className="text-destructive py-8 text-center text-sm">
            {error}
          </div>
        ) : entries.length === 0 ? (
          <div className="text-muted-foreground py-8 text-center text-sm">
            No files found in this directory
          </div>
        ) : (
          entries.map((entry) => renderEntry(entry))
        )}
      </div>
    </div>
  );
}
