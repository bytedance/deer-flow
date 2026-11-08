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
          const bytes = await readPreviewFile(
            urlOfArtifact({ filepath, threadId, isMock }),
            abort.signal,
          );
          const hash = Array.from(
            new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
            (byte) => byte.toString(16).padStart(2, "0"),
          ).join("");
          abort.signal.throwIfAborted();
          state = readingStateAccess(
            viewerId,
            JSON.stringify([threadId, filepath, rendererKey, hash]),
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
}) {
  const { match, isLoading, viewerId } = useArtifactPreviewRenderer(
    props.filepath,
  );
  const { locale, t } = useI18n();
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
      key={`${viewerId}:${props.threadId}:${props.filepath}:${locale}:${match.contribution.namespace}`}
      renderer={match.renderer}
      viewerId={viewerId ?? "anonymous"}
      rendererKey={`${match.contribution.namespace}:${match.renderer.id}`}
      {...props}
    />
  );
}
