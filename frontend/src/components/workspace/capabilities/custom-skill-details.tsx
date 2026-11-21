"use client";

import { useQueryClient } from "@tanstack/react-query";
import { DownloadIcon, LoaderIcon, PencilIcon, Trash2Icon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import {
  type CustomSkillContent,
  deleteCustomSkill,
  loadCustomSkill,
  formatSkillSecurityFindings,
  SkillRequestError,
  updateCustomSkill,
} from "@/core/skills/api";
import type { Skill } from "@/core/skills/type";

function lifecycleErrorMessage(
  error: unknown,
  fallback: string,
  manageRequired: string,
): string {
  if (error instanceof SkillRequestError && error.status === 403) {
    return manageRequired;
  }
  return error instanceof Error && error.message ? error.message : fallback;
}

export function CustomSkillDetails({
  skill,
  onChanged,
  onDeleted,
  onExport,
}: {
  skill: Skill;
  onChanged: (skill: CustomSkillContent) => void;
  onDeleted: () => void;
  onExport: () => void;
}) {
  const { t } = useI18n();
  const text = t.settings.skills;
  const queryClient = useQueryClient();
  const [loaded, setLoaded] = useState<CustomSkillContent | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [errorFallback, setErrorFallback] = useState(text.skillLoadFailed);
  const [reloadToken, setReloadToken] = useState(0);
  const loadFailedRef = useRef(text.skillLoadFailed);
  loadFailedRef.current = text.skillLoadFailed;

  useEffect(() => {
    const controller = new AbortController();
    setLoaded(null);
    setDraft("");
    setEditing(false);
    setConfirmingDelete(false);
    setError(null);
    setErrorFallback(loadFailedRef.current);
    setLoading(true);
    loadCustomSkill(skill.name, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setLoaded(result);
        setDraft(result.content);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(caught);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [skill.name, reloadToken]);

  const save = async () => {
    if (saving || !loaded) return;
    setSaving(true);
    setError(null);
    setErrorFallback(text.skillSaveFailed);
    try {
      const result = await updateCustomSkill(skill.name, draft);
      setLoaded(result);
      setDraft(result.content);
      setEditing(false);
      onChanged(result);
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
      toast.success(text.skillSaved);
    } catch (caught) {
      setError(caught);
    } finally {
      setSaving(false);
    }
  };
  const remove = async () => {
    if (deleting) return;
    setDeleting(true);
    setError(null);
    setErrorFallback(text.skillDeleteFailed);
    try {
      await deleteCustomSkill(skill.name);
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
      toast.success(text.skillDeleted);
      onDeleted();
    } catch (caught) {
      setError(caught);
      setConfirmingDelete(false);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-4 border-t pt-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium">{text.skillContent}</h3>
        {loaded && !editing && (
          <Button
            size="sm"
            variant="outline"
            disabled={loading || deleting || skill.editable === false}
            onClick={() => {
              setDraft(loaded.content);
              setEditing(true);
              setError(null);
            }}
          >
            <PencilIcon className="size-4" />
            {text.editSkill}
          </Button>
        )}
      </div>
      {loading ? (
        <p
          role="status"
          className="text-muted-foreground flex items-center gap-2 text-sm"
        >
          <LoaderIcon className="size-4 animate-spin" />
          {text.skillContentLoading}
        </p>
      ) : editing ? (
        <Textarea
          aria-label={text.skillContent}
          className="min-h-64 font-mono text-xs"
          value={draft}
          disabled={saving}
          onChange={(event) => setDraft(event.target.value)}
        />
      ) : loaded ? (
        <pre className="bg-muted/50 max-h-72 overflow-auto rounded-lg p-3 text-xs whitespace-pre-wrap">
          {loaded.content}
        </pre>
      ) : null}
      {error !== null && (
        <div role="alert" className="text-destructive text-sm">
          {lifecycleErrorMessage(
            error,
            errorFallback,
            text.skillManageRequired,
          )}
          {!loaded && (
            <Button
              className="ml-2"
              size="sm"
              variant="link"
              onClick={() => setReloadToken((value) => value + 1)}
            >
              {text.retry}
            </Button>
          )}
          {error instanceof SkillRequestError && error.findings.length > 0 && (
            <pre className="bg-muted mt-2 max-h-48 overflow-auto rounded p-2 text-xs whitespace-pre-wrap">
              {formatSkillSecurityFindings(error.findings)}
            </pre>
          )}
        </div>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        {editing ? (
          <>
            <Button
              variant="outline"
              disabled={saving}
              onClick={() => {
                setEditing(false);
                setDraft(loaded?.content ?? "");
                setError(null);
              }}
            >
              {text.cancelEdit}
            </Button>
            <Button
              disabled={saving || !draft.trim()}
              onClick={() => void save()}
            >
              {saving && <LoaderIcon className="size-4 animate-spin" />}
              {text.saveSkill}
            </Button>
          </>
        ) : (
          <Button
            variant="outline"
            disabled={loading || deleting}
            onClick={onExport}
          >
            <DownloadIcon className="size-4" />
            {text.exportSkill}
          </Button>
        )}
      </div>
      {confirmingDelete ? (
        <div className="border-destructive/40 space-y-3 rounded-lg border p-3">
          <p className="text-sm">{text.deleteConfirm}</p>
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              disabled={deleting}
              onClick={() => setConfirmingDelete(false)}
            >
              {text.cancelEdit}
            </Button>
            <Button
              variant="destructive"
              disabled={deleting}
              onClick={() => void remove()}
            >
              {deleting && <LoaderIcon className="size-4 animate-spin" />}
              {text.confirmDelete}
            </Button>
          </div>
        </div>
      ) : (
        <Button
          variant="outline"
          className="text-destructive"
          disabled={loading || editing || saving || skill.editable === false}
          onClick={() => setConfirmingDelete(true)}
        >
          <Trash2Icon className="size-4" />
          {text.deleteSkill}
        </Button>
      )}
    </div>
  );
}
