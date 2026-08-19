import { useQueryClient } from "@tanstack/react-query";
import {
  Code2Icon,
  CopyIcon,
  DownloadIcon,
  EyeIcon,
  LoaderIcon,
  PackageIcon,
  PencilIcon,
  PencilOffIcon,
  RotateCcwIcon,
  SaveIcon,
  SquareArrowOutUpRightIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
  Artifact,
  ArtifactAction,
  ArtifactActions,
  ArtifactContent,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact";
import { Button } from "@/components/ui/button";
import { Select, SelectItem } from "@/components/ui/select";
import {
  SelectContent,
  SelectGroup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { CodeEditor } from "@/components/workspace/code-editor";
import {
  ArtifactRequestError,
  updateArtifactContent,
} from "@/core/artifacts/api";
import {
  canEditOpenedArtifact,
  createArtifactDraft,
  reconcileArtifactDraft,
} from "@/core/artifacts/editing";
import { useArtifactContent } from "@/core/artifacts/hooks";
import {
  appendHtmlPreviewBaseHref,
  appendHtmlPreviewScrollRestoration,
  createHtmlPreviewScrollKey,
  getArtifactViewState,
  HTML_PREVIEW_SCROLL_MESSAGE_SOURCE,
} from "@/core/artifacts/preview";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { useAuth } from "@/core/auth/AuthProvider";
import { extractCitationSources } from "@/core/citations/sources";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import { findToolCallResult } from "@/core/messages/utils";
import { installSkill, SkillRequestError } from "@/core/skills/api";
import {
  SafeStreamdown,
  toStreamdownComponents,
} from "@/core/streamdown/components";
import {
  canBrowserPreviewFile,
  checkCodeFile,
  getFileExtensionDisplayName,
  getFileIcon,
  getFileName,
} from "@/core/utils/files";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { ArtifactLink } from "../citations/artifact-link";
import { CitationSourcesPanel } from "../citations/citation-sources-panel";
import { useThread } from "../messages/context";
import { Tooltip } from "../tooltip";

import { useArtifacts } from "./context";
import { artifactMarkdownPlugins } from "./markdown-preview-plugins";

const WRITE_FILE_PREVIEW_REFRESH_INTERVAL_MS = 3000;

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
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isAdmin = user?.system_role === "admin";
  const {
    artifacts,
    setOpen,
    select,
    drafts,
    setDrafts,
    editingPath,
    setEditingPath,
  } = useArtifacts();
  const { thread, isMock } = useThread();
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
  // Keep these local because ChatBox replaces context artifacts with thread state.
  const [openedPresentedFilepaths, setOpenedPresentedFilepaths] = useState<
    string[]
  >(() => {
    if (isWriteFile || artifacts.includes(filepath)) {
      return [];
    }
    return [filepath];
  });
  useEffect(() => {
    if (isWriteFile || artifacts.includes(filepath)) {
      return;
    }
    setOpenedPresentedFilepaths((current) => {
      if (current.includes(filepath)) {
        return current;
      }
      return [...current, filepath];
    });
  }, [artifacts, filepath, isWriteFile]);
  const artifactOptions = useMemo(() => {
    if (isWriteFile) {
      return artifacts;
    }
    const currentIsPresented = !artifacts.includes(filepath);
    const presentedFilepaths =
      currentIsPresented && !openedPresentedFilepaths.includes(filepath)
        ? [...openedPresentedFilepaths, filepath]
        : openedPresentedFilepaths;
    const presentedSet = new Set(presentedFilepaths);
    return [
      ...presentedFilepaths,
      ...artifacts.filter((artifact) => !presentedSet.has(artifact)),
    ];
  }, [artifacts, filepath, isWriteFile, openedPresentedFilepaths]);
  const isSkillFile = useMemo(() => {
    return filepath.endsWith(".skill");
  }, [filepath]);
  const { isCodeFile, language } = useMemo(() => {
    if (isWriteFile) {
      const codeResult = checkCodeFile(filepath);
      // Non-code browser-previewable files (PDF, images, audio, video)
      // should render in the sandboxed iframe, not the code editor.
      if (!codeResult.isCodeFile && canBrowserPreviewFile(filepath)) {
        return codeResult;
      }
      let language = codeResult.language;
      language ??= "text";
      return { isCodeFile: true, language };
    }
    // Treat .skill files as markdown (they contain SKILL.md)
    if (isSkillFile) {
      return { isCodeFile: true, language: "markdown" };
    }
    return checkCodeFile(filepath);
  }, [filepath, isWriteFile, isSkillFile]);
  const canPreviewInBrowser = useMemo(() => {
    return canBrowserPreviewFile(filepath);
  }, [filepath]);
  const isSupportPreview = useMemo(() => {
    return language === "html" || language === "markdown";
  }, [language]);
  const toolResult = (() => {
    if (!isWriteFile) {
      return undefined;
    }
    const url = new URL(filepathFromProps);
    const toolCallId = url.searchParams.get("tool_call_id");
    if (!toolCallId) {
      return undefined;
    }
    return findToolCallResult(toolCallId, thread.messages);
  })();
  const artifactViewState = getArtifactViewState({
    filepath: filepathFromProps,
    isSupportPreview,
    toolResult,
  });
  const {
    content,
    url,
    sha256,
    truncated,
    previewBytes,
    totalBytes,
    fullContentRequested,
    loadFullContent,
    isLoading,
    error,
  } = useArtifactContent({
    threadId,
    filepath: filepathFromProps,
    enabled: isCodeFile && !isWriteFile,
  });

  const displayContent = content ?? "";
  const isWritingFile = isWriteFile && toolResult === undefined;
  const visibleContent = useThrottledValue(
    displayContent,
    isWritingFile ? WRITE_FILE_PREVIEW_REFRESH_INTERVAL_MS : 0,
    filepathFromProps,
  );

  const [isSaving, setIsSaving] = useState(false);
  const activeDraft = drafts[filepath] ?? createArtifactDraft(filepath);
  const isDirty = activeDraft.draftContent !== activeDraft.baselineContent;
  const hasUnsavedDrafts = Object.values(drafts).some(
    (draft) => draft.draftContent !== draft.baselineContent,
  );
  const isEditing = editingPath === filepath;
  const canEdit = canEditOpenedArtifact({
    filepath,
    isCodeFile,
    isWriteFile,
    isSkillFile,
    isMock: Boolean(isMock),
    hasRevision: typeof sha256 === "string" && sha256.length === 64,
    isStaticWebsite: env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true",
  });
  const editorContent = isDirty ? activeDraft.draftContent : visibleContent;

  useEffect(() => {
    if (content === undefined || sha256 === undefined || isWriteFile) {
      return;
    }
    setDrafts((current) => {
      const existing = current[filepath] ?? createArtifactDraft(filepath);
      const next = reconcileArtifactDraft(existing, { content, sha256 });
      if (next === existing) {
        return current;
      }
      return { ...current, [filepath]: next };
    });
  }, [content, filepath, isWriteFile, setDrafts, sha256]);

  const [viewMode, setViewMode] = useState<"code" | "preview">(
    artifactViewState.initialViewMode,
  );
  const [isInstalling, setIsInstalling] = useState(false);
  const isLoadingFullContent = fullContentRequested && isLoading;
  const effectiveViewMode =
    truncated && language === "html" ? "code" : viewMode;
  useEffect(() => {
    setViewMode(artifactViewState.initialViewMode);
  }, [artifactViewState.initialViewMode]);

  const confirmDiscard = useCallback(() => {
    return !isDirty || window.confirm(t.artifactEditing.discardChanges);
  }, [isDirty, t.artifactEditing.discardChanges]);

  const discardDraft = useCallback(() => {
    const latestContent = content ?? activeDraft.baselineContent;
    const latestSha256 = sha256 ?? activeDraft.baselineSha256;
    setDrafts((current) => ({
      ...current,
      [filepath]: {
        ...activeDraft,
        baselineContent: latestContent,
        baselineSha256: latestSha256,
        draftContent: latestContent,
        conflict: false,
      },
    }));
    setEditingPath(null);
  }, [activeDraft, content, filepath, setDrafts, setEditingPath, sha256]);

  const handleSave = useCallback(async () => {
    if (
      !canEdit ||
      !isDirty ||
      isSaving ||
      thread.isLoading ||
      activeDraft.conflict ||
      activeDraft.baselineSha256 === null
    ) {
      return;
    }

    setIsSaving(true);
    try {
      const result = await updateArtifactContent({
        threadId,
        filepath,
        content: activeDraft.draftContent,
        expectedSha256: activeDraft.baselineSha256,
      });
      const savedContent = activeDraft.draftContent;
      setDrafts((current) => ({
        ...current,
        [filepath]: {
          filepath,
          baselineContent: savedContent,
          baselineSha256: result.sha256,
          draftContent: savedContent,
          conflict: false,
        },
      }));
      queryClient.setQueryData(
        ["artifact", filepathFromProps, threadId, isMock, fullContentRequested],
        (
          current:
            | { content?: string; url?: string; sha256?: string }
            | undefined,
        ) => ({
          ...current,
          content: savedContent,
          sha256: result.sha256,
        }),
      );
      toast.success(t.artifactEditing.saved);
    } catch (error) {
      if (error instanceof ArtifactRequestError && error.status === 412) {
        setDrafts((current) => ({
          ...current,
          [filepath]: { ...(current[filepath] ?? activeDraft), conflict: true },
        }));
        void queryClient.invalidateQueries({
          queryKey: ["artifact", filepathFromProps, threadId, isMock],
        });
        toast.error(t.artifactEditing.conflict);
      } else if (
        error instanceof ArtifactRequestError &&
        error.status === 409
      ) {
        toast.error(t.artifactEditing.runInProgress);
      } else {
        toast.error(
          error instanceof Error ? error.message : t.artifactEditing.saveFailed,
        );
      }
    } finally {
      setIsSaving(false);
    }
  }, [
    activeDraft,
    canEdit,
    filepath,
    filepathFromProps,
    fullContentRequested,
    isDirty,
    isMock,
    isSaving,
    queryClient,
    setDrafts,
    t.artifactEditing,
    thread.isLoading,
    threadId,
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
      if (error instanceof SkillRequestError && error.isAdminRequired) {
        toast.error(t.settings.skills.installAdminRequired);
      } else {
        toast.error("Failed to install skill");
      }
    } finally {
      setIsInstalling(false);
    }
  }, [threadId, filepath, isInstalling, t]);
  return (
    <Artifact className={cn(className)}>
      <ArtifactHeader className="px-2">
        <div className="flex items-center gap-2">
          <ArtifactTitle>
            {isWriteFile ? (
              <div className="px-2">{getFileName(filepath)}</div>
            ) : (
              <Select
                value={filepath}
                onValueChange={(nextFilepath) => {
                  if (confirmDiscard()) {
                    if (isDirty) {
                      discardDraft();
                    }
                    select(nextFilepath);
                  }
                }}
              >
                <SelectTrigger className="border-none bg-transparent! shadow-none select-none focus:outline-0 active:outline-0">
                  <SelectValue placeholder="Select a file" />
                </SelectTrigger>
                <SelectContent className="select-none">
                  <SelectGroup>
                    {artifactOptions.map((option) => (
                      <SelectItem key={option} value={option}>
                        {getFileName(option)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            )}
          </ArtifactTitle>
        </div>
        <div className="flex min-w-0 grow items-center justify-center gap-2">
          {artifactViewState.canPreview && !truncated && (
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
          {(isSaving || isDirty || activeDraft.conflict) && (
            <span
              className={cn(
                "text-muted-foreground max-w-32 truncate text-xs",
                activeDraft.conflict && "text-destructive",
              )}
              aria-live="polite"
            >
              {isSaving
                ? t.artifactEditing.saving
                : activeDraft.conflict
                  ? t.artifactEditing.conflictShort
                  : t.artifactEditing.unsaved}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ArtifactActions>
            {canEdit && !isEditing && (
              <ArtifactAction
                icon={PencilIcon}
                label={t.common.edit}
                tooltip={t.common.edit}
                disabled={thread.isLoading}
                onClick={() => {
                  setViewMode("code");
                  setEditingPath(filepath);
                }}
              />
            )}
            {canEdit && isEditing && (
              <>
                <ArtifactAction
                  className={cn(
                    isDirty && !activeDraft.conflict && "text-primary",
                  )}
                  icon={isSaving ? LoaderIcon : SaveIcon}
                  label={t.common.save}
                  tooltip={
                    thread.isLoading
                      ? t.artifactEditing.runInProgress
                      : activeDraft.conflict
                        ? t.artifactEditing.conflict
                        : t.common.save
                  }
                  disabled={
                    !isDirty ||
                    isSaving ||
                    thread.isLoading ||
                    activeDraft.conflict
                  }
                  onClick={() => void handleSave()}
                />
                <ArtifactAction
                  icon={PencilOffIcon}
                  label={t.artifactEditing.exit}
                  tooltip={t.artifactEditing.exit}
                  disabled={isSaving}
                  onClick={() => setEditingPath(null)}
                />
                <ArtifactAction
                  icon={RotateCcwIcon}
                  label={t.artifactEditing.discard}
                  tooltip={t.artifactEditing.discard}
                  disabled={isSaving}
                  onClick={() => {
                    if (confirmDiscard()) {
                      discardDraft();
                    }
                  }}
                />
              </>
            )}
            {!isEditing &&
              !isWriteFile &&
              filepath.endsWith(".skill") &&
              isAdmin && (
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
            {!isEditing && !isWriteFile && (
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
            {!isEditing && isCodeFile && (
              <ArtifactAction
                icon={CopyIcon}
                label={t.clipboard.copyToClipboard}
                disabled={!content || truncated}
                onClick={() => {
                  void (async () => {
                    const didCopy = await writeTextToClipboard(
                      editorContent ?? "",
                    );
                    if (!didCopy) {
                      toast.error(t.clipboard.failedToCopyToClipboard);
                      return;
                    }

                    toast.success(t.clipboard.copiedToClipboard);
                  })().catch(() => {
                    toast.error(t.clipboard.failedToCopyToClipboard);
                  });
                }}
                tooltip={t.clipboard.copyToClipboard}
              />
            )}
            {!isEditing && !isWriteFile && (
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
              onClick={() => {
                if (
                  !hasUnsavedDrafts ||
                  window.confirm(t.artifactEditing.discardChanges)
                ) {
                  setDrafts({});
                  setEditingPath(null);
                  setOpen(false);
                }
              }}
              tooltip={t.common.close}
            />
          </ArtifactActions>
        </div>
      </ArtifactHeader>
      <ArtifactContent className="flex flex-col p-0">
        {truncated && (
          <div className="border-border bg-muted/40 flex shrink-0 items-center justify-between gap-3 border-b px-4 py-2 text-sm">
            <span className="text-muted-foreground">
              {t.artifactPreview.limited(
                formatArtifactBytes(previewBytes) ?? "1 MiB",
                formatArtifactBytes(totalBytes),
              )}
            </span>
            <Button size="sm" variant="outline" onClick={loadFullContent}>
              {t.artifactPreview.loadFullFile}
            </Button>
          </div>
        )}
        {isLoadingFullContent && (
          <div className="border-border text-muted-foreground flex shrink-0 items-center gap-2 border-b px-4 py-2 text-sm">
            <LoaderIcon className="size-4 animate-spin" />
            {t.artifactPreview.loadingFullFile}
          </div>
        )}
        <div className="min-h-0 flex-1">
          {error && (
            <ArtifactPreviewError
              filepath={filepath}
              threadId={threadId}
              isMock={isMock}
              message={t.artifactPreview.previewFailed}
              downloadLabel={t.common.download}
            />
          )}
          {artifactViewState.canPreview &&
            !error &&
            effectiveViewMode === "preview" &&
            !isLoading &&
            (!truncated || language === "markdown") &&
            (language === "markdown" || language === "html") && (
              <ArtifactFilePreview
                content={editorContent}
                language={language}
                scrollKey={filepathFromProps}
                url={url}
              />
            )}
          {isCodeFile &&
            !error &&
            effectiveViewMode === "code" &&
            !truncated &&
            !isLoading && (
              <CodeEditor
                className="size-full resize-none rounded-none border-none"
                value={editorContent ?? ""}
                readonly={!isEditing}
                disabled={thread.isLoading || isSaving}
                autoFocus={isEditing}
                onChange={(nextContent) => {
                  setDrafts((current) => ({
                    ...current,
                    [filepath]: {
                      ...(current[filepath] ?? activeDraft),
                      draftContent: nextContent,
                    },
                  }));
                }}
                onSave={() => void handleSave()}
                language={language}
              />
            )}
          {isCodeFile &&
            !error &&
            truncated &&
            effectiveViewMode === "code" && (
              <pre className="size-full overflow-auto p-4 font-mono text-sm whitespace-pre-wrap">
                {visibleContent}
              </pre>
            )}
          {!isCodeFile && canPreviewInBrowser && (
            <iframe
              className="size-full"
              sandbox=""
              src={urlOfArtifact({ filepath, threadId, isMock })}
            />
          )}
          {!isCodeFile && !canPreviewInBrowser && (
            <ArtifactDownloadFallback
              filepath={filepath}
              threadId={threadId}
              isMock={isMock}
            />
          )}
        </div>
      </ArtifactContent>
    </Artifact>
  );
}

function ArtifactPreviewError({
  filepath,
  threadId,
  isMock,
  message,
  downloadLabel,
}: {
  filepath: string;
  threadId: string;
  isMock?: boolean;
  message: string;
  downloadLabel: string;
}) {
  return (
    <div className="flex size-full items-center justify-center p-6">
      <div className="flex max-w-sm flex-col items-center gap-4 text-center">
        <p className="text-muted-foreground text-sm">{message}</p>
        <Button asChild>
          <a
            href={urlOfArtifact({
              filepath,
              threadId,
              download: true,
              isMock,
            })}
            target="_blank"
            rel="noopener noreferrer"
          >
            <DownloadIcon className="size-4" />
            {downloadLabel}
          </a>
        </Button>
      </div>
    </div>
  );
}

function formatArtifactBytes(bytes: number | undefined) {
  if (bytes === undefined) return undefined;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function ArtifactDownloadFallback({
  filepath,
  threadId,
  isMock,
}: {
  filepath: string;
  threadId: string;
  isMock?: boolean;
}) {
  const filename = getFileName(filepath);
  const fileType = getFileExtensionDisplayName(filepath);

  return (
    <div className="flex size-full items-center justify-center p-6">
      <div className="flex max-w-sm flex-col items-center gap-4 text-center">
        <div className="text-muted-foreground">
          {getFileIcon(filepath, "size-12")}
        </div>
        <div className="space-y-1">
          <div className="font-medium break-all">{filename}</div>
          <div className="text-muted-foreground text-sm">{fileType} file</div>
        </div>
        <p className="text-muted-foreground text-sm">
          This file type cannot be previewed in the browser.
        </p>
        <Button asChild>
          <a
            href={urlOfArtifact({
              filepath,
              threadId,
              download: true,
              isMock,
            })}
            target="_blank"
            rel="noopener noreferrer"
          >
            <DownloadIcon className="size-4" />
            Download
          </a>
        </Button>
      </div>
    </div>
  );
}

export function ArtifactFilePreview({
  content,
  language,
  scrollKey,
  url,
}: {
  content: string;
  language: string;
  scrollKey: string;
  url?: string;
}) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const scrollPositionRef = useRef({ x: 0, y: 0 });
  const scrollMessageKey = useMemo(
    () => createHtmlPreviewScrollKey(scrollKey),
    [scrollKey],
  );
  const [htmlPreviewUrl, setHtmlPreviewUrl] = useState<string>();
  const citationSources = useMemo(
    () =>
      language === "markdown" ? extractCitationSources(content ?? "") : [],
    [content, language],
  );

  useEffect(() => {
    scrollPositionRef.current = { x: 0, y: 0 };
  }, [scrollMessageKey]);

  useEffect(() => {
    if (language !== "html") {
      return;
    }

    const handleMessage = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow) {
        return;
      }
      if (!isArtifactScrollMessage(event.data, scrollMessageKey)) {
        return;
      }

      if (event.data.type === "save") {
        const x = scrollCoordinate(event.data.x);
        const y = scrollCoordinate(event.data.y);
        if (x !== undefined && y !== undefined) {
          scrollPositionRef.current = { x, y };
        }
        return;
      }

      iframeRef.current?.contentWindow?.postMessage(
        {
          source: HTML_PREVIEW_SCROLL_MESSAGE_SOURCE,
          key: scrollMessageKey,
          type: "restore",
          ...scrollPositionRef.current,
        },
        "*",
      );
    };

    window.addEventListener("message", handleMessage);
    return () => {
      window.removeEventListener("message", handleMessage);
    };
  }, [language, scrollMessageKey]);

  useEffect(() => {
    if (language !== "html") {
      setHtmlPreviewUrl(undefined);
      return;
    }

    const previewContent = appendHtmlPreviewScrollRestoration(
      appendHtmlPreviewBaseHref(content ?? "", url),
      scrollKey,
    );
    const blob = new Blob([previewContent], {
      type: "text/html;charset=utf-8",
    });
    const objectUrl = URL.createObjectURL(blob);
    setHtmlPreviewUrl(objectUrl);

    return () => {
      URL.revokeObjectURL(objectUrl);
    };
  }, [content, language, scrollKey, url]);

  if (language === "markdown") {
    return (
      <div className="size-full overflow-auto px-4 py-3">
        <SafeStreamdown
          className="min-w-0"
          {...artifactMarkdownPlugins}
          components={toStreamdownComponents({ a: ArtifactLink })}
        >
          {content ?? ""}
        </SafeStreamdown>
        <CitationSourcesPanel sources={citationSources} className="mb-4" />
      </div>
    );
  }
  if (language === "html") {
    return (
      <iframe
        ref={iframeRef}
        className="size-full"
        title="Artifact preview"
        // allow-scripts is needed for the scroll-restoration injected
        // script (appendHtmlPreviewScrollRestoration) which communicates
        // via postMessage. allow-same-origin is deliberately omitted: the
        // opaque origin prevents access to parent.document and cookies,
        // and postMessage(..., "*") works fine from it.
        sandbox="allow-scripts allow-forms"
        src={htmlPreviewUrl}
      />
    );
  }
  return null;
}

function isArtifactScrollMessage(
  data: unknown,
  key: string,
): data is {
  type: "save" | "restore-request";
  x?: unknown;
  y?: unknown;
} {
  return (
    typeof data === "object" &&
    data !== null &&
    "source" in data &&
    data.source === HTML_PREVIEW_SCROLL_MESSAGE_SOURCE &&
    "key" in data &&
    data.key === key &&
    "type" in data &&
    (data.type === "save" || data.type === "restore-request")
  );
}

function scrollCoordinate(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

function useThrottledValue(
  value: string,
  intervalMs: number,
  resetKey: string,
) {
  const [throttledValue, setThrottledValue] = useState(value);
  const latestValueRef = useRef(value);
  const lastFlushAtRef = useRef(0);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const resetKeyRef = useRef(resetKey);

  useEffect(() => {
    latestValueRef.current = value;

    if (resetKeyRef.current !== resetKey) {
      resetKeyRef.current = resetKey;
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      lastFlushAtRef.current = Date.now();
      setThrottledValue(value);
      return;
    }

    if (intervalMs <= 0) {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      lastFlushAtRef.current = Date.now();
      setThrottledValue(value);
      return;
    }

    const now = Date.now();
    const elapsed = now - lastFlushAtRef.current;
    if (lastFlushAtRef.current === 0 || elapsed >= intervalMs) {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      lastFlushAtRef.current = now;
      setThrottledValue(value);
      return;
    }

    if (timeoutRef.current) {
      return;
    }

    timeoutRef.current = setTimeout(() => {
      timeoutRef.current = null;
      lastFlushAtRef.current = Date.now();
      setThrottledValue(latestValueRef.current);
    }, intervalMs - elapsed);
  }, [intervalMs, resetKey, value]);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return intervalMs <= 0 || resetKeyRef.current !== resetKey
    ? value
    : throttledValue;
}
