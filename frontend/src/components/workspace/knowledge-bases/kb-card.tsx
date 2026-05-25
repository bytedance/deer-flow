"use client";

import {
  BookOpenIcon,
  FileTextIcon,
  GlobeIcon,
  LockIcon,
  PencilIcon,
  ShieldIcon,
  Trash2Icon,
  UsersIcon,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
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
import { useI18n } from "@/core/i18n/hooks";
import { useDeleteKnowledgeBase } from "@/core/knowledge-base";
import type { KnowledgeBase } from "@/core/knowledge-base";

import { KBDocumentsDialog } from "./kb-documents-dialog";
import { KBFormDialog } from "./kb-form-dialog";
import { KBPermissionsDialog } from "./kb-permissions-dialog";

interface KBCardProps {
  knowledgeBase: KnowledgeBase;
}

export function KBCard({ knowledgeBase }: KBCardProps) {
  const { t } = useI18n();
  const deleteMutation = useDeleteKnowledgeBase();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [docsOpen, setDocsOpen] = useState(false);
  const [permsOpen, setPermsOpen] = useState(false);

  const canWrite = knowledgeBase.can_write ?? false;
  const canAdmin = knowledgeBase.can_admin ?? false;

  function visibilityIcon() {
    switch (knowledgeBase.visibility) {
      case "public":
        return <GlobeIcon className="h-3 w-3" />;
      case "tenant":
        return <UsersIcon className="h-3 w-3" />;
      default:
        return <LockIcon className="h-3 w-3" />;
    }
  }

  function visibilityLabel() {
    switch (knowledgeBase.visibility) {
      case "public":
        return t.knowledgeBase.visibilityPublic;
      case "tenant":
        return t.knowledgeBase.visibilityTenant;
      default:
        return t.knowledgeBase.visibilityPrivate;
    }
  }

  function statusVariant() {
    switch (knowledgeBase.status) {
      case "active":
        return "default" as const;
      case "indexing":
        return "secondary" as const;
      default:
        return "destructive" as const;
    }
  }

  function statusLabel() {
    switch (knowledgeBase.status) {
      case "active":
        return t.knowledgeBase.statusActive;
      case "indexing":
        return t.knowledgeBase.statusIndexing;
      default:
        return t.knowledgeBase.statusError;
    }
  }

  async function handleDelete() {
    try {
      await deleteMutation.mutateAsync(knowledgeBase.id);
      toast.success(t.knowledgeBase.deleteSuccess);
      setDeleteOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <Card className="group flex flex-col transition-shadow hover:shadow-md">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <div className="bg-primary/10 text-primary flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                <BookOpenIcon className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <CardTitle className="truncate text-base">
                  {knowledgeBase.name}
                </CardTitle>
                <div className="mt-0.5 flex items-center gap-1">
                  <Badge variant={statusVariant()} className="text-xs">
                    {statusLabel()}
                  </Badge>
                  <Badge variant="outline" className="text-xs gap-1">
                    {visibilityIcon()}
                    {visibilityLabel()}
                  </Badge>
                </div>
              </div>
            </div>
          </div>
          {knowledgeBase.description && (
            <CardDescription className="mt-2 line-clamp-2 text-sm">
              {knowledgeBase.description}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="pt-0 pb-3">
          <div className="text-muted-foreground flex items-center gap-3 text-xs">
            <span>
              {knowledgeBase.document_count} {t.knowledgeBase.documentCount}
            </span>
            <span>
              {knowledgeBase.chunk_count} {t.knowledgeBase.chunks}
            </span>
            {knowledgeBase.indexed_count !== undefined && (
              <span className="text-green-600">
                {knowledgeBase.indexed_count} {t.knowledgeBase.indexedCount}
              </span>
            )}
            {knowledgeBase.failed_count !== undefined && knowledgeBase.failed_count > 0 && (
              <span className="text-red-600">
                {knowledgeBase.failed_count} {t.knowledgeBase.failedCount}
              </span>
            )}
          </div>
        </CardContent>

        <CardFooter className="mt-auto flex items-center justify-between gap-2 pt-3">
          <Button size="sm" className="flex-1" onClick={() => setDocsOpen(true)}>
            <FileTextIcon className="mr-1.5 h-3.5 w-3.5" />
            {t.knowledgeBase.documents}
          </Button>
          <div className="flex gap-1">
            {canAdmin && (
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8 shrink-0"
                onClick={() => setPermsOpen(true)}
                title={t.knowledgeBase.permissions}
              >
                <ShieldIcon className="h-3.5 w-3.5" />
              </Button>
            )}
            {canWrite && (
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8 shrink-0"
                onClick={() => setEditOpen(true)}
                title={t.common.edit}
              >
                <PencilIcon className="h-3.5 w-3.5" />
              </Button>
            )}
            {canAdmin && (
              <Button
                size="icon"
                variant="ghost"
                className="text-destructive hover:text-destructive h-8 w-8 shrink-0"
                onClick={() => setDeleteOpen(true)}
                title={t.knowledgeBase.delete}
              >
                <Trash2Icon className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </CardFooter>
      </Card>

      <KBFormDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        knowledgeBase={knowledgeBase}
      />

      <KBDocumentsDialog
        open={docsOpen}
        onOpenChange={setDocsOpen}
        knowledgeBase={knowledgeBase}
      />

      <KBPermissionsDialog
        open={permsOpen}
        onOpenChange={setPermsOpen}
        knowledgeBase={knowledgeBase}
      />

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.knowledgeBase.delete}</DialogTitle>
            <DialogDescription>
              {t.knowledgeBase.deleteConfirm}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteMutation.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? t.common.loading : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
