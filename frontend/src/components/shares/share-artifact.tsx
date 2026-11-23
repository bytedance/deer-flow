"use client";

import { useEffect, useState } from "react";

import { ArtifactTablePreview } from "@/components/workspace/artifacts/artifact-table-preview";
import { useI18n } from "@/core/i18n/hooks";
import { shareArtifactURL, type SharedArtifact } from "@/core/shares/api";

import { ShareMarkdown } from "./share-markdown";

export function ShareArtifact({
  token,
  artifact,
  artifacts,
}: {
  token: string;
  artifact: SharedArtifact;
  artifacts: SharedArtifact[];
}) {
  const { t } = useI18n();
  const url = shareArtifactURL(token, artifact.path);
  const extension = artifact.path.split(".").at(-1)?.toLowerCase();
  const isHTML = extension === "html" || extension === "htm";
  const isImage = ["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(
    extension ?? "",
  );
  const isText =
    !isHTML &&
    (artifact.mime_type.startsWith("text/") ||
      ["json", "md", "csv", "tsv"].includes(extension ?? ""));
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!isText) return;
    const controller = new AbortController();
    void globalThis
      .fetch(url, {
        credentials: "omit",
        cache: "no-store",
        referrerPolicy: "no-referrer",
        headers: artifact.size > 0 ? { Range: "bytes=0-524287" } : undefined,
        signal: controller.signal,
      })
      .then(async (response) => {
        if (!response.ok) throw new Error();
        return response.text();
      })
      .then((value) => {
        if (!controller.signal.aborted) setText(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(true);
      });
    return () => controller.abort();
  }, [url, isText, artifact.size]);

  if (isHTML || extension === "pdf")
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground text-sm">{t.sharing.previewNote}</p>
        <iframe
          className="h-[65vh] w-full rounded-md border bg-white"
          sandbox={isHTML ? "" : undefined}
          src={url}
          referrerPolicy="no-referrer"
          title={artifact.path}
        />
      </div>
    );
  if (isImage)
    return (
      <img
        className="max-h-[70vh] max-w-full object-contain"
        src={url}
        alt={artifact.path}
        referrerPolicy="no-referrer"
      />
    );
  if (!isText) return <p>{t.sharing.noPreview}</p>;
  if (error) return <p role="alert">{t.sharing.failed}</p>;
  if (text === null) return <p role="status">{t.sharing.loading}</p>;
  const truncated = artifact.size > 524288;
  return (
    <div className="space-y-3">
      {truncated && (
        <p className="text-muted-foreground text-sm">
          {t.sharing.previewLimited}
        </p>
      )}
      {extension === "csv" || extension === "tsv" ? (
        <ArtifactTablePreview
          content={text}
          delimiter={extension === "tsv" ? "\t" : ","}
          truncated={truncated}
          identity={url}
        />
      ) : extension === "md" ? (
        <ShareMarkdown
          content={text}
          token={token}
          artifacts={artifacts}
          basePath={
            artifact.path.includes("/")
              ? artifact.path.slice(0, artifact.path.lastIndexOf("/") + 1)
              : ""
          }
        />
      ) : (
        <pre className="overflow-x-auto text-sm whitespace-pre-wrap">
          {text}
        </pre>
      )}
    </div>
  );
}
