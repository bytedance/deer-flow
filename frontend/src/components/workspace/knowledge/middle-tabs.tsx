"use client";

import { MoreHorizontal, Pencil, Trash2, Upload } from "lucide-react";
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
import { acceptAttribute, partitionFilesBySuffix } from "@/core/knowledge/supported-formats";
import type { KnowledgeBase } from "@/core/knowledge/types";

import { toast } from "./kb-toast";
import { runAfterMenuClose } from "./run-after-menu-close";
import { TabStrip } from "./tab-strip";

export type KnowledgeMiddleTab = "documents";

/**
 * Middle-column container (phase-2 batch-1, spec §3 三行结构; 首期收窄):
 *   row 1 — library header: kb-list restore overlay (a hover-revealed control
 *           the panels shell fills only once the list is folded, so it never
 *           overlays a document row) + kb name +
 *           overflow menu (upload / rename / delete — library-scoped);
 *   row 2 — the documents tab strip;
 *   row 3 — the documents pane, keep-alive via forceMount so switching never
 *           unmounts the document table (search/sort/selection state and the
 *           indexing refetch interval survive).
 * Upload lives in the library menu (adding a document is a library-level
 * action); the documents pane keeps its toolbar lean (search + sort) and
 * still accepts drag-drop anywhere on the pane.
 */
export function MiddleTabs({
  kb,
  onUpload,
  uploading = false,
  supportedSuffixes,
  onRenameKb,
  onDeleteKb,
  listToggle,
  documents,
}: {
  kb: KnowledgeBase;
  onUpload: (files: File[]) => void;
  uploading?: boolean;
  /** Upload allowlist (Task 6, spec §6): gates the picker accept + intercept. */
  supportedSuffixes: readonly string[];
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
}) {
  const { t } = useI18n();
  const tk = t.knowledge;
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [activeTab, setActiveTab] = useState<KnowledgeMiddleTab>("documents");
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState(kb.name);
  const [deleteKbOpen, setDeleteKbOpen] = useState(false);

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="knowledge-middle-tabs">
      {/* Row 1: library header (fold toggle + name + library-level overflow menu) */}
      <div
        className="relative flex h-12 items-center gap-2 border-b px-4"
        data-testid="knowledge-middle-header"
      >
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

      {/* Rows 2+3: tab strip + keep-alive pane */}
      <Tabs
        className="min-h-0 flex-1 gap-0"
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as KnowledgeMiddleTab)}
      >
        <TabStrip<KnowledgeMiddleTab>
          activeTab={activeTab}
          onTabChange={setActiveTab}
          tabs={[{ value: "documents", label: tk.tabs.documents }]}
        />
        <TabsContent
          className="min-h-0 data-[state=inactive]:hidden"
          forceMount
          value="documents"
        >
          <div className="flex h-full min-h-0 flex-col">{documents}</div>
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
    </div>
  );
}
