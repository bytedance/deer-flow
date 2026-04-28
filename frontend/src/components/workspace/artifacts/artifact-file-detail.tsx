import {
  Code2Icon,
  CopyIcon,
  DownloadIcon,
  EditIcon,
  EyeIcon,
  LoaderIcon,
  PackageIcon,
  SaveIcon,
  SquareArrowOutUpRightIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Streamdown } from "streamdown";

import {
  Artifact,
  ArtifactAction,
  ArtifactActions,
  ArtifactContent,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Select, SelectItem } from "@/components/ui/select";
import {
  SelectContent,
  SelectGroup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { CodeEditor } from "@/components/workspace/code-editor";
import { useArtifactContent } from "@/core/artifacts/hooks";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { deleteFile, readFile, writeFile } from "@/core/filesystem/api";
import { useI18n } from "@/core/i18n/hooks";
import { installSkill } from "@/core/skills/api";
import { streamdownPlugins } from "@/core/streamdown";
import { checkCodeFile, getFileName } from "@/core/utils/files";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { ArtifactLink } from "../citations/artifact-link";
import { useThread } from "../messages/context";
import { Tooltip } from "../tooltip";

import { useArtifacts } from "./context";

export function ArtifactFileDetail({
  className,
  filepath: filepathFromProps,
  threadId,
}: {
  className?: string;
  filepath: string;
  threadId: string;
}) {
  const { t } = useI18n();
  const { artifacts, setOpen, select, directoryEntries, setDirectoryEntries } =
    useArtifacts();

  const isWorkspaceFile = useMemo(() => {
    return filepathFromProps.startsWith("workspace:");
  }, [filepathFromProps]);

  const isWriteFile = useMemo(() => {
    return filepathFromProps.startsWith("write-file:");
  }, [filepathFromProps]);

  const filepath = useMemo(() => {
    if (isWriteFile) {
      const url = new URL(filepathFromProps);
      return decodeURIComponent(url.pathname);
    }
    if (isWorkspaceFile) {
      return filepathFromProps.replace("workspace:", "");
    }
    return filepathFromProps;
  }, [filepathFromProps, isWriteFile, isWorkspaceFile]);

  const isSkillFile = useMemo(() => {
    return filepath.endsWith(".skill");
  }, [filepath]);

  const { isCodeFile, language } = useMemo(() => {
    if (isWriteFile || isWorkspaceFile) {
      let language = checkCodeFile(filepath).language;
      language ??= "text";
      return { isCodeFile: true, language };
    }
    if (isSkillFile) {
      return { isCodeFile: true, language: "markdown" };
    }
    return checkCodeFile(filepath);
  }, [filepath, isWriteFile, isSkillFile, isWorkspaceFile]);

  const isSupportPreview = useMemo(() => {
    return language === "html" || language === "markdown";
  }, [language]);

  const { content: artifactContent } = useArtifactContent({
    threadId,
    filepath: filepathFromProps,
    enabled: isCodeFile && !isWriteFile && !isWorkspaceFile,
  });

  const [workspaceContent, setWorkspaceContent] = useState<string | null>(null);
  const [isLoadingWorkspaceContent, setIsLoadingWorkspaceContent] =
    useState(false);

  useEffect(() => {
    if (isWorkspaceFile && !workspaceContent) {
      setIsLoadingWorkspaceContent(true);
      readFile(threadId, filepath)
        .then((data) => {
          setWorkspaceContent(data.content);
        })
        .catch((error) => {
          console.error("Failed to read workspace file:", error);
          toast.error("Failed to load file");
        })
        .finally(() => {
          setIsLoadingWorkspaceContent(false);
        });
    }
  }, [isWorkspaceFile, filepath, threadId, workspaceContent]);

  const displayContent = workspaceContent ?? artifactContent ?? "";

  const [viewMode, setViewMode] = useState<"code" | "preview">("code");
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [isInstalling, setIsInstalling] = useState(false);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const { isMock } = useThread();

  useEffect(() => {
    if (isSupportPreview) {
      setViewMode("preview");
    } else {
      setViewMode("code");
    }
  }, [isSupportPreview]);

  useEffect(() => {
    if (isEditing) {
      setEditContent(displayContent);
    }
  }, [isEditing, displayContent]);

  const handleStartEdit = useCallback(() => {
    setIsEditing(true);
    setEditContent(displayContent);
  }, [displayContent]);

  const handleCancelEdit = useCallback(() => {
    setIsEditing(false);
    setEditContent("");
  }, []);

  const handleSave = useCallback(async () => {
    if (isSaving) return;
    setIsSaving(true);
    try {
      await writeFile(threadId, filepath, editContent);
      setWorkspaceContent(editContent);
      setIsEditing(false);
      toast.success("File saved successfully");
    } catch (error) {
      console.error("Failed to save file:", error);
      toast.error("Failed to save file");
    } finally {
      setIsSaving(false);
    }
  }, [threadId, filepath, editContent, isSaving]);

  const handleDelete = useCallback(async () => {
    if (isDeleting) return;
    setIsDeleting(true);
    try {
      await deleteFile(threadId, filepath);
      toast.success("File deleted successfully");
      setOpen(false);

      const parentPath = filepath.substring(0, filepath.lastIndexOf("/"));
      if (directoryEntries[parentPath]) {
        const updatedEntries = directoryEntries[parentPath].filter(
          (e) => e.path !== filepath,
        );
        setDirectoryEntries(parentPath, updatedEntries);
      }
    } catch (error) {
      console.error("Failed to delete file:", error);
      toast.error("Failed to delete file");
    } finally {
      setIsDeleting(false);
      setIsDeleteDialogOpen(false);
    }
  }, [
    threadId,
    filepath,
    isDeleting,
    setOpen,
    directoryEntries,
    setDirectoryEntries,
  ]);

  const handleInstallSkill = useCallback(async () => {
    if (isInstalling) return;

    setIsInstalling(true);
    try {
      const result = await installSkill({
        thread_id: threadId,
        path: filepath,
      });
      if (result.success) {
        toast.success(result.message);
      } else {
        toast.error(result.message ?? "Failed to install skill");
      }
    } catch (error) {
      console.error("Failed to install skill:", error);
      toast.error("Failed to install skill");
    } finally {
      setIsInstalling(false);
    }
  }, [threadId, filepath, isInstalling]);

  if (isLoadingWorkspaceContent && isWorkspaceFile) {
    return (
      <Artifact className={cn(className)}>
        <ArtifactContent className="flex items-center justify-center p-4">
          <LoaderIcon className="text-muted-foreground h-6 w-6 animate-spin" />
        </ArtifactContent>
      </Artifact>
    );
  }

  return (
    <Artifact className={cn(className)}>
      <ArtifactHeader className="px-2">
        <div className="flex items-center gap-2">
          <ArtifactTitle>
            {isWriteFile || isWorkspaceFile ? (
              <div className="px-2">{getFileName(filepath)}</div>
            ) : (
              <Select value={filepath} onValueChange={select}>
                <SelectTrigger className="border-none bg-transparent! shadow-none select-none focus:outline-0 active:outline-0">
                  <SelectValue placeholder="Select a file" />
                </SelectTrigger>
                <SelectContent className="select-none">
                  <SelectGroup>
                    {(artifacts ?? []).map((filepath) => (
                      <SelectItem key={filepath} value={filepath}>
                        {getFileName(filepath)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            )}
          </ArtifactTitle>
        </div>
        <div className="flex min-w-0 grow items-center justify-center">
          {isSupportPreview && !isEditing && (
            <ToggleGroup
              className="mx-auto"
              type="single"
              variant="outline"
              size="sm"
              value={viewMode}
              onValueChange={(value) => {
                if (value) {
                  setViewMode(value as "code" | "preview");
                }
              }}
            >
              <ToggleGroupItem value="code">
                <Code2Icon />
              </ToggleGroupItem>
              <ToggleGroupItem value="preview">
                <EyeIcon />
              </ToggleGroupItem>
            </ToggleGroup>
          )}
          {isEditing && (
            <span className="text-muted-foreground text-xs">Editing mode</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ArtifactActions>
            {isWorkspaceFile && !isEditing && (
              <Tooltip content="Edit file">
                <ArtifactAction
                  icon={EditIcon}
                  label="Edit"
                  tooltip="Edit file"
                  onClick={handleStartEdit}
                />
              </Tooltip>
            )}
            {isEditing && (
              <>
                <Tooltip content="Cancel">
                  <ArtifactAction
                    icon={XIcon}
                    label="Cancel"
                    tooltip="Cancel editing"
                    onClick={handleCancelEdit}
                  />
                </Tooltip>
                <Tooltip content="Save">
                  <ArtifactAction
                    icon={SaveIcon}
                    label="Save"
                    tooltip="Save file"
                    disabled={isSaving}
                    onClick={handleSave}
                  />
                </Tooltip>
              </>
            )}
            {isWorkspaceFile && !isEditing && (
              <Tooltip content="Delete file">
                <ArtifactAction
                  icon={Trash2Icon}
                  label="Delete"
                  tooltip="Delete file"
                  onClick={() => setIsDeleteDialogOpen(true)}
                />
              </Tooltip>
            )}
            {!isWriteFile &&
              !isWorkspaceFile &&
              filepath.endsWith(".skill") && (
                <Tooltip content={t.toolCalls.skillInstallTooltip}>
                  <ArtifactAction
                    icon={isInstalling ? LoaderIcon : PackageIcon}
                    label={t.common.install}
                    tooltip={t.common.install}
                    disabled={
                      isInstalling ||
                      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
                    }
                    onClick={handleInstallSkill}
                  />
                </Tooltip>
              )}
            {!isWriteFile && !isWorkspaceFile && (
              <ArtifactAction
                icon={SquareArrowOutUpRightIcon}
                label={t.common.openInNewWindow}
                tooltip={t.common.openInNewWindow}
                onClick={() => {
                  const w = window.open(
                    urlOfArtifact({ filepath, threadId, isMock }),
                    "_blank",
                    "noopener,noreferrer",
                  );
                  if (w) w.opener = null;
                }}
              />
            )}
            {isCodeFile && !isEditing && (
              <ArtifactAction
                icon={CopyIcon}
                label={t.clipboard.copyToClipboard}
                disabled={!displayContent}
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(displayContent ?? "");
                    toast.success(t.clipboard.copiedToClipboard);
                  } catch (error) {
                    toast.error("Failed to copy to clipboard");
                    console.error(error);
                  }
                }}
                tooltip={t.clipboard.copyToClipboard}
              />
            )}
            {!isWriteFile && !isWorkspaceFile && (
              <ArtifactAction
                icon={DownloadIcon}
                label={t.common.download}
                tooltip={t.common.download}
                onClick={() => {
                  const w = window.open(
                    urlOfArtifact({
                      filepath,
                      threadId,
                      download: true,
                      isMock,
                    }),
                    "_blank",
                    "noopener,noreferrer",
                  );
                  if (w) w.opener = null;
                }}
              />
            )}
            <ArtifactAction
              icon={XIcon}
              label={t.common.close}
              onClick={() => setOpen(false)}
              tooltip={t.common.close}
            />
          </ArtifactActions>
        </div>
      </ArtifactHeader>
      <ArtifactContent className="p-0">
        {isSupportPreview &&
          viewMode === "preview" &&
          (language === "markdown" || language === "html") &&
          !isEditing && (
            <ArtifactFilePreview
              content={displayContent}
              language={language ?? "text"}
            />
          )}
        {isCodeFile && viewMode === "code" && (
          <CodeEditor
            className="size-full resize-none rounded-none border-none"
            value={isEditing ? editContent : displayContent}
            readonly={!isEditing}
            onChange={isEditing ? setEditContent : undefined}
          />
        )}
        {!isCodeFile && !isEditing && (
          <iframe
            className="size-full"
            src={urlOfArtifact({ filepath, threadId, isMock })}
          />
        )}
      </ArtifactContent>

      <Dialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete File</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete &quot;{getFileName(filepath)}
              &quot;? This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsDeleteDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={isDeleting}
            >
              {isDeleting ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Artifact>
  );
}

export function ArtifactFilePreview({
  content,
  language,
}: {
  content: string;
  language: string;
}) {
  const [htmlPreviewUrl, setHtmlPreviewUrl] = useState<string>();

  useEffect(() => {
    if (language !== "html") {
      setHtmlPreviewUrl(undefined);
      return;
    }

    const blob = new Blob([content ?? ""], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    setHtmlPreviewUrl(url);

    return () => {
      URL.revokeObjectURL(url);
    };
  }, [content, language]);

  if (language === "markdown") {
    return (
      <div className="size-full px-4">
        <Streamdown
          className="size-full"
          {...streamdownPlugins}
          components={{ a: ArtifactLink }}
        >
          {content ?? ""}
        </Streamdown>
      </div>
    );
  }
  if (language === "html") {
    return (
      <iframe
        className="size-full"
        title="Artifact preview"
        sandbox="allow-scripts allow-forms"
        src={htmlPreviewUrl}
      />
    );
  }
  return null;
}
