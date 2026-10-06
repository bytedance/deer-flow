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
import { EvalTab } from "@/components/workspace/knowledge/eval-tab";
import { GraphTab } from "@/components/workspace/knowledge/graph-tab";
import { KbListPanel } from "@/components/workspace/knowledge/kb-list-panel";
import { toast } from "@/components/workspace/knowledge/kb-toast";
import { ManualCardDrawer } from "@/components/workspace/knowledge/manual-card-drawer";
import { MiddleTabs, type KnowledgeMiddleTab } from "@/components/workspace/knowledge/middle-tabs";
import { KnowledgePanelsShell } from "@/components/workspace/knowledge/panels-shell";
import { RecallTestPanel } from "@/components/workspace/knowledge/recall-test-panel";
import { VectorTab } from "@/components/workspace/knowledge/vector-tab";
import { WikiEditDialog } from "@/components/workspace/knowledge/wiki-edit-dialog";
import { WikiEntryDrawer } from "@/components/workspace/knowledge/wiki-entry-drawer";
import { WikiTab } from "@/components/workspace/knowledge/wiki-tab";
import { useI18n } from "@/core/i18n/hooks";
import { downloadDocumentSource, type WikiGenerateMode } from "@/core/knowledge/api";
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
  useDeleteWikiEntry,
  useDocuments,
  useGenerateWiki,
  useKnowledgeBases,
  useRegenerateWikiEntries,
  useRetryDocument,
  useSupportedFormats,
  useTriggerSynthesis,
  useUpdateKnowledgeBase,
  useUpdateWikiEntry,
  useUploadDocument,
  useWikiEntries,
  useWikiEntry,
} from "@/core/knowledge/hooks";
import { readLastKbId, useKbLocalOrder, writeLastKbId } from "@/core/knowledge/kb-order";
import { FALLBACK_SUPPORTED_SUFFIXES } from "@/core/knowledge/supported-formats";
import type {
  GraphRetrievalOverlay,
  KnowledgeDocument,
  VectorRetrievalOverlay,
  WikiEntrySummary,
} from "@/core/knowledge/types";
import { useDocFailureNotifier } from "@/core/knowledge/use-doc-failure-notifier";
import { isWikiUpdating } from "@/core/knowledge/wiki-status";

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
  // 检索测试切片行跳转（2026-09-05 两层重设计）：切片总览抽屉打开后定位该切片。
  const [chunkFocusId, setChunkFocusId] = useState<string | null>(null);
  // Middle-column tab + entry drawer state (phase-2 batch-1). The drawer is
  // an overlay — opening it never switches the tab; only the drawer's
  // explicit 在百科 tab 中查看 action navigates (revealWikiEntry).
  const [activeTab, setActiveTab] = useState<KnowledgeMiddleTab>("documents");
  // 复现预填通道（2026-08-27 spec §7.2）：评测侧 ↗ 携带 query 切召回 tab 预填；
  // RecallTestPanel 消费后回调清空（onViewInVectorSpace/setVectorOverlay 同构先例）。
  const [recallPrefill, setRecallPrefill] = useState<string | null>(null);
  const [drawerEntryId, setDrawerEntryId] = useState<string | null>(null);
  // Phase-3 P6 混排修复：检索测试 wiki 路命中人工卡片时开卡片抽屉（卡片
  // id 走 wiki 详情接口必然 404）。
  const [drawerCardId, setDrawerCardId] = useState<string | null>(null);
  // Wiki 更新状态可见 (2026-08-14): a manual trigger keeps the entries query
  // enabled (hence polling) even off the wiki tab — the trigger menu lives in
  // the library header, visible from every tab. Cleared on the observed
  // generating→idle transition or on kb switch (code-review finding).
  const [wikiRunActive, setWikiRunActive] = useState(false);
  // Phase-3 Batch-1 P1: wiki entry editing state
  const [editingEntryId, setEditingEntryId] = useState<string | null>(null);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  // P6 检索联动（2026-08-15 spec §9）：recall 一键跳转与 chat 每轮跟随共享的
  // 叠加请求。recall 通道同时切 tab（显式动作）；chat 通道只更新 state——
  // 向量 tab 的「跟随对话」开关决定何时应用（冻结语义在 VectorTab 内）。
  const [vectorOverlay, setVectorOverlay] = useState<VectorRetrievalOverlay | null>(null);
  // P4 图谱路径高亮（2026-08-19 spec §7）：chat 每轮 graph_search 轨迹的
  // 平行叠加通道——只更新 state，不切 tab（冻结语义在 GraphTab 内）。
  const [graphOverlay, setGraphOverlay] = useState<GraphRetrievalOverlay | null>(null);
  // 「跟随对话」开关状态两 tab 共享（spec §7 同一开关语义，两处生效）。
  const [followChat, setFollowChat] = useState(true);

  const kbsQuery = useKnowledgeBases();
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

  const documentsQuery = useDocuments(selectedKbId);
  const documents = useMemo(() => documentsQuery.data ?? [], [documentsQuery.data]);
  // 错误产品化（2026-08-31 定案）：全局 sonner toast 退出文档错误链路（视口级，
  // 出 tab），失败条目由本层状态承接，渲染在文档 tab 内右下角面板。
  const docFailures = useDocFailureNotifier(documents);
    // 向量空间索引中提示：仍在管线（未 ready/failed）的文档数。
    const indexingDocCount = useMemo(
      () => documents.filter((doc) => doc.status !== "ready" && doc.status !== "failed").length,
      [documents],
    );
  // Lazy: the wiki list fetches once its tab is first activated or a manual
  // update run is triggered (keep-alive panes stay mounted — the gate is
  // what keeps it lazy).
  const wikiEntriesQuery = useWikiEntries(selectedKbId, activeTab === "wiki" || wikiRunActive);
  const wikiEntries = wikiEntriesQuery.data?.entries ?? [];

  // Task 6 upload allowlist: endpoint is the source of truth, with a local
  // mirror as fallback until the query resolves (spec §6).
  const supportedFormatsQuery = useSupportedFormats();
  const supportedSuffixes = supportedFormatsQuery.data?.suffixes ?? FALLBACK_SUPPORTED_SUFFIXES;

  const openWikiEntry = (entry: WikiEntrySummary) => setDrawerEntryId(entry.id);
  const revealWikiEntry = (entryId: string) => {
    setActiveTab("wiki");
    setDrawerEntryId(null);
    void entryId; // the list is unpaginated — the entry is visible after the switch
  };
  // Phase-3 Batch-1 P1: open edit dialog for a wiki entry
  const handleEditEntry = (entry: WikiEntrySummary) => {
    setEditingEntryId(entry.id);
    setEditDialogOpen(true);
  };

  const createKb = useCreateKnowledgeBase();
  const updateKb = useUpdateKnowledgeBase();
  const deleteKb = useDeleteKnowledgeBase();
  const uploadDocument = useUploadDocument(selectedKbId ?? "");
  const deleteDocument = useDeleteDocument(selectedKbId ?? "");
  const retryDocument = useRetryDocument(selectedKbId ?? "");
  const triggerSynthesis = useTriggerSynthesis(selectedKbId ?? "");
  const generateWiki = useGenerateWiki(selectedKbId ?? "");
  const regenerateWikiEntries = useRegenerateWikiEntries(selectedKbId ?? "");
  const deleteWikiEntry = useDeleteWikiEntry(selectedKbId ?? "");
  const updateWikiEntry = useUpdateWikiEntry(selectedKbId ?? "");

  // Wiki 更新状态可见 (2026-08-14): live 更新中 feedback + completion toast.
  // `isPending` covers the click→first-poll gap; the toast observes the
  // server-reported generating→idle transition, so a no-op run or a missed
  // poll never produces a phantom 已更新.
  const wikiUpdating = isWikiUpdating(wikiEntriesQuery.data, generateWiki.isPending || regenerateWikiEntries.isPending);
  // 局部更新在飞目标（2026-09-05）：库级 wikiUpdating 只表示「有 run 在飞」，不表示
  // 「哪些行在更新」。单条/多选重生成记录目标 ids，仅这些行显示更新中；整库 run
  // 清空 ids → 全部 dirty 行显示更新中（原语义）。
  // 清空时机 = 排空边(generating→idle)/onError/already_running/切库/整库 run；
  // 绝不能用 !wikiUpdating 清——202 ack→in-flight 间隙 wikiUpdating 会短暂为假，
  // 在那一刻清 ids 会退化成整库语义（全部 dirty 一起闪更新中）。
  const [regeneratingIds, setRegeneratingIds] = useState<string[]>([]);
  const wikiManualRunRef = useRef(false);
  const prevWikiGenerationRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    wikiManualRunRef.current = false;
    prevWikiGenerationRef.current = undefined;
    setWikiRunActive(false);
    setRegeneratingIds([]);
  }, [selectedKbId]);
  useEffect(() => {
    const generation = wikiEntriesQuery.data?.generation;
    const prev = prevWikiGenerationRef.current;
    prevWikiGenerationRef.current = generation;
    const drained = prev === "generating" && generation === "idle";
    // run 排空 → 局部目标已无意义，清空（不论是否手动触发）。
    if (drained) setRegeneratingIds([]);
    if (drained && wikiManualRunRef.current) {
      wikiManualRunRef.current = false;
      setWikiRunActive(false);
      // P1 失败可见性 (2026-08-14): a crashed run also drains the flag —
      // toast the truth instead of the success copy.
      if (wikiEntriesQuery.data?.last_run === "failed") {
        toast.error(tk.wikiUpdateFailed);
      } else {
        toast.success(tk.wikiUpdated);
      }
    }
  }, [wikiEntriesQuery.data, tk.wikiUpdated, tk.wikiUpdateFailed]);
  // Fetch full entry detail when editing
  const editingEntryQuery = useWikiEntry(selectedKbId, editingEntryId);
  const editingEntry = editingEntryQuery.data ?? null;

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

  // 百科生成触发器（2026-08-30）：全局库菜单与百科 tab 内 ⋯ 双入口共用同一逻辑。
  const handleGenerateWiki = (mode: WikiGenerateMode) => {
    // 整库 run：清空局部目标 → 全部 dirty 行显示「更新中」（原语义）。
    setRegeneratingIds([]);
    generateWiki.mutate(mode, {
      onSuccess: (ack) => {
        // P1 触发幂等 (2026-08-14): a run is already draining the
        // dirty set (manual or worker-auto) — inform, but don't
        // arm the completion toast for a run we didn't start.
        if (ack.status === "already_running") {
          toast.info(tk.wikiAlreadyRunning);
          return;
        }
        // Start toast stays (the trigger lives in the library
        // menu, visible from every tab); the completion toast
        // fires on the generating→idle transition above. The run
        // flag keeps the entries query polling from any tab.
        wikiManualRunRef.current = true;
        setWikiRunActive(true);
        toast.success(tk.wikiEnqueued);
      },
      onError: (error) => showMutationError(error, tk.errors.wikiFailed),
    });
  };

  // 局部更新/重建触发器（2026-09-02）：百科条目右键菜单（单条/多选）传入
  // 手选 entry_ids。ack 处理与 handleGenerateWiki 同构：后端复用同一库级
  // in-flight/轮询/完成信号，故沿用同一套 already_running 提示与完成 toast。
  const handleRegenerateEntries = (entryIds: string[]) => {
    // 局部 run：仅目标行显示「更新中」，其余 dirty 行保持「待更新」。
    setRegeneratingIds(entryIds);
    regenerateWikiEntries.mutate(entryIds, {
      onSuccess: (ack) => {
        if (ack.status === "already_running") {
          // 在飞的是别人的 run（目标未知）→ 回退整库语义。
          setRegeneratingIds([]);
          toast.info(tk.wikiAlreadyRunning);
          return;
        }
        wikiManualRunRef.current = true;
        setWikiRunActive(true);
        toast.success(tk.wikiEnqueued);
      },
      onError: (error) => {
        setRegeneratingIds([]);
        showMutationError(error, tk.errors.wikiFailed);
      },
    });
  };

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
              activeTab={activeTab}
              onTabChange={setActiveTab}
              uploading={uploadDocument.isPending}
              supportedSuffixes={supportedSuffixes}
              onUpload={uploadFilesWithCheck}
              onGenerateWiki={handleGenerateWiki}
              wikiUpdating={wikiUpdating}
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
                  onDownload={(doc) =>
                    downloadDocumentSource(selectedKb.id, doc.id)
                  }
                  onGenerateQuestion={async (docIds) => {
                    // 右键快捷出题（2026-09-02）：出一条，合并进待审候选（后端合并语义）；
                    // 通知与评测页生成对话框同款（stk.generating），停留文档页。
                    const stk = tk.eval.synthesize;
                    try {
                      const response = await triggerSynthesis.mutateAsync({ doc_ids: docIds, count: 1 });
                      if (response.status === "enqueued") {
                        toast.success(stk.generating);
                      } else {
                        toast.info(stk.generating);
                      }
                    } catch (error) {
                      toast.error(error instanceof Error && error.message ? error.message : stk.triggerFailed);
                    }
                  }}
                  failures={docFailures.failures}
                  onDismissFailure={docFailures.dismissOne}
                  onDismissAllFailures={docFailures.dismissAll}
                />
              }
              wiki={
<WikiTab
                  entries={wikiEntries}
                  kbId={selectedKb.id}
                  entriesLoading={wikiEntriesQuery.isLoading}
                  updating={wikiUpdating}
                  updatingEntryIds={regeneratingIds}
                  active={activeTab === "wiki"}
                  onGenerateWiki={handleGenerateWiki}
                  onRegenerateEntries={handleRegenerateEntries}
                  onDeleteEntry={(entry) => {
                    deleteWikiEntry.mutate(entry.id, {
                      onError: (error) => showMutationError(error, tk.errors.deleteWikiEntryFailed),
                    });
                  }}
                  onEditEntry={handleEditEntry}
                  onOpenCard={(cardId) => setDrawerCardId(cardId)}
                  onOpenEntry={openWikiEntry}
                />
              }
              recall={
                <RecallTestPanel
                  kbId={selectedKb.id}
                  onPrefillConsumed={() => setRecallPrefill(null)}
                  onOpenWikiEntry={(entryId) => setDrawerEntryId(entryId)}
                  onOpenManualCard={(cardId) => setDrawerCardId(cardId)}
                  onOpenChunkHit={(chunkId) => {
                    // chunk_id 形如 `{doc_id}#NNNN`：回查文档对象开切片总览抽屉并定位。
                    const docId = chunkId.split("#")[0]!;
                    const doc = documents.find((item) => item.id === docId);
                    if (doc) {
                      setChunkFocusId(chunkId);
                      setDrawerDoc(doc);
                    }
                  }}
                  /* 2026-09-05：「在向量空间查看」收为检索工具栏右侧图标按钮
                     （不再独占一行），接线恢复。 */
                  onViewInVectorSpace={(next) => {
                    setVectorOverlay(next);
                    setActiveTab("vectors");
                  }}
                  prefillQuery={recallPrefill}
                />
              }
              vectors={
                <VectorTab
                  kbId={selectedKb.id}
                  enabled={activeTab === "vectors"}
                  indexingCount={indexingDocCount}
                  overlay={vectorOverlay}
                  followChat={followChat}
                  onFollowChatChange={setFollowChat}
                  onOpenChunk={(docId, chunkId) => {
                    // 指纹缓存与文档列表同源——正常必命中；防御性忽略。
                    // 2026-09-05：与检索测试同链路——开抽屉并定位该切片（闪环 + 当前 #K）。
                    const doc = documents.find((item) => item.id === docId);
                    if (doc) {
                      setChunkFocusId(chunkId);
                      setDrawerDoc(doc);
                    }
                  }}
                  onOpenWikiEntry={(entryId) => setDrawerEntryId(entryId)}
                  onOpenManualCard={(cardId) => setDrawerCardId(cardId)}
                />
              }
              graph={
                <GraphTab
                  documents={documents}
                  enabled={activeTab === "graph"}
                  kbId={selectedKb.id}
                  overlay={graphOverlay}
                  followChat={followChat}
                  onFollowChatChange={setFollowChat}
                  onOpenChunk={(docId, chunkId) => {
                    // 与向量空间同一链路（2026-09-05 补齐定位）：回查文档对象开抽屉
                    // 并定位该切片（chunkFocusId 闪环 + 「当前 #K」）。
                    const doc = documents.find((item) => item.id === docId);
                    if (doc) {
                      setChunkFocusId(chunkId);
                      setDrawerDoc(doc);
                    }
                  }}
                />
              }
              eval={
                // keep-alive 懒门控：仅评测 tab 激活后才发请求（useWikiEntries 先例，
                // plan Task 5）。粒度 state 在 EvalTab 内部（进 queryKey）。
                <EvalTab
                  enabled={activeTab === "eval"}
                  kbId={selectedKb.id}
                  onReproduce={(query) => {
                    setRecallPrefill(query);
                    setActiveTab("recall");
                  }}
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
            onOpenWikiEntry={(entryId) => setDrawerEntryId(entryId)}
            onRetrievalOverlay={setVectorOverlay}
            onGraphOverlay={setGraphOverlay}
            requestedThreadId={deepLinkKb ? deepLinkThread : null}
          />
        }
      />

      {drawerDoc && selectedKbId && (
        <ChunkDrawer
          kbId={selectedKbId}
          doc={drawerDoc}
          open={drawerDoc !== null}
          focusChunkId={chunkFocusId}
          onOpenChange={(open) => {
            if (!open) {
              setDrawerDoc(null);
              setChunkFocusId(null);
            }
          }}
        />
      )}

      {drawerEntryId && selectedKbId && (
        <WikiEntryDrawer
          entryId={drawerEntryId}
          kbId={selectedKbId}
          open={drawerEntryId !== null}
          onOpenChange={(open) => {
            if (!open) {
              setDrawerEntryId(null);
            }
          }}
          onRevealInTab={revealWikiEntry}
        />
      )}

      {drawerCardId && selectedKbId && (
        <ManualCardDrawer
          cardId={drawerCardId}
          kbId={selectedKbId}
          open={drawerCardId !== null}
          onOpenChange={(open) => {
            if (!open) {
              setDrawerCardId(null);
            }
          }}
        />
      )}

      {/* Task 11 duplicate-upload confirm (queued per conflicting file) */}
      <DuplicateUploadDialog
        pending={pendingDuplicate}
        onResolve={(action) => pendingDuplicate?.resolve(action)}
      />

      {/* Phase-3 Batch-1 P1: Wiki entry edit dialog */}
      {editingEntry && (
        <WikiEditDialog
          entry={editingEntry}
          open={editDialogOpen}
          onOpenChange={setEditDialogOpen}
          onSave={async (entryId, content, supplementContent) => {
            try {
              await updateWikiEntry.mutateAsync({
                entryId,
                body: { content, supplement_content: supplementContent },
              });
              toast.success("Wiki 条目已更新");
              setEditingEntryId(null);
            } catch (error) {
              showMutationError(error, "更新 Wiki 条目失败");
              throw error; // Re-throw to keep dialog open on error
            }
          }}
        />
      )}
    </div>
  );
}
