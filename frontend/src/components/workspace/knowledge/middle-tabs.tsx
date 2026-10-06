"use client";

import { BookOpen, Loader2, MoreHorizontal, Pencil, RefreshCw, Trash2, Upload } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { useI18n } from "@/core/i18n/hooks";
import type { WikiGenerateMode } from "@/core/knowledge/api";
import { acceptAttribute, partitionFilesBySuffix } from "@/core/knowledge/supported-formats";
import type { KnowledgeBase } from "@/core/knowledge/types";

import { toast } from "./kb-toast";
import { runAfterMenuClose } from "./run-after-menu-close";
import { TabStrip } from "./tab-strip";
import { WikiRebuildDialog } from "./wiki-rebuild-dialog";

export type KnowledgeMiddleTab = "documents" | "wiki" | "recall" | "vectors" | "graph" | "eval";

/**
 * Middle-column container (phase-2 batch-1, spec §3 三行结构):
 *   row 1 — library header: kb-list restore overlay (a hover-revealed control
 *           the panels shell fills only once the list is folded, so it never
 *           overlays a document row) + kb name +
 *           overflow menu (generate wiki / rename /
 *           delete — library-scoped, visible for every tab);
 *   row 2 — the 文档|百科|检索测试 tab strip;
 *   row 3 — tab panes, keep-alive via forceMount so switching never unmounts
 *           the document table (search/sort/selection state and the indexing
 *           refetch interval survive), the wiki list, or the recall-test
 *           panel's last result.
 * Upload lives in the library menu (adding a document is a library-level
 * action, like generate-wiki/rename); the documents pane keeps its toolbar
 * lean (search + sort) and still accepts drag-drop anywhere on the pane.
 */
export function MiddleTabs({
  kb,
  activeTab,
  onTabChange,
  onUpload,
  uploading = false,
  supportedSuffixes,
  onGenerateWiki,
  wikiUpdating = false,
  onRenameKb,
  onDeleteKb,
  listToggle,
  documents,
  wiki,
  recall,
  vectors,
  graph,
  eval: evalPane,
}: {
  kb: KnowledgeBase;
  activeTab: KnowledgeMiddleTab;
  onTabChange: (tab: KnowledgeMiddleTab) => void;
  onUpload: (files: File[]) => void;
  uploading?: boolean;
  /** Upload allowlist (Task 6, spec §6): gates the picker accept + intercept. */
  supportedSuffixes: readonly string[];
  onGenerateWiki: (mode: WikiGenerateMode) => void;
  /**
   * Wiki 更新状态可见 (2026-08-14): a generation run is in flight — the
   * trigger items disable to prevent duplicate queueing and the 更新百科
   * item shows a spinner.
   */
  wikiUpdating?: boolean;
  onRenameKb: (name: string) => Promise<void> | void;
  onDeleteKb: () => Promise<void> | void;
  /**
   * kb-list restore overlay, always provided by the panels shell but CSS-gated
   * to reveal only once the list column has folded and settled. Rendered over
   * the library name's start — the workspace header's DF hover-swap pattern —
   * absolutely positioned, so it never takes layout and the name keeps a
   * single position. The list header's own collapse button is the other half
   * of the pair, on the far side of the same divider.
   */
  listToggle?: ReactNode;
  documents: ReactNode;
  wiki: ReactNode;
  recall: ReactNode;
  vectors: ReactNode;
  /** 知识图谱 pane（2026-08-19 spec）：实体关系力导向图。 */
  graph: ReactNode;
  /** 评测 pane（2026-08-24 spec §5，plan Task 4）：指标总览 + 趋势图。 */
  eval: ReactNode;
}) {
  const { t } = useI18n();
  const tk = t.knowledge;
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState(kb.name);
  const [deleteKbOpen, setDeleteKbOpen] = useState(false);
  const [rebuildOpen, setRebuildOpen] = useState(false);

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="knowledge-middle-tabs">
      {/* Row 1: library header (fold toggle + name + library-level overflow menu) */}
      <div className="relative flex items-center gap-2 border-b px-4 py-3">
        {/* The kb-list restore overlay (2026-09-02): absolutely positioned by
            the shell relative to this relative row → zero layout advance in
            every fold phase. It is its own hover target, sized exactly to the
            chip: a precise hit reveals a single opaque state — a wider zone
            with a semi-transparent backdrop read as smudged text under the
            button. */}
        {listToggle}
        <h2 className="min-w-0 truncate text-sm font-semibold">{kb.name}</h2>
        <Badge className="shrink-0" variant="outline">{t.knowledge.personalKBs}</Badge>
        <div className="ml-auto flex shrink-0 items-center">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button aria-label={tk.settings} size="sm" variant="ghost">
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem
                disabled={uploading}
                onSelect={() => fileInputRef.current?.click()}
              >
                <Upload className="size-4" />
                {uploading ? tk.uploadingDocuments : tk.uploadDocuments}
              </DropdownMenuItem>
              <DropdownMenuItem disabled={wikiUpdating} onSelect={() => onGenerateWiki("incremental")}>
                {wikiUpdating ? <Loader2 className="size-4 animate-spin" /> : <BookOpen className="size-4" />}
                {wikiUpdating ? tk.wikiPanel.updating : tk.updateWiki}
              </DropdownMenuItem>
              <DropdownMenuItem disabled={wikiUpdating} onSelect={() => runAfterMenuClose(() => setRebuildOpen(true))}>
                <RefreshCw className="size-4" />
                {tk.rebuildWiki}
              </DropdownMenuItem>
              {/* 知识库管理段（2026-08-30）：重命名/删除补图标，两项独占一个分界段；
                  分界上移到重命名之前，段内不再隔断 */}
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => {
                  setRenameValue(kb.name);
                  runAfterMenuClose(() => setRenameOpen(true));
                }}
              >
                <Pencil className="size-4" />
                {tk.renameKb}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onSelect={() => runAfterMenuClose(() => setDeleteKbOpen(true))}
              >
                <Trash2 className="size-4" />
                {tk.deleteKb}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <input
          ref={fileInputRef}
          multiple
          accept={acceptAttribute(supportedSuffixes)}
          className="hidden"
          data-testid="document-upload-input"
          type="file"
          onChange={(event) => {
            const files = event.target.files;
            if (files && files.length > 0) {
              // Task 6: pre-upload allowlist intercept (accept is advisory;
              // users can still pick anything via "all files").
              const { accepted, rejected } = partitionFilesBySuffix(Array.from(files), supportedSuffixes);
              if (rejected.length > 0) {
                toast.error(tk.unsupportedFilesSkipped(rejected.map((f) => f.name).join(", ")));
              }
              if (accepted.length > 0) {
                onUpload(accepted);
              }
            }
            event.target.value = "";
          }}
        />
      </div>

      {/* Rows 2+3: tab strip + keep-alive panes */}
      <Tabs
        className="min-h-0 flex-1 gap-0"
        value={activeTab}
        onValueChange={(value) => onTabChange(value as KnowledgeMiddleTab)}
      >
        <TabStrip<KnowledgeMiddleTab>
          activeTab={activeTab}
          onTabChange={onTabChange}
          tabs={[
            { value: "documents", label: tk.tabs.documents },
            { value: "wiki", label: tk.tabs.wiki },
            { value: "recall", label: tk.tabs.recall },
            { value: "vectors", label: tk.tabs.vectors },
            { value: "graph", label: tk.tabs.graph },
            { value: "eval", label: tk.tabs.eval },
          ]}
        />
        <TabsContent
          className="min-h-0 data-[state=inactive]:hidden"
          forceMount
          value="documents"
        >
          <div className="flex h-full min-h-0 flex-col">{documents}</div>
        </TabsContent>
        <TabsContent
          className="min-h-0 data-[state=inactive]:hidden"
          forceMount
          value="wiki"
        >
          <div className="flex h-full min-h-0 flex-col">{wiki}</div>
        </TabsContent>
        <TabsContent
          className="min-h-0 data-[state=inactive]:hidden"
          forceMount
          value="recall"
        >
          <div className="flex h-full min-h-0 flex-col">{recall}</div>
        </TabsContent>
        <TabsContent
          className="min-h-0 data-[state=inactive]:hidden"
          forceMount
          value="vectors"
        >
          <div className="flex h-full min-h-0 flex-col">{vectors}</div>
        </TabsContent>
        <TabsContent
          className="min-h-0 data-[state=inactive]:hidden"
          forceMount
          value="graph"
        >
          <div className="flex h-full min-h-0 flex-col">{graph}</div>
        </TabsContent>
        <TabsContent
          className="min-h-0 data-[state=inactive]:hidden"
          forceMount
          value="eval"
        >
          <div className="flex h-full min-h-0 flex-col">{evalPane}</div>
        </TabsContent>
      </Tabs>

      {/* Rename dialog */}
      <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{tk.renameKb}</DialogTitle>
          </DialogHeader>
          <div className="py-2">
            <Input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameOpen(false)}>
              {t.common.cancel}
            </Button>
            <Button
              disabled={!renameValue.trim()}
              onClick={() => {
                void onRenameKb(renameValue.trim());
                setRenameOpen(false);
              }}
            >
              {t.common.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* KB delete confirm (cascade warning, spec §3.7) */}
      <Dialog open={deleteKbOpen} onOpenChange={setDeleteKbOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{tk.deleteKbConfirmTitle}</DialogTitle>
            <DialogDescription>{tk.deleteKbConfirmDescription}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteKbOpen(false)}>
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                void onDeleteKb();
                setDeleteKbOpen(false);
              }}
            >
              {t.common.confirmDelete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {/* Wiki full-rebuild confirm (Task 14: full mode is for rule upgrades;
          2026-08-30 抽出共享组件，百科 tab 内 ⋯ 菜单复用同一弹窗) */}
      <WikiRebuildDialog
        open={rebuildOpen}
        onOpenChange={setRebuildOpen}
        onConfirm={() => {
          onGenerateWiki("full");
          setRebuildOpen(false);
        }}
      />
    </div>
  );
}
