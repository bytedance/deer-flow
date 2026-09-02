"use client";

import { DownloadIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  appendHtmlPreviewBaseHref,
  appendHtmlPreviewScrollRestoration,
  createHtmlPreviewScrollKey,
  HTML_PREVIEW_SCROLL_MESSAGE_SOURCE,
} from "@/core/artifacts/preview";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { extractCitationSources } from "@/core/citations/sources";
import {
  SafeStreamdown,
  toStreamdownComponents,
} from "@/core/streamdown/components";
import {
  getFileExtensionDisplayName,
  getFileIcon,
  getFileName,
} from "@/core/utils/files";

import { ArtifactLink } from "../citations/artifact-link";
import { CitationSourcesPanel } from "../citations/citation-sources-panel";

import { artifactMarkdownPlugins } from "./markdown-preview-plugins";

export function ArtifactPreviewError({
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

export function formatArtifactBytes(bytes: number | undefined) {
  if (bytes === undefined) return undefined;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export function ArtifactDownloadFallback({
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
