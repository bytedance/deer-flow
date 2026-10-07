"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { KnowledgeChatPanel } from "@/components/workspace/knowledge/chat-panel";
import { ChunkDrawer } from "@/components/workspace/knowledge/chunk-drawer";
import { DocumentPanel } from "@/components/workspace/knowledge/document-panel";
import {
  DuplicateUploadDialog,
  type DuplicateAction,
} from "@/components/workspace/knowledge/duplicate-upload-dialog";
import { KbListPanel } from "@/components/workspace/knowledge/kb-list-panel";
import { toast } from "@/components/workspace/knowledge/kb-toast";
import { MiddleTabs } from "@/components/workspace/knowledge/middle-tabs";
import { KnowledgePanelsShell } from "@/components/workspace/knowledge/panels-shell";
import { useKnowledgeBaseEnabled } from "@/core/features";
import { useI18n } from "@/core/i18n/hooks";
import { downloadDocumentSource } from "@/core/knowledge/api";
import { classifyDocError } from "@/core/knowledge/doc-errors";
import {
  computeSha256,
  findDuplicateByName,
  nextCopyName,
  verdictForDuplicate,
} from "@/core/knowledge/duplicate-check";
import { executeDuplicateAction } from "@/core/knowledge/duplicate-upload-flow";
import {
  useCreateKnowledgeBase,
  useDeleteDocument,
  useDeleteKnowledgeBase,
  useDocuments,
  useKnowledgeBases,
  useRetryDocument,
  useSupportedFormats,
  useUpdateKnowledgeBase,
  useUploadDocument,
} from "@/core/knowledge/hooks";
import { readLastKbId, useKbLocalOrder, writeLastKbId } from "@/core/knowledge/kb-order";
import { FALLBACK_SUPPORTED_SUFFIXES } from "@/core/knowledge/supported-formats";
import type { KnowledgeDocument } from "@/core/knowledge/types";
import { useDocFailureNotifier } from "@/core/knowledge/use-doc-failure-notifier";

function showMutationError(error: unknown, fallback: string) {
  toast.error(error instanceof Error && error.message ? error.message : fallback);
}

export default function KnowledgePage() {
  const { t } = useI18n();
  const tk = t.knowledge;
  // 文档类错误产品化（2026-08-30）：分类器映射友好文案，未识别回落兜底，
  // 原始英文异常文本不外露（含空文件 400、不支持格式、云端重试耗尽等）。
  const docErrorText = (error: unknown, fallback: string) => {
    const kind = classifyDocError(error instanceof Error ? error.message : "");
    return kind === "unknown" ? fallback : tk.docErrors[kind];
  };
  const searchParams = useSearchParams();
  const router = useRouter();
  const deepLinkKb = searchParams.get("kb");
  const deepLinkThread = searchParams.get("thread");

  const [selectedKbId, setSelectedKbId] = useState<string | null>(null);
  const [drawerDoc, setDrawerDoc] = useState<KnowledgeDocument | null>(null);

  // 未启用门控（RFC §6.2 四项之四）：扩展关闭时本页不轮询扩展端点——入口
  // 本身由侧栏门控隐藏，这里是直连 URL 的兜底（查询全部按旗门控 + 空态）。
  const { enabled: knowledgeEnabled } = useKnowledgeBaseEnabled();

  const kbsQuery = useKnowledgeBases(knowledgeEnabled);
  const kbs = useMemo(() => kbsQuery.data ?? [], [kbsQuery.data]);
  // User-defined display order (drag reorder, localStorage-persisted) layered
  // over the server's created_at order; unknown kbs trail in server order.
  const { ordered: orderedKbs, commitMove } = useKbLocalOrder(kbs);
  const selectedKb = orderedKbs.find((kb) => kb.id === selectedKbId) ?? null;

  // Default selection: remembered last-opened > first in the user's order;
  // the deep-link effect below outranks both. Falls back to the remaining
  // first after a delete.
  useEffect(() => {
    if (orderedKbs.length === 0) {
      if (selectedKbId !== null) {
        setSelectedKbId(null);
      }
      return;
    }
    if (!selectedKb) {
      const remembered = readLastKbId();
      const rememberedKb = remembered
        ? orderedKbs.find((kb) => kb.id === remembered)
        : undefined;
      setSelectedKbId(rememberedKb?.id ?? orderedKbs[0]!.id);
    }
  }, [orderedKbs, selectedKb, selectedKbId]);

  // Remember the open library for the next visit (best effort).
  useEffect(() => {
    if (selectedKbId) writeLastKbId(selectedKbId);
  }, [selectedKbId]);

  // Deep link effect: apply on mount or when KB param changes.
  useEffect(() => {
    if (!deepLinkKb) return;
    const kb = kbs.find((kb) => kb.id === deepLinkKb);
    if (kb) {
      if (selectedKbId !== kb.id) {
        setSelectedKbId(kb.id);
      }
      // After applying, clear the thread param but keep kb param visible.
      router.replace(`${window.location.pathname}?kb=${encodeURIComponent(deepLinkKb)}`);
    }
  }, [deepLinkKb, kbs, selectedKbId, router]);

  const documentsQuery = useDocuments(knowledgeEnabled ? selectedKbId : null);
  const documents = useMemo(() => documentsQuery.data ?? [], [documentsQuery.data]);
  // 错误产品化（2026-08-31 定案）：全局 sonner toast 退出文档错误链路（视口级，
  // 出 tab），失败条目由本层状态承接，渲染在文档 tab 内右下角面板。
  const docFailures = useDocFailureNotifier(documents);

  // Task 6 upload allowlist: endpoint is the source of truth, with a local
  // mirror as fallback until the query resolves (spec §6).
  const supportedFormatsQuery = useSupportedFormats(knowledgeEnabled);
  const supportedSuffixes = supportedFormatsQuery.data?.suffixes ?? FALLBACK_SUPPORTED_SUFFIXES;

  const createKb = useCreateKnowledgeBase();
  const updateKb = useUpdateKnowledgeBase();
  const deleteKb = useDeleteKnowledgeBase();
  const uploadDocument = useUploadDocument(selectedKbId ?? "");
  const deleteDocument = useDeleteDocument(selectedKbId ?? "");
  const retryDocument = useRetryDocument(selectedKbId ?? "");

  // ── Task 11 duplicate-upload interception ─────────────────────────────
  // Both upload entries (MiddleTabs library menu + DocumentPanel drag/pick)
  // funnel into `uploadFilesWithCheck`: hash the file, pre-check against the
  // current document list, and queue a confirm dialog on a same-name hit.
  const [pendingDuplicate, setPendingDuplicate] = useState<{
    fileName: string;
    kind: "identical" | "conflict";
    doc: KnowledgeDocument;
    copyName: string;
    resolve: (action: DuplicateAction) => void;
  } | null>(null);
  // Fresh document list for the pre-check — props in flight during the loop
  // would otherwise go stale after a replace mutation.
  const documentsRef = useRef(documents);
  useEffect(() => {
    documentsRef.current = documents;
  }, [documents]);

  const doUpload = async (file: File) => {
    try {
      await uploadDocument.mutateAsync(file);
    } catch (error) {
      docFailures.report(file.name, docErrorText(error, tk.errors.uploadFailed));
    }
  };

  const uploadFilesWithCheck = (files: File[]) => {
    void (async () => {
      for (const file of files) {
        let hash: string;
        try {
          hash = await computeSha256(file);
        } catch {
          // WebCrypto unavailable (non-secure context) — degrade to a plain
          // upload rather than blocking the pipeline.
          await doUpload(file);
          continue;
        }
        const currentDocs = documentsRef.current;
        const verdict = verdictForDuplicate(findDuplicateByName(file.name, currentDocs), hash);
        if (verdict.kind === "clean") {
          await doUpload(file);
          continue;
        }
        const copyName = nextCopyName(file.name, new Set(currentDocs.map((d) => d.name)));
        const action = await new Promise<DuplicateAction>((resolve) => {
          setPendingDuplicate({
            fileName: file.name,
            kind: verdict.kind,
            doc: verdict.doc,
            copyName,
            resolve: (chosen) => {
              setPendingDuplicate(null);
              resolve(chosen);
            },
          });
        });
        try {
          const outcome = await executeDuplicateAction(
            action,
            { file, doc: verdict.doc, copyName },
            {
              deleteDocument: (docId) => deleteDocument.mutateAsync(docId),
              uploadFile: doUpload,
            },
          );
          if (outcome === "skipped") {
            toast.info(tk.duplicateUpload.skippedDuplicate(file.name));
          } else if (outcome === "copied") {
            toast.success(tk.duplicateUpload.uploadedAsCopy(copyName));
          } else if (outcome === "replaced") {
            toast.success(tk.duplicateUpload.replacedDocument(file.name));
          }
        } catch (error) {
          docFailures.report(file.name, docErrorText(error, tk.errors.uploadFailed));
        }
      }
    })();
  };

  if (!knowledgeEnabled) {
    return (
      <div
        className="text-muted-foreground flex size-full min-h-0 items-center justify-center text-sm"
        data-testid="knowledge-page-disabled"
      >
        {tk.disabledHint}
      </div>
    );
  }

  return (
    <div className="size-full min-h-0" data-testid="knowledge-page">
      <KnowledgePanelsShell
        left={({ collapseLeft }) => (
          <KbListPanel
            kbs={orderedKbs}
            selectedKbId={selectedKbId}
            onSelect={setSelectedKbId}
            onCollapse={collapseLeft}
            onReorder={commitMove}
            onCreate={async (name, description) => {
              try {
                const created = await createKb.mutateAsync({ name, description });
                setSelectedKbId(created.id);
              } catch (error) {
                showMutationError(error, tk.errors.createFailed);
              }
            }}
          />
        )}
        middle={({ listToggle }) =>
          selectedKb ? (
            <MiddleTabs
              kb={selectedKb}
              uploading={uploadDocument.isPending}
              supportedSuffixes={supportedSuffixes}
              onUpload={uploadFilesWithCheck}
              listToggle={listToggle}
              onRenameKb={async (name) => {
                try {
                  await updateKb.mutateAsync({ kbId: selectedKb.id, patch: { name } });
                } catch (error) {
                  showMutationError(error, tk.errors.renameFailed);
                }
              }}
              onDeleteKb={async () => {
                try {
                  await deleteKb.mutateAsync(selectedKb.id);
                } catch (error) {
                  showMutationError(error, tk.errors.deleteFailed);
                }
              }}
              documents={
                <DocumentPanel
                  kb={selectedKb}
                  documents={documents}
                  supportedSuffixes={supportedSuffixes}
                  onUpload={uploadFilesWithCheck}
                  onDeleteDocument={async (docId) => {
                    try {
                      await deleteDocument.mutateAsync(docId);
                    } catch (error) {
                      showMutationError(error, tk.errors.deleteDocumentFailed);
                    }
                  }}
                  onRetryDocument={(docId) => {
                    retryDocument.mutate(docId, {
                      // 重试请求本身失败（状态仍停在 failed，hook 不会重新提醒）——
                      // 收编进同一面板，不走全局 toast。
                      onError: (error) =>
                        docFailures.report(
                          documents.find((d) => d.id === docId)?.name ?? "",
                          docErrorText(error, tk.errors.retryFailed),
                        ),
                    });
                  }}
                  onOpenChunks={setDrawerDoc}
                  onDownload={(doc) => downloadDocumentSource(selectedKb.id, doc.id)}
                  failures={docFailures.failures}
                  onDismissFailure={docFailures.dismissOne}
                  onDismissAllFailures={docFailures.dismissAll}
                />
              }
            />
          ) : (
            <div className="flex h-full min-h-0 flex-col">
              {/* Only while folded: with no library selected there is no tab
                  strip to carry the restore button, and drag-to-edge can still
                  fold the list — this is the only way back. */}
              {listToggle && (
                <div className="flex items-center gap-2 border-b px-4 py-3">{listToggle}</div>
              )}
              <div className="text-muted-foreground flex flex-1 items-center justify-center text-sm">
                {tk.selectKbHint}
              </div>
            </div>
          )
        }
        right={
          <KnowledgeChatPanel
            kb={selectedKb}
            requestedThreadId={deepLinkKb ? deepLinkThread : null}
          />
        }
      />

      {drawerDoc && selectedKbId && (
        <ChunkDrawer
          kbId={selectedKbId}
          doc={drawerDoc}
          open={drawerDoc !== null}
          onOpenChange={(open) => {
            if (!open) {
              setDrawerDoc(null);
            }
          }}
        />
      )}

      {/* Task 11 duplicate-upload confirm (queued per conflicting file) */}
      <DuplicateUploadDialog
        pending={pendingDuplicate}
        onResolve={(action) => pendingDuplicate?.resolve(action)}
      />
    </div>
  );
}
