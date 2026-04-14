import {
  Code2Icon,
  CopyIcon,
  DownloadIcon,
  EyeIcon,
  GitCompareArrowsIcon,
  LoaderIcon,
  PackageIcon,
  SquareArrowOutUpRightIcon,
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
import { Select, SelectItem } from "@/components/ui/select";
import {
  SelectContent,
  SelectGroup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { CodeEditor } from "@/components/workspace/code-editor";
import { buildThreadFileHistory } from "@/core/artifacts/history";
import { useArtifactContent } from "@/core/artifacts/hooks";
import {
  getThreadFileDisplayPath,
  normalizeThreadHistoryFileKey,
  urlOfArtifact,
} from "@/core/artifacts/utils";
import { useI18n } from "@/core/i18n/hooks";
import { installSkill } from "@/core/skills/api";
import { streamdownPlugins } from "@/core/streamdown";
import { checkCodeFile, getFileName } from "@/core/utils/files";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { ArtifactLink } from "../citations/artifact-link";
import { useThread } from "../messages/context";
import { Tooltip } from "../tooltip";

import { ArtifactFileDiff } from "./artifact-file-diff";
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
  const { files, setOpen, select } = useArtifacts();
  const isWriteFile = useMemo(() => {
    return filepathFromProps.startsWith("write-file:");
  }, [filepathFromProps]);
  const filepath = useMemo(() => {
    if (isWriteFile) {
      const url = new URL(filepathFromProps);
      return decodeURIComponent(url.pathname);
    }
    return filepathFromProps;
  }, [filepathFromProps, isWriteFile]);
  const isSkillFile = useMemo(() => {
    return filepath.endsWith(".skill");
  }, [filepath]);
  const { isCodeFile, language } = useMemo(() => {
    if (isWriteFile) {
      let language = checkCodeFile(filepath).language;
      language ??= "text";
      return { isCodeFile: true, language };
    }
    // Treat .skill files as markdown (they contain SKILL.md)
    if (isSkillFile) {
      return { isCodeFile: true, language: "markdown" };
    }
    return checkCodeFile(filepath);
  }, [filepath, isWriteFile, isSkillFile]);
  const isSupportPreview = useMemo(() => {
    return language === "html" || language === "markdown";
  }, [language]);
  const { content } = useArtifactContent({
    threadId,
    filepath: filepathFromProps,
    enabled: isCodeFile && !isWriteFile,
  });

  const [viewMode, setViewMode] = useState<"code" | "preview" | "diff">("code");
  const [selectedVersionId, setSelectedVersionId] = useState("current");
  const [isInstalling, setIsInstalling] = useState(false);
  const { thread, isMock } = useThread();
  const history = useMemo(() => {
    return buildThreadFileHistory(thread.messages);
  }, [thread.messages]);
  const historySnapshots = useMemo(() => {
    if (isWriteFile) {
      return [];
    }
    return history[normalizeThreadHistoryFileKey(filepath)] ?? [];
  }, [filepath, history, isWriteFile]);
  const selectedSnapshot = useMemo(() => {
    if (selectedVersionId === "current") {
      return null;
    }
    return (
      historySnapshots.find((snapshot) => snapshot.id === selectedVersionId) ??
      null
    );
  }, [historySnapshots, selectedVersionId]);
  const isHistoricalView = selectedSnapshot !== null;
  const canRenderTextContent = isCodeFile || isHistoricalView;
  const canShowDiff =
    isHistoricalView && typeof selectedSnapshot?.previousContent === "string";
  const displayContent = selectedSnapshot?.content ?? content ?? "";

  useEffect(() => {
    if (viewMode === "preview" && !isSupportPreview) {
      setViewMode("code");
      return;
    }
    if (viewMode === "diff" && !canShowDiff) {
      setViewMode(isSupportPreview ? "preview" : "code");
    }
  }, [canShowDiff, isSupportPreview, viewMode]);
  useEffect(() => {
    setSelectedVersionId("current");
    setViewMode(isSupportPreview ? "preview" : "code");
  }, [filepathFromProps, isSupportPreview]);

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
  return (
    <Artifact className={cn(className)}>
      <ArtifactHeader className="px-2">
        <div className="flex items-center gap-2">
          <ArtifactTitle>
            <div className="flex min-w-0 flex-col gap-1 px-2">
              {isWriteFile ? (
                <div>{getFileName(filepath)}</div>
              ) : (
                <Select value={filepath} onValueChange={select}>
                  <SelectTrigger className="h-auto min-h-9 border-none bg-transparent! px-0 shadow-none select-none focus:outline-0 active:outline-0">
                    <SelectValue placeholder="Select a file" />
                  </SelectTrigger>
                  <SelectContent className="select-none">
                    <SelectGroup>
                      {(files ?? []).map((filepath) => (
                        <SelectItem key={filepath} value={filepath}>
                          {getThreadFileDisplayPath(filepath)}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              )}
              {!isWriteFile && historySnapshots.length > 0 && (
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground text-xs font-medium">
                    {t.common.version}
                  </span>
                  <Select
                    value={selectedVersionId}
                    onValueChange={setSelectedVersionId}
                  >
                    <SelectTrigger className="h-8 min-w-44 border-none bg-transparent! px-0 text-xs shadow-none focus:outline-0 active:outline-0">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="select-none">
                      <SelectGroup>
                        <SelectItem value="current">
                          {t.common.current}
                        </SelectItem>
                        {[...historySnapshots].reverse().map((snapshot) => (
                          <SelectItem key={snapshot.id} value={snapshot.id}>
                            {`${t.common.version} ${snapshot.version} · ${snapshot.operation}`}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                </div>
              )}
              {selectedSnapshot?.description && (
                <div className="text-muted-foreground text-xs">
                  {selectedSnapshot.description}
                </div>
              )}
            </div>
          </ArtifactTitle>
        </div>
        <div className="flex min-w-0 grow items-center justify-center">
          {(isSupportPreview || canShowDiff) && (
            <ToggleGroup
              className="mx-auto"
              type="single"
              variant="outline"
              size="sm"
              value={viewMode}
              onValueChange={(value) => {
                if (value) {
                  setViewMode(value as "code" | "preview" | "diff");
                }
              }}
            >
              <ToggleGroupItem value="code">
                <Code2Icon />
              </ToggleGroupItem>
              {isSupportPreview && (
                <ToggleGroupItem value="preview">
                  <EyeIcon />
                </ToggleGroupItem>
              )}
              {canShowDiff && (
                <ToggleGroupItem value="diff">
                  <GitCompareArrowsIcon />
                </ToggleGroupItem>
              )}
            </ToggleGroup>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ArtifactActions>
            {!isWriteFile && !isHistoricalView && filepath.endsWith(".skill") && (
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
            {!isWriteFile && !isHistoricalView && (
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
            {canRenderTextContent && (
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
            {!isWriteFile && !isHistoricalView && (
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
          (language === "markdown" || language === "html") && (
            <ArtifactFilePreview
              content={displayContent}
              language={language ?? "text"}
            />
          )}
        {canRenderTextContent && viewMode === "code" && (
          <CodeEditor
            className="size-full resize-none rounded-none border-none"
            value={displayContent ?? ""}
            readonly
          />
        )}
        {canShowDiff && viewMode === "diff" && selectedSnapshot && (
          <ArtifactFileDiff
            afterContent={selectedSnapshot.content}
            afterLabel={`${t.common.after} · ${t.common.version} ${selectedSnapshot.version}`}
            beforeContent={selectedSnapshot.previousContent ?? ""}
            beforeLabel={`${t.common.before} · ${t.common.version} ${selectedSnapshot.version - 1}`}
            title={t.common.diff}
          />
        )}
        {!canRenderTextContent && (
          <iframe
            className="size-full"
            src={urlOfArtifact({ filepath, threadId, isMock })}
          />
        )}
      </ArtifactContent>
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
