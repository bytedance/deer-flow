import {
  ChevronRightIcon,
  DownloadIcon,
  FolderIcon,
  LoaderIcon,
  PackageIcon,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  buildArtifactFileTree,
  type ArtifactFileTreeNode,
} from "@/core/artifacts/file-tree";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { installSkill, SkillRequestError } from "@/core/skills/api";
import {
  getFileExtensionDisplayName,
  getFileIcon,
  getFileName,
} from "@/core/utils/files";
import { cn } from "@/lib/utils";

import { useArtifacts } from "./context";

type ArtifactTreeProps = {
  nodes: ArtifactFileTreeNode[];
  threadId: string;
  isAdmin: boolean;
  installingFile: string | null;
  installLabel: string;
  downloadLabel: string;
  selectedPath: string | null;
  onOpen: (path: string) => void;
  onInstall: (event: React.MouseEvent, path: string) => void;
};

function ArtifactTree({ nodes, ...props }: ArtifactTreeProps) {
  return (
    <ul role="tree" className="flex flex-col gap-0.5">
      {nodes.map((node) =>
        node.type === "directory" ? (
          <li
            key={`directory:${node.path}`}
            role="treeitem"
            aria-selected={false}
          >
            <Collapsible defaultOpen>
              <CollapsibleTrigger className="group hover:bg-muted flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm">
                <ChevronRightIcon className="size-4 shrink-0 transition-transform group-data-[state=open]:rotate-90" />
                <FolderIcon className="text-muted-foreground size-4 shrink-0" />
                <span className="min-w-0 truncate">{node.name}</span>
              </CollapsibleTrigger>
              <CollapsibleContent className="ml-4 border-l pl-2">
                <ArtifactTree nodes={node.children} {...props} />
              </CollapsibleContent>
            </Collapsible>
          </li>
        ) : (
          <li
            key={`file:${node.path}`}
            role="treeitem"
            aria-selected={props.selectedPath === node.path}
            className="hover:bg-muted group flex min-w-0 items-center rounded-md pr-1"
          >
            <Button
              variant="ghost"
              className="h-auto min-w-0 grow justify-start gap-2 px-2 py-1.5 font-normal"
              title={node.path}
              onClick={() => props.onOpen(node.path)}
            >
              {getFileIcon(node.path, "size-4 shrink-0")}
              <span className="min-w-0 truncate">{node.name}</span>
            </Button>
            {node.path.toLowerCase().endsWith(".skill") && props.isAdmin && (
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={`${props.installLabel} ${node.name}`}
                title={props.installLabel}
                disabled={props.installingFile === node.path}
                onClick={(event) => props.onInstall(event, node.path)}
              >
                {props.installingFile === node.path ? (
                  <LoaderIcon className="size-4 animate-spin" />
                ) : (
                  <PackageIcon className="size-4" />
                )}
              </Button>
            )}
            <Button size="icon-sm" variant="ghost" asChild>
              <a
                href={urlOfArtifact({
                  filepath: node.path,
                  threadId: props.threadId,
                  download: true,
                })}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`${props.downloadLabel} ${node.name}`}
                title={props.downloadLabel}
              >
                <DownloadIcon className="size-4" />
              </a>
            </Button>
          </li>
        ),
      )}
    </ul>
  );
}

export function ArtifactFileList({
  className,
  files,
  threadId,
  variant = "cards",
}: {
  className?: string;
  files: string[];
  threadId: string;
  variant?: "cards" | "tree";
}) {
  const { t } = useI18n();
  const { user } = useAuth();
  const isAdmin = user?.system_role === "admin";
  const { select: selectArtifact, selectedArtifact, setOpen } = useArtifacts();
  const [installingFile, setInstallingFile] = useState<string | null>(null);
  const tree = useMemo(() => buildArtifactFileTree(files), [files]);

  const handleClick = useCallback(
    (filepath: string) => {
      selectArtifact(filepath);
      setOpen(true);
    },
    [selectArtifact, setOpen],
  );

  const handleInstallSkill = useCallback(
    async (e: React.MouseEvent, filepath: string) => {
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
        if (error instanceof SkillRequestError && error.isAdminRequired) {
          toast.error(t.settings.skills.installAdminRequired);
        } else {
          toast.error("Failed to install skill");
        }
      } finally {
        setInstallingFile(null);
      }
    },
    [threadId, installingFile, t],
  );

  if (variant === "tree") {
    return (
      <div className={cn("w-full", className)}>
        <ArtifactTree
          nodes={tree}
          threadId={threadId}
          isAdmin={isAdmin}
          installingFile={installingFile}
          installLabel={t.common.install}
          downloadLabel={t.common.download}
          selectedPath={selectedArtifact}
          onOpen={handleClick}
          onInstall={handleInstallSkill}
        />
      </div>
    );
  }

  return (
    <ul className={cn("flex w-full flex-col gap-4", className)}>
      {files.map((file) => (
        <Card
          key={file}
          className="relative cursor-pointer p-3"
          onClick={() => handleClick(file)}
        >
          <CardHeader className="grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 pr-2 pl-1">
            <CardTitle className="relative min-w-0 pl-8 leading-tight [overflow-wrap:anywhere] break-words">
              <div className="min-w-0">{getFileName(file)}</div>
              <div className="absolute top-2 -left-0.5">
                {getFileIcon(file, "size-6")}
              </div>
            </CardTitle>
            <CardDescription className="min-w-0 pl-8 text-xs">
              {getFileExtensionDisplayName(file)} file
            </CardDescription>
            <CardAction className="row-span-1 self-center">
              {file.endsWith(".skill") && isAdmin && (
                <Button
                  variant="ghost"
                  disabled={installingFile === file}
                  onClick={(e) => handleInstallSkill(e, file)}
                >
                  {installingFile === file ? (
                    <LoaderIcon className="size-4 animate-spin" />
                  ) : (
                    <PackageIcon className="size-4" />
                  )}
                  {t.common.install}
                </Button>
              )}
              <Button variant="ghost" asChild>
                <a
                  href={urlOfArtifact({
                    filepath: file,
                    threadId: threadId,
                    download: true,
                  })}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                >
                  <DownloadIcon className="size-4" />
                  {t.common.download}
                </a>
              </Button>
            </CardAction>
          </CardHeader>
        </Card>
      ))}
    </ul>
  );
}
