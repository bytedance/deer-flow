"use client";

import { LoaderIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { readPreviewFile } from "@/core/artifacts/binary-preview";
import { readingStateAccess } from "@/core/artifacts/reading-state";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { useArtifactPreviewRenderer } from "@/core/extensions/artifact-previews";
import type { ArtifactPreviewRenderer } from "@/core/extensions/contracts";
import { useI18n } from "@/core/i18n/hooks";
import { getFileName } from "@/core/utils/files";

import {
  ArtifactDownloadFallback,
  ArtifactPreviewError,
} from "./artifact-file-preview";

function MountedPreview({
  renderer,
  filepath,
  threadId,
  isMock,
  viewerId,
  rendererKey,
}: {
  renderer: ArtifactPreviewRenderer;
  filepath: string;
  threadId: string;
  isMock?: boolean;
  viewerId: string;
  rendererKey: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const { locale, t } = useI18n();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (failed || !ref.current) return;
    const abort = new AbortController();
    let state: ReturnType<typeof readingStateAccess> | undefined;
    const shadow =
      ref.current.shadowRoot ?? ref.current.attachShadow({ mode: "open" });
    const root = document.createElement("div");
    root.style.height = "100%";
    shadow.replaceChildren(root);
    let controller: { dispose: () => void } | undefined;
    const onError = () => {
      if (!abort.signal.aborted) setFailed(true);
    };
    try {
      controller = renderer.mount(root, {
        filename: getFileName(filepath),
        locale,
        signal: abort.signal,
        onError,
        getReadingState: () => state?.get(),
        saveReadingState: (value) => {
          if (!abort.signal.aborted) state?.set(value);
        },
        readFile: async () => {
          state = undefined;
          const { bytes, etag } = await readPreviewFile(
            urlOfArtifact({ filepath, threadId, isMock }),
            abort.signal,
          );
          let version = etag ? `etag:${etag}` : undefined;
          if (!version && globalThis.crypto?.subtle) {
            try {
              const digest = await globalThis.crypto.subtle.digest(
                "SHA-256",
                bytes,
              );
              version = `sha256:${Array.from(new Uint8Array(digest), (byte) =>
                byte.toString(16).padStart(2, "0"),
              ).join("")}`;
            } catch {
              // Reading preferences must never prevent a successful preview.
            }
          }
          abort.signal.throwIfAborted();
          // LAN HTTP origins may have no Web Crypto. Without a version, skip
          // restoring preferences rather than borrowing state from an older file.
          if (version)
            state = readingStateAccess(
              viewerId,
              JSON.stringify([threadId, filepath, rendererKey, version]),
            );
          return bytes;
        },
      });
      if (typeof controller?.dispose !== "function")
        throw new Error("Invalid preview controller");
    } catch {
      onError();
    }
    return () => {
      abort.abort();
      try {
        controller?.dispose();
      } catch {
        /* Contain extension cleanup failures. */
      }
      root.remove();
    };
  }, [
    renderer,
    filepath,
    threadId,
    isMock,
    locale,
    failed,
    viewerId,
    rendererKey,
  ]);
  return failed ? (
    <ArtifactPreviewError
      filepath={filepath}
      threadId={threadId}
      isMock={isMock}
      message={t.artifactPreview.previewFailed}
      downloadLabel={t.common.download}
      onRetry={() => setFailed(false)}
    />
  ) : (
    <div
      ref={ref}
      className="size-full min-w-0"
      aria-label={getFileName(filepath)}
    />
  );
}

/** Only installed, enabled, viewer-owned contributions can render files. */
export function PluginArtifactPreview(props: {
  filepath: string;
  threadId: string;
  isMock?: boolean;
  isRunning?: boolean;
}) {
  const { match, isLoading, viewerId } = useArtifactPreviewRenderer(
    props.filepath,
  );
  const { locale, t } = useI18n();
  const [revision, setRevision] = useState(0);
  const previous = useRef({
    threadId: props.threadId,
    filepath: props.filepath,
    isRunning: props.isRunning,
  });
  useEffect(() => {
    const old = previous.current;
    previous.current = {
      threadId: props.threadId,
      filepath: props.filepath,
      isRunning: props.isRunning,
    };
    if (
      old.threadId === props.threadId &&
      old.filepath === props.filepath &&
      old.isRunning &&
      !props.isRunning
    )
      setRevision((value) => value + 1);
  }, [props.threadId, props.filepath, props.isRunning]);
  if (isLoading)
    return (
      <div className="text-muted-foreground flex items-center gap-2 p-6 text-sm">
        <LoaderIcon className="size-4 animate-spin" />
        {t.artifactPreview.loadingPreview}
      </div>
    );
  if (!match) return <ArtifactDownloadFallback {...props} />;
  return (
    <MountedPreview
      key={`${viewerId}:${props.threadId}:${props.filepath}:${locale}:${match.contribution.namespace}:${revision}`}
      renderer={match.renderer}
      viewerId={viewerId ?? "anonymous"}
      rendererKey={`${match.contribution.namespace}:${match.renderer.id}`}
      {...props}
    />
  );
}
