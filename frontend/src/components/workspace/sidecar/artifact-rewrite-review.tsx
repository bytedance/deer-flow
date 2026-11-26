"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { useEffect, useState } from "react";
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
import { Textarea } from "@/components/ui/textarea";
import { useArtifactContent } from "@/core/artifacts/hooks";
import {
  artifactReplacement,
  applyArtifactSelectionDraft,
  MAX_REPLACEMENT_LENGTH,
  type ArtifactSelectionEdit,
} from "@/core/artifacts/selection";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

import { useArtifacts } from "../artifacts/context";
import { useThread } from "../messages/context";

import { useSidecar } from "./context";

export function ArtifactRewriteReview({
  edit,
  messages,
  disabled,
  onCancel,
}: {
  edit: ArtifactSelectionEdit;
  messages: Message[];
  disabled: boolean;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const { user } = useAuth();
  const { thread } = useThread();
  const sidecar = useSidecar();
  const clearArtifactEdit = sidecar.clearArtifactEdit;
  const {
    drafts,
    setDrafts,
    setEditingPath,
    select,
    setOpen: openArtifacts,
  } = useArtifacts();
  const authorized =
    edit.ownerId === user?.id && edit.threadId === sidecar.parentThreadId;
  const artifact = useArtifactContent({
    filepath: edit.filepath,
    threadId: edit.threadId,
    enabled: authorized,
  });
  const canApply =
    authorized &&
    !disabled &&
    !thread.isLoading &&
    !artifact.isLoading &&
    !artifact.error &&
    artifact.sha256 === edit.revision;
  const draft = drafts[edit.filepath];
  const changed =
    !draft ||
    draft.conflict ||
    draft.draftContent !== edit.source ||
    draft.baselineSha256 !== edit.revision ||
    (artifact.sha256 !== undefined && artifact.sha256 !== edit.revision);
  const [open, setOpen] = useState(false);
  const [replacement, setReplacement] = useState("");
  const candidate = disabled ? null : artifactReplacement(messages, edit.id);
  useEffect(() => {
    if (!authorized) clearArtifactEdit(edit.id);
  }, [authorized, edit.id, clearArtifactEdit]);
  if (!authorized) return null;
  return (
    <>
      <div
        className="bg-muted/40 mx-3 space-y-2 rounded-lg border p-3 text-sm"
        data-testid="artifact-rewrite-review"
      >
        <p className="truncate font-medium" title={edit.context.label}>
          {edit.context.label}
        </p>
        <p className="text-muted-foreground">
          {t.artifactSelection.instructions}
        </p>
        <div className="flex gap-2">
          <Button
            size="sm"
            disabled={candidate === null}
            onClick={() => {
              setReplacement(candidate ?? "");
              setOpen(true);
            }}
          >
            {t.artifactSelection.review}
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel}>
            {t.common.cancel}
          </Button>
        </div>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t.artifactSelection.review}</DialogTitle>
            <DialogDescription className="break-all">
              {edit.context.label}
            </DialogDescription>
          </DialogHeader>
          <label className="space-y-2 text-sm">
            <span>{t.artifactSelection.original}</span>
            <Textarea
              aria-label={t.artifactSelection.original}
              readOnly
              value={edit.context.content}
              className="max-h-36"
            />
          </label>
          <label className="space-y-2 text-sm">
            <span>{t.artifactSelection.replacement}</span>
            <Textarea
              aria-label={t.artifactSelection.replacement}
              value={replacement}
              onChange={(event) => setReplacement(event.target.value)}
              maxLength={MAX_REPLACEMENT_LENGTH}
              className="max-h-72 min-h-40 font-mono"
            />
          </label>
          <DialogFooter>
            {changed && (
              <p role="alert" className="text-destructive text-sm">
                {t.artifactSelection.changed}
              </p>
            )}
            <Button variant="outline" onClick={() => setOpen(false)}>
              {t.common.cancel}
            </Button>
            <Button
              disabled={
                !canApply ||
                changed ||
                replacement.length > MAX_REPLACEMENT_LENGTH
              }
              onClick={() => {
                const next = applyArtifactSelectionDraft(
                  drafts[edit.filepath],
                  edit,
                  replacement,
                );
                if (!canApply || !next) {
                  toast.error(t.artifactSelection.changed);
                  return;
                }
                setDrafts((current) => {
                  const updated = applyArtifactSelectionDraft(
                    current[edit.filepath],
                    edit,
                    replacement,
                  );
                  return updated
                    ? { ...current, [edit.filepath]: updated }
                    : current;
                });
                toast.success(t.artifactSelection.applied);
                setOpen(false);
                onCancel();
                select(edit.filepath);
                setEditingPath(edit.filepath);
                sidecar.close();
                openArtifacts(true);
              }}
            >
              {t.artifactSelection.apply}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
