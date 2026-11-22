"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2Icon,
  ExternalLinkIcon,
  LoaderIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import type { enUS } from "@/core/i18n/locales/en-US";
import {
  deleteCustomSkill,
  formatSkillSecurityFindings,
  inspectSkillSource,
  installSkillSource,
  SkillRequestError,
  type InstallSkillResponse,
  type SkillSourcePreview,
} from "@/core/skills/api";
import { useEnableSkill } from "@/core/skills/hooks";

type SkillText = (typeof enUS)["settings"]["skills"];
type Phase =
  | "input"
  | "inspecting"
  | "preview"
  | "installing"
  | "success"
  | "error";

function sourceErrorMessage(error: unknown, text: SkillText): string {
  if (!(error instanceof SkillRequestError)) return text.sourceRequestFailed;
  if (error.status === 403) return text.skillManageRequired;
  switch (error.code) {
    case "skill_source_invalid":
      return text.sourceInvalid;
    case "skill_source_not_configured":
      return text.sourceNotConfigured;
    case "skill_source_auth_failed":
      return text.sourceAuthFailed;
    case "skill_source_unavailable":
      return text.sourceUnavailable;
    case "skill_source_rate_limited":
      return text.sourceRateLimited(error.retryAfter);
    case "skill_source_not_found":
      return text.sourceNotFound;
    case "skill_source_snapshot_unusable":
      return text.sourceSnapshotUnusable;
    case "skill_source_changed":
      return text.sourceChanged;
    case "skill_security_scan_failed":
      return text.skillSecurityScanFailed;
    case "skill_install_failed":
      return text.installFailed;
    default:
      return error.message || text.sourceRequestFailed;
  }
}

export function SkillSourceInstallDialog({
  onClose,
  onInstalled,
}: {
  onClose: () => void;
  onInstalled: () => void;
}) {
  const { t, locale } = useI18n();
  const text = t.settings.skills;
  const queryClient = useQueryClient();
  const active = useRef<AbortController | null>(null);
  const pendingInstall = useRef<Promise<InstallSkillResponse> | null>(null);
  const [phase, setPhase] = useState<Phase>("input");
  const [source, setSource] = useState("");
  const [preview, setPreview] = useState<SkillSourcePreview | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [installedName, setInstalledName] = useState("");
  const [installedEnabled, setInstalledEnabled] = useState(true);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const { mutateAsync: setSkillEnabled, isPending: isEnabling } =
    useEnableSkill();

  const refreshSkills = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["skills"] });
  }, [queryClient]);
  const preservePendingInstall = useCallback(() => {
    const request = pendingInstall.current;
    if (!request) return false;
    pendingInstall.current = null;
    // The Gateway drains installs after client cancellation. Follow the request
    // once so its settlement, rather than dismissal, triggers the final read.
    void request.then(refreshSkills, refreshSkills);
    return true;
  }, [refreshSkills]);

  useEffect(
    () => () => {
      if (!preservePendingInstall()) active.current?.abort();
      active.current = null;
    },
    [preservePendingInstall],
  );

  const close = () => {
    if (!preservePendingInstall()) active.current?.abort();
    active.current = null;
    refreshSkills();
    onClose();
  };
  const fail = (caught: unknown) => {
    if (
      caught instanceof SkillRequestError &&
      caught.code === "skill_source_changed"
    ) {
      setPreview(null);
    }
    setError(caught);
    setPhase("error");
  };
  const inspect = async () => {
    if (phase === "inspecting" || phase === "installing") return;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setError(null);
    setPreview(null);
    setPhase("inspecting");
    try {
      const normalizedSource = source.trim();
      setSource(normalizedSource);
      const result = await inspectSkillSource(
        normalizedSource,
        controller.signal,
      );
      if (active.current !== controller || controller.signal.aborted) return;
      setPreview(result);
      setPhase("preview");
    } catch (caught) {
      if (active.current !== controller || controller.signal.aborted) return;
      fail(caught);
    } finally {
      if (active.current === controller) active.current = null;
    }
  };
  const install = async () => {
    if (!preview || phase === "installing") return;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setError(null);
    setPhase("installing");
    let request: Promise<InstallSkillResponse> | null = null;
    try {
      request = installSkillSource(
        {
          source: preview.source,
          expected_snapshot_digest: preview.snapshot_digest,
        },
        controller.signal,
      );
      pendingInstall.current = request;
      const result = await request;
      if (active.current !== controller || controller.signal.aborted) return;
      if (!result.success) {
        fail(new SkillRequestError(400, result.message || text.installFailed));
        return;
      }
      setInstalledName(result.skill_name || preview.skill_name);
      setInstalledEnabled(result.enabled ?? true);
      setConfirmingDelete(false);
      setPhase("success");
      refreshSkills();
      onInstalled();
    } catch (caught) {
      if (active.current !== controller || controller.signal.aborted) return;
      fail(caught);
    } finally {
      if (pendingInstall.current === request) pendingInstall.current = null;
      if (active.current === controller) active.current = null;
    }
  };
  const toggleInstalled = async (enabled: boolean) => {
    try {
      const updated = await setSkillEnabled({
        skillName: installedName,
        enabled,
      });
      setInstalledEnabled(updated.enabled);
    } catch (caught) {
      toast.error(
        caught instanceof SkillRequestError && caught.status === 403
          ? text.skillManageRequired
          : caught instanceof Error
            ? caught.message
            : text.skillSaveFailed,
      );
    }
  };
  const removeInstalled = async () => {
    if (isDeleting) return;
    setIsDeleting(true);
    try {
      await deleteCustomSkill(installedName);
      toast.success(text.skillDeleted);
      refreshSkills();
      onClose();
    } catch (caught) {
      toast.error(
        caught instanceof SkillRequestError && caught.status === 403
          ? text.skillManageRequired
          : caught instanceof Error
            ? caught.message
            : text.skillDeleteFailed,
      );
    } finally {
      setIsDeleting(false);
    }
  };
  const bytes = preview
    ? preview.total_bytes.toLocaleString(locale, { maximumFractionDigits: 0 })
    : "";

  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{text.sourceDialogTitle}</DialogTitle>
          <DialogDescription>{text.sourceDialogDescription}</DialogDescription>
        </DialogHeader>

        {(phase === "input" || phase === "inspecting") && (
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              void inspect();
            }}
          >
            <label className="space-y-2 text-sm font-medium">
              {text.sourceLabel}
              <Input
                autoFocus
                value={source}
                onChange={(event) => setSource(event.target.value)}
                placeholder={text.sourcePlaceholder}
                disabled={phase === "inspecting"}
                maxLength={256}
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
              />
            </label>
            <DialogFooter>
              <Button
                type="submit"
                disabled={!source.trim() || phase === "inspecting"}
              >
                {phase === "inspecting" && (
                  <LoaderIcon className="size-4 animate-spin" />
                )}
                {phase === "inspecting"
                  ? text.sourceInspecting
                  : text.sourceInspect}
              </Button>
            </DialogFooter>
          </form>
        )}

        {preview && (phase === "preview" || phase === "installing") && (
          <div className="space-y-4">
            <div>
              <h3 className="font-medium break-all">{preview.skill_name}</h3>
              <p className="text-muted-foreground mt-1 text-sm whitespace-pre-wrap">
                {preview.description}
              </p>
            </div>
            <dl className="bg-muted/50 grid grid-cols-2 gap-3 rounded-lg p-3 text-sm">
              <div>
                <dt className="text-muted-foreground text-xs">
                  {text.sourceFiles}
                </dt>
                <dd>{preview.file_count}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground text-xs">
                  {text.sourceSize}
                </dt>
                <dd>{bytes} B</dd>
              </div>
              <div className="col-span-2 min-w-0">
                <dt className="text-muted-foreground text-xs">
                  {text.sourceDigest}
                </dt>
                <dd className="font-mono text-xs break-all">
                  {preview.snapshot_digest}
                </dd>
              </div>
              <div className="col-span-2 min-w-0">
                <dt className="text-muted-foreground text-xs">
                  {text.sourceUpstreamHash}
                </dt>
                <dd className="font-mono text-xs break-all">
                  {preview.upstream_hash ?? "—"}
                </dd>
              </div>
            </dl>
            <a
              className="text-muted-foreground flex items-center gap-1 text-xs break-all underline"
              href={preview.source_url}
              target="_blank"
              rel="noreferrer"
            >
              {preview.source_url}
              <ExternalLinkIcon className="size-3 shrink-0" />
            </a>
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
              <p>{text.sourceImmediateEffect}</p>
              <p className="text-muted-foreground mt-1">
                {text.sourceFinalScanNotice}
              </p>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                disabled={phase === "installing"}
                onClick={() => setPhase("input")}
              >
                {text.sourceBack}
              </Button>
              <Button
                disabled={phase === "installing"}
                onClick={() => void install()}
              >
                {phase === "installing" && (
                  <LoaderIcon className="size-4 animate-spin" />
                )}
                {phase === "installing"
                  ? text.sourceInstalling
                  : text.sourceInstall}
              </Button>
            </DialogFooter>
          </div>
        )}

        {phase === "error" && (
          <div className="space-y-4">
            <div
              role="alert"
              className="border-destructive/40 rounded-lg border p-3"
            >
              <h3 className="text-destructive text-sm font-medium">
                {text.sourceErrorTitle}
              </h3>
              <p className="mt-1 text-sm">{sourceErrorMessage(error, text)}</p>
              {error instanceof SkillRequestError && error.code && (
                <p className="text-muted-foreground mt-2 text-xs whitespace-pre-wrap">
                  {error.message}
                </p>
              )}
              {error instanceof SkillRequestError &&
                error.findings.length > 0 && (
                  <pre className="bg-muted mt-3 max-h-48 overflow-auto rounded p-2 text-xs whitespace-pre-wrap">
                    {formatSkillSecurityFindings(error.findings)}
                  </pre>
                )}
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setError(null);
                  setPhase(preview ? "preview" : "input");
                }}
              >
                {preview ? text.sourceBack : text.sourceRetry}
              </Button>
              {preview && (
                <Button onClick={() => void install()}>
                  {text.sourceInstall}
                </Button>
              )}
            </DialogFooter>
          </div>
        )}

        {phase === "success" && (
          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <CheckCircle2Icon className="mt-0.5 size-5 text-emerald-600" />
              <div>
                <h3 className="font-medium">{text.sourceSuccessTitle}</h3>
                <p className="text-muted-foreground text-sm break-all">
                  {installedName}
                </p>
              </div>
            </div>
            <p className="text-sm">
              {installedEnabled
                ? text.sourceSuccessDescription
                : text.sourceSuccessDisabledDescription}
            </p>
            <p className="text-muted-foreground text-sm">
              {text.sourceVisibilityNotice}
            </p>
            <div className="flex items-center justify-between rounded-lg border p-3">
              <span className="text-sm">{text.sourceEnabled}</span>
              <Switch
                aria-label={`${text.sourceEnabled} ${installedName}`}
                checked={installedEnabled}
                disabled={isEnabling || isDeleting}
                onCheckedChange={(enabled) => void toggleInstalled(enabled)}
              />
            </div>
            {confirmingDelete ? (
              <div className="border-destructive/40 space-y-3 rounded-lg border p-3">
                <p className="text-sm">{text.deleteConfirm}</p>
                <div className="flex justify-end gap-2">
                  <Button
                    variant="outline"
                    disabled={isDeleting}
                    onClick={() => setConfirmingDelete(false)}
                  >
                    {text.cancelEdit}
                  </Button>
                  <Button
                    variant="destructive"
                    disabled={isDeleting}
                    onClick={() => void removeInstalled()}
                  >
                    {isDeleting && (
                      <LoaderIcon className="size-4 animate-spin" />
                    )}
                    {text.confirmDelete}
                  </Button>
                </div>
              </div>
            ) : (
              <Button
                variant="outline"
                disabled={isEnabling}
                onClick={() => setConfirmingDelete(true)}
              >
                <Trash2Icon className="size-4" />
                {text.deleteSkill}
              </Button>
            )}
            <DialogFooter>
              <Button onClick={close}>{t.common.close}</Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
