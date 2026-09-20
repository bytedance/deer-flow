"use client";

import { DownloadIcon, FileArchiveIcon, LoaderIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useI18n } from "@/core/i18n/hooks";
import {
  downloadSkillExport,
  handOffSkillDownload,
  loadSkillExportManifest,
  type SkillExportManifest,
  SkillExportRequestError,
} from "@/core/skills/export";

export default function SkillExportDialog({
  name,
  onClose,
}: {
  name: string;
  onClose: () => void;
}) {
  const { t, locale } = useI18n();
  const text = t.settings.skills;
  const [manifest, setManifest] = useState<SkillExportManifest | null>(null);
  const [phase, setPhase] = useState<
    "loading" | "ready" | "downloading" | "done" | "error"
  >("loading");
  const [error, setError] = useState<unknown>(null);
  const [visible, setVisible] = useState(0);
  const active = useRef<AbortController | null>(null);
  const downloading = useRef(false);

  const load = useCallback(async () => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setManifest(null);
    setError(null);
    setPhase("loading");
    setVisible(0);
    try {
      const result = await loadSkillExportManifest(name, controller.signal);
      if (controller.signal.aborted || active.current !== controller) return;
      setManifest(result);
      setPhase("ready");
    } catch (error) {
      if (controller.signal.aborted || active.current !== controller) return;
      setError(error);
      setPhase("error");
    }
  }, [name]);
  useEffect(() => {
    void load();
    return () => active.current?.abort();
  }, [load]);

  const close = () => {
    active.current?.abort();
    onClose();
  };
  const download = async () => {
    if (!manifest?.revision || !manifest.can_export || downloading.current)
      return;
    downloading.current = true;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setError(null);
    setPhase("downloading");
    try {
      const blob = await downloadSkillExport(
        name,
        manifest.revision,
        controller.signal,
      );
      if (controller.signal.aborted || active.current !== controller) return;
      handOffSkillDownload(blob, name);
      setPhase("done");
    } catch (error) {
      if (controller.signal.aborted || active.current !== controller) return;
      setError(error);
      setPhase("error");
    } finally {
      downloading.current = false;
    }
  };
  const changed =
    error instanceof SkillExportRequestError && error.status === 409;
  const errorMessage =
    error instanceof SkillExportRequestError
      ? ((
          {
            403: text.installAdminRequired,
            404: text.exportNotFound,
            409: text.exportChanged,
            413: text.exportLimit,
            422: text.exportBlocked,
            429: text.exportBusy,
            503: text.exportTimeout,
          } as Record<number, string>
        )[error.status] ?? text.exportFailed)
      : text.exportFailed;
  const bytes = (size: number) =>
    size < 1024
      ? `${size} B`
      : size < 1024 * 1024
        ? `${(size / 1024).toLocaleString(locale, { maximumFractionDigits: 1 })} KiB`
        : `${(size / (1024 * 1024)).toLocaleString(locale, { maximumFractionDigits: 1 })} MiB`;

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileArchiveIcon className="size-5" />
            {text.exportTitle}
          </DialogTitle>
          <DialogDescription>{text.exportDescription}</DialogDescription>
        </DialogHeader>
        <div className="min-w-0 space-y-5">
          <div className="font-mono text-base font-medium break-all">
            {name}.skill
          </div>
          {phase === "loading" && (
            <p
              role="status"
              className="text-muted-foreground flex items-center gap-2 text-sm"
            >
              <LoaderIcon className="size-4 animate-spin" />
              {text.exportLoading}
            </p>
          )}
          {manifest && (
            <>
              <dl className="bg-muted/50 grid grid-cols-3 gap-3 rounded-lg p-3 text-sm">
                {[
                  [text.exportFiles, manifest.file_count],
                  [text.exportDirectories, manifest.directory_count],
                  [text.exportSize, bytes(manifest.total_bytes)],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-muted-foreground text-xs">{label}</dt>
                    <dd className="mt-1 font-medium tabular-nums">{value}</dd>
                  </div>
                ))}
              </dl>
              <details className="rounded-lg border p-3">
                <summary className="cursor-pointer text-sm font-medium">
                  {text.exportContents}
                </summary>
                <ul
                  className="mt-3 max-h-48 space-y-2 overflow-y-auto text-xs"
                  aria-label={text.exportContents}
                >
                  {manifest.files.slice(visible, visible + 50).map((file) => (
                    <li
                      key={file.path}
                      className="flex items-start justify-between gap-3"
                    >
                      <span className="min-w-0 font-mono break-all">
                        {file.path === "." ? name : file.path}
                        {file.type === "directory" ? "/" : ""}
                      </span>
                      <span className="text-muted-foreground shrink-0 tabular-nums">
                        {file.type === "file" ? bytes(file.size) : "—"}
                      </span>
                    </li>
                  ))}
                </ul>
                {visible > 0 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setVisible((n) => Math.max(0, n - 50))}
                  >
                    {text.exportPrevious}
                  </Button>
                )}
                {manifest.files.length > visible + 50 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setVisible((n) => n + 50)}
                  >
                    {text.exportMore}
                  </Button>
                )}
              </details>
              <section className="space-y-2 text-sm">
                <h3 className="font-medium">{text.exportRequirements}</h3>
                <dl className="space-y-2">
                  <div>
                    <dt className="text-muted-foreground text-xs">
                      {text.exportCompatibility}
                    </dt>
                    <dd className="break-words whitespace-pre-wrap">
                      {manifest.requirements.compatibility ??
                        text.exportUndeclared}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground text-xs">
                      {text.exportTools}
                    </dt>
                    <dd className="break-words">
                      {manifest.requirements.allowed_tools?.join(", ") ??
                        text.exportUndeclared}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground text-xs">
                      {text.exportSecrets}
                    </dt>
                    <dd className="break-words">
                      {manifest.requirements.required_secrets
                        ?.map(
                          (secret) =>
                            `${secret.name} (${secret.optional ? text.exportOptional : text.exportRequired})`,
                        )
                        .join(", ") ?? text.exportUndeclared}
                    </dd>
                  </div>
                </dl>
              </section>
              {manifest.warnings.length > 0 && (
                <section className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
                  <h3 className="font-medium">{text.exportWarnings}</h3>
                  <p className="text-muted-foreground mt-1 text-xs">
                    {text.exportWarningDescription}
                  </p>
                  <ul className="mt-2 max-h-28 overflow-y-auto text-xs">
                    {manifest.warnings.map((warning, i) => (
                      <li key={i} className="break-all">
                        {warning.path ? `${warning.path}: ` : ""}
                        {text.exportNotices[warning.code] ?? warning.message}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              {!manifest.can_export && (
                <section role="alert" className="text-destructive text-sm">
                  <p className="font-medium">{text.exportBlocked}</p>
                  <ul className="mt-1 max-h-28 overflow-y-auto">
                    {manifest.blockers.map((blocker, i) => (
                      <li className="break-all" key={i}>
                        {blocker.path ? `${blocker.path}: ` : ""}
                        {text.exportNotices[blocker.code] ?? blocker.message}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              <p className="text-muted-foreground text-xs leading-relaxed">
                {text.exportScope}
              </p>
            </>
          )}
          {error !== null && (
            <p role="alert" className="text-destructive text-sm">
              {errorMessage}
            </p>
          )}
          {phase === "done" && (
            <p role="status" className="text-sm">
              {text.exportHandedOff}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={close}>
            {t.common.close}
          </Button>
          {(phase === "error" || (manifest && !manifest.can_export)) && (
            <Button variant="outline" onClick={() => void load()}>
              {text.exportRefresh}
            </Button>
          )}
          {manifest?.can_export && (
            <Button
              disabled={
                phase === "downloading" ||
                changed ||
                (error instanceof SkillExportRequestError &&
                  error.status === 403)
              }
              onClick={() => void download()}
            >
              {phase === "downloading" ? (
                <LoaderIcon className="size-4 animate-spin" />
              ) : (
                <DownloadIcon className="size-4" />
              )}
              {phase === "downloading"
                ? text.exportDownloading
                : text.exportDownload}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
