"use client";

import { DatabaseIcon, FileTextIcon, PlusIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import {
  useCreateKnowledgeDataset,
  useDeleteKnowledgeDataset,
  useKnowledgeBaseEnabled,
  useKnowledgeDatasets,
  useKnowledgeEvents,
  type KnowledgeDataset,
} from "@/core/knowledge";

import { DatasetStatus, SharedKnowledgeBanner } from "./_components";

function countLabel(template: string, count: number): string {
  return template.replace("{count}", String(count));
}

export default function KnowledgePage() {
  const { t } = useI18n();
  const { user } = useAuth();
  const { enabled } = useKnowledgeBaseEnabled();
  const datasetsQuery = useKnowledgeDatasets(enabled);
  const createDataset = useCreateKnowledgeDataset();
  const deleteDataset = useDeleteKnowledgeDataset();
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeDataset | null>(
    null,
  );
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const isAdmin = user?.system_role === "admin";

  useKnowledgeEvents(enabled);

  useEffect(() => {
    document.title = `${t.knowledge.title} - ${t.pages.appName}`;
  }, [t.knowledge.title, t.pages.appName]);

  const submitCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) return;
    try {
      await createDataset.mutateAsync({
        name: trimmedName,
        description: description.trim() || undefined,
      });
      setName("");
      setDescription("");
      setCreateOpen(false);
    } catch {
      // Mutation owns the sanitized toast error; keep the dialog open.
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteDataset.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch {
      // Mutation owns the sanitized toast error; keep the dialog open.
    }
  };

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="overflow-y-auto">
        <div className="mx-auto flex w-full max-w-(--container-width-md) flex-col gap-5 p-4 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-2xl font-semibold">{t.knowledge.title}</h1>
              <p className="text-muted-foreground mt-1 text-sm">
                {t.knowledge.description}
              </p>
            </div>
            <Button onClick={() => setCreateOpen(true)}>
              <PlusIcon />
              {t.knowledge.create.action}
            </Button>
          </div>

          <SharedKnowledgeBanner />

          {datasetsQuery.isPending ? (
            <div className="text-muted-foreground py-16 text-center text-sm">
              {t.common.loading}
            </div>
          ) : datasetsQuery.isError ? (
            <Empty className="border">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <DatabaseIcon />
                </EmptyMedia>
                <EmptyTitle>{t.knowledge.loadFailed}</EmptyTitle>
                <EmptyDescription>
                  {datasetsQuery.error.message}
                </EmptyDescription>
              </EmptyHeader>
              <Button
                variant="outline"
                onClick={() => void datasetsQuery.refetch()}
              >
                {t.knowledge.retry}
              </Button>
            </Empty>
          ) : datasetsQuery.data?.length ? (
            <div
              className="grid gap-4 md:grid-cols-2"
              data-testid="knowledge-dataset-list"
            >
              {datasetsQuery.data.map((dataset) => (
                <Card key={dataset.id} data-testid={`dataset-${dataset.id}`}>
                  <CardHeader>
                    <CardTitle className="min-w-0 truncate">
                      {dataset.name}
                    </CardTitle>
                    <CardDescription className="line-clamp-2 min-h-10">
                      {dataset.description?.trim() ? dataset.description : "—"}
                    </CardDescription>
                    <CardAction>
                      <DatasetStatus dataset={dataset} />
                    </CardAction>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-4">
                    <div className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-sm">
                      <span className="inline-flex items-center gap-1.5">
                        <FileTextIcon className="size-4" />
                        {countLabel(
                          t.knowledge.dataset.documents,
                          Number(dataset.document_count ?? 0),
                        )}
                      </span>
                      <span>
                        {countLabel(
                          t.knowledge.dataset.chunks,
                          Number(dataset.chunk_count ?? 0),
                        )}
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <Button asChild variant="outline" size="sm">
                        <Link
                          href={`/workspace/knowledge/${encodeURIComponent(dataset.id)}`}
                        >
                          {t.knowledge.dataset.open}
                        </Link>
                      </Button>
                      {isAdmin ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => setDeleteTarget(dataset)}
                        >
                          <Trash2Icon />
                          {t.knowledge.dataset.delete}
                        </Button>
                      ) : (
                        <span className="text-muted-foreground text-xs">
                          {t.knowledge.dataset.adminOnly}
                        </span>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <Empty className="border">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <DatabaseIcon />
                </EmptyMedia>
                <EmptyTitle>{t.knowledge.emptyTitle}</EmptyTitle>
                <EmptyDescription>
                  {t.knowledge.emptyDescription}
                </EmptyDescription>
              </EmptyHeader>
              <Button onClick={() => setCreateOpen(true)}>
                <PlusIcon />
                {t.knowledge.create.action}
              </Button>
            </Empty>
          )}
        </div>
      </WorkspaceBody>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <form className="grid gap-4" onSubmit={submitCreate}>
            <DialogHeader>
              <DialogTitle>{t.knowledge.create.title}</DialogTitle>
              <DialogDescription>
                {t.knowledge.create.description}
              </DialogDescription>
            </DialogHeader>
            <label className="grid gap-2 text-sm font-medium">
              {t.knowledge.create.name}
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t.knowledge.create.namePlaceholder}
                maxLength={128}
                required
                autoFocus
              />
            </label>
            <label className="grid gap-2 text-sm font-medium">
              {t.knowledge.create.datasetDescription}
              <Textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder={t.knowledge.create.descriptionPlaceholder}
                maxLength={65535}
              />
            </label>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setCreateOpen(false)}
              >
                {t.knowledge.cancel}
              </Button>
              <Button
                type="submit"
                disabled={!name.trim() || createDataset.isPending}
              >
                {createDataset.isPending
                  ? t.knowledge.create.submitting
                  : t.knowledge.create.submit}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.knowledge.dataset.deleteTitle}</DialogTitle>
            <DialogDescription>
              {t.knowledge.dataset.deleteDescription}
            </DialogDescription>
          </DialogHeader>
          <p className="font-medium">{deleteTarget?.name}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              {t.knowledge.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => void confirmDelete()}
              disabled={deleteDataset.isPending}
            >
              {deleteDataset.isPending
                ? t.knowledge.dataset.deleting
                : t.knowledge.dataset.deleteConfirm}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </WorkspaceContainer>
  );
}
