import {
  ChevronDownIcon,
  ChevronRightIcon,
  DownloadIcon,
  FolderIcon,
  FolderOpenIcon,
  LoaderIcon,
  PackageIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type MouseEvent,
} from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  buildThreadFileTree,
  collectThreadFileTreeFolderIds,
  getThreadFileDisplayPath,
  type ThreadFileTreeNode,
  urlOfArtifact,
} from "@/core/artifacts/utils";
import { useI18n } from "@/core/i18n/hooks";
import { installSkill } from "@/core/skills/api";
import { getFileIcon } from "@/core/utils/files";
import { cn } from "@/lib/utils";

import { useArtifacts } from "./context";

export function ArtifactFileList({
  className,
  files,
  threadId,
}: {
  className?: string;
  files: string[];
  threadId: string;
}) {
  const tree = useMemo(() => buildThreadFileTree(files), [files]);
  const defaultExpandedFolderIds = useMemo(
    () => collectThreadFileTreeFolderIds(tree),
    [tree],
  );
  const [expandedFolderIds, setExpandedFolderIds] = useState<Set<string>>(
    () => new Set(defaultExpandedFolderIds),
  );

  useEffect(() => {
    setExpandedFolderIds((current) => {
      const next = new Set(current);
      for (const folderId of defaultExpandedFolderIds) {
        next.add(folderId);
      }
      return next;
    });
  }, [defaultExpandedFolderIds]);

  return (
    <ul className={cn("flex w-full flex-col gap-1", className)}>
      {tree.map((node) => (
        <ArtifactFileTreeNode
          key={node.id}
          expandedFolderIds={expandedFolderIds}
          node={node}
          onToggleFolder={(folderId) => {
            setExpandedFolderIds((current) => {
              const next = new Set(current);
              if (next.has(folderId)) {
                next.delete(folderId);
              } else {
                next.add(folderId);
              }
              return next;
            });
          }}
          threadId={threadId}
        />
      ))}
    </ul>
  );
}

function ArtifactFileTreeNode({
  expandedFolderIds,
  node,
  onToggleFolder,
  threadId,
}: {
  expandedFolderIds: Set<string>;
  node: ThreadFileTreeNode;
  onToggleFolder: (folderId: string) => void;
  threadId: string;
}) {
  if (node.kind === "folder") {
    const isExpanded = expandedFolderIds.has(node.id);

    return (
      <li className="flex flex-col gap-1">
        <button
          className="hover:bg-muted/60 flex h-9 items-center gap-2 rounded-md px-2 text-left text-sm transition-colors"
          onClick={() => onToggleFolder(node.id)}
          type="button"
        >
          {isExpanded ? (
            <ChevronDownIcon className="text-muted-foreground size-4 shrink-0" />
          ) : (
            <ChevronRightIcon className="text-muted-foreground size-4 shrink-0" />
          )}
          {isExpanded ? (
            <FolderOpenIcon className="text-muted-foreground size-4 shrink-0" />
          ) : (
            <FolderIcon className="text-muted-foreground size-4 shrink-0" />
          )}
          <span className="truncate font-medium">{node.name}</span>
        </button>
        {isExpanded && (
          <ul className="ml-4 flex flex-col gap-1 border-l pl-2">
            {node.children.map((child) => (
              <ArtifactFileTreeNode
                key={child.id}
                expandedFolderIds={expandedFolderIds}
                node={child}
                onToggleFolder={onToggleFolder}
                threadId={threadId}
              />
            ))}
          </ul>
        )}
      </li>
    );
  }

  return <ArtifactFileRow filepath={node.filepath} threadId={threadId} />;
}

function ArtifactFileRow({
  filepath,
  threadId,
}: {
  filepath: string;
  threadId: string;
}) {
  const { t } = useI18n();
  const {
    select: selectArtifact,
    selectedArtifact,
    setOpen,
  } = useArtifacts();
  const [installingFile, setInstallingFile] = useState<string | null>(null);

  const handleClick = useCallback(() => {
    selectArtifact(filepath);
    setOpen(true);
  }, [filepath, selectArtifact, setOpen]);

  const handleInstallSkill = useCallback(
    async (e: MouseEvent<HTMLButtonElement>) => {
      e.stopPropagation();
      e.preventDefault();

      if (installingFile) return;

      setInstallingFile(filepath);
      try {
        const result = await installSkill({
          thread_id: threadId,
          path: filepath,
        });
        if (result.success) {
          toast.success(result.message);
        } else {
          toast.error(result.message || "Failed to install skill");
        }
      } catch (error) {
        console.error("Failed to install skill:", error);
        toast.error("Failed to install skill");
      } finally {
        setInstallingFile(null);
      }
    },
    [filepath, installingFile, threadId],
  );

  const isSelected = selectedArtifact === filepath;

  return (
    <li>
      <div
        className={cn(
          "group hover:bg-muted/60 flex min-h-9 items-center gap-2 rounded-md px-2 text-sm transition-colors",
          isSelected && "bg-muted",
        )}
      >
        <button
          className="flex min-w-0 grow items-center gap-2 py-2 text-left"
          onClick={handleClick}
          title={getThreadFileDisplayPath(filepath)}
          type="button"
        >
          <span className="shrink-0">{getFileIcon(filepath, "size-4")}</span>
          <span className="truncate">{filepath.split("/").pop()}</span>
        </button>
        <div className="flex shrink-0 items-center gap-1 opacity-100 md:opacity-0 md:transition-opacity md:group-hover:opacity-100">
          {filepath.endsWith(".skill") && (
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={installingFile === filepath}
              onClick={handleInstallSkill}
            >
              {installingFile === filepath ? (
                <LoaderIcon className="size-4 animate-spin" />
              ) : (
                <PackageIcon className="size-4" />
              )}
              <span className="sr-only">{t.common.install}</span>
            </Button>
          )}
          <Button variant="ghost" size="icon-sm" asChild>
            <a
              href={urlOfArtifact({
                filepath,
                threadId,
                download: true,
              })}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
            >
              <DownloadIcon className="size-4" />
              <span className="sr-only">{t.common.download}</span>
            </a>
          </Button>
        </div>
      </div>
    </li>
  );
}
