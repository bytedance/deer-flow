"use client";

import {
  LibraryBig,
  PanelLeftClose,
  Plus,
  UserRound,
  Users,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import type { KnowledgeBase } from "@/core/knowledge/types";
import { cn } from "@/lib/utils";

/**
 * Left column of the knowledge page (spec §5.2): the 个人知识库 group, the
 * header「+」create dialog, and per-kb selection. Presentational — the page
 * owns data fetching and mutations.
 * The header folds its own column (`onCollapse`); the matching restore button
 * lives in the middle column's header and only appears once this one is gone,
 * so the two straddle the divider instead of competing for the same action.
 * Rows drag-to-reorder through native HTML5 drag when `onReorder` is given,
 * sortable-style: crossing a row moves the lifted row into its slot live, so
 * the list rearranges under the cursor (a translateY "make room" preview
 * instead yanked the hovered row out from under the cursor and flickered).
 * The panel reports every crossing through onReorder; the owner persists.
 */
export function KbListPanel({
  kbs,
  selectedKbId,
  onSelect,
  onCreate,
  onCollapse,
  onReorder,
}: {
  kbs: KnowledgeBase[];
  selectedKbId: string | null;
  onSelect: (kbId: string) => void;
  onCreate: (name: string, description: string) => Promise<void> | void;
  /** When set, the group header shows the fold button (push-style collapse). */
  onCollapse?: () => void;
  /** When set, rows become drag-reorderable; called with (source, target). */
  onReorder?: (sourceId: string, targetId: string) => void;
}) {
  const { t } = useI18n();
  const tk = t.knowledge;
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // Drag-reorder state: which row is lifted, and the last row it crossed.
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  // 分组折叠态（2026-09-10）：标题文字即折叠开关，两组各自记忆。
  const [personalOpen, setPersonalOpen] = useState(true);
  const [sharedOpen, setSharedOpen] = useState(true);

  const resetAndClose = () => {
    setCreateOpen(false);
    setName("");
    setDescription("");
    setSubmitting(false);
  };

  const handleCreate = async () => {
    if (!name.trim() || submitting) {
      return;
    }
    setSubmitting(true);
    try {
      await onCreate(name.trim(), description.trim());
      resetAndClose();
    } catch {
      // The page-level mutation surfaces the error toast; keep the dialog open.
      setSubmitting(false);
    }
  };

  return (
    <div className="flex h-full flex-col" data-testid="kb-list-panel">
      <div className="flex items-center gap-0.5 px-3 pt-3 pb-2">
        {/* 分组标题点击折叠（2026-09-10）：标题本身即开关（hover 变色给点击
            暗示）。chevron 已删（2026-09-25，spec §7.1）：折叠在整行上，箭头纯
           装饰，而它占宽把「个人知识库」挤折行。 */}
        <button
          aria-expanded={personalOpen}
          className="text-muted-foreground hover:text-foreground -ml-1 mr-auto flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-medium whitespace-nowrap transition-colors"
          data-testid="kb-personal-toggle"
          type="button"
          onClick={() => setPersonalOpen((open) => !open)}
        >
          {/* 分组醒目图标（2026-09-10）：单人=个人、多人=共享，色随项目强调色惯例
              （text-X-600 dark:text-X-500，同 document-panel 的 amber 用法）。 */}
          <UserRound className="text-sky-600 dark:text-sky-500 size-3.5 shrink-0" />
          {tk.personalKBs}
        </button>
        <Button
          aria-label={tk.createKB}
          className="size-6 shrink-0"
          size="icon"
          variant="ghost"
          onClick={() => setCreateOpen(true)}
        >
          <Plus className="size-4" />
        </Button>
        {onCollapse && (
          <Button
            aria-label={tk.collapseKbList}
            className="text-muted-foreground hover:text-foreground size-6 shrink-0"
            size="icon"
            variant="ghost"
            onClick={onCollapse}
          >
            <PanelLeftClose className="size-4" />
          </Button>
        )}
      </div>

      {/* 百科 Tab 容器同款 overlay 滚动条（2026-09-04）：库列表内滚改 ScrollArea
          （type="scroll"、停 2s 淡出），取代原生 overflow-y-auto。 */}
      {/* px-2 在内容层而非 Root（焦点环修复 2026-10-02）：裁剪盒是 ScrollArea 视口自己，
          Root 的留白挡不住外扩 3px 的 focus ring——留白下移到 ul/分组层后行几何不变。 */}
      <ScrollArea
        className="flex-1 pb-2"
        scrollHideDelay={2000}
        type="scroll"
      >
        {personalOpen &&
          (kbs.length === 0 ? (
          <p className="text-muted-foreground px-4 py-6 text-center text-xs">
            {tk.emptyKbList}
          </p>
        ) : (
          <ul className="flex flex-col gap-0.5 px-2 py-1">
            {kbs.map((kb) => {
              const isActive = kb.id === selectedKbId;
              return (
                <li
                  data-drag-source={dragId === kb.id ? "true" : undefined}
                  draggable={onReorder ? true : undefined}
                  key={kb.id}
                  onDragEnd={() => {
                    setDragId(null);
                    setOverId(null);
                  }}
                  onDragLeave={(event) => {
                    // Only clear when genuinely leaving the row — child
                    // elements (button, icon, text) fire dragleave too, and
                    // reacting to them re-triggered dragover and flickered.
                    if (
                      !event.currentTarget.contains(
                        event.relatedTarget as Node | null,
                      )
                    ) {
                      setOverId((cur) => (cur === kb.id ? null : cur));
                    }
                  }}
                  onDragOver={(event) => {
                    if (!onReorder || !dragId || dragId === kb.id) return;
                    event.preventDefault();
                    // dataTransfer can be absent on synthetic drag events.
                    if (event.dataTransfer)
                      event.dataTransfer.dropEffect = "move";
                    // Sortable-style: cross a row, take its slot — once per
                    // crossing, so one gesture can walk the whole list.
                    if (overId !== kb.id) {
                      setOverId(kb.id);
                      onReorder(dragId, kb.id);
                    }
                  }}
                  onDragStart={(event) => {
                    if (!onReorder) return;
                    setDragId(kb.id);
                    if (event.dataTransfer) {
                      event.dataTransfer.effectAllowed = "move";
                      event.dataTransfer.setData("text/plain", kb.id);
                    }
                  }}
                  onDrop={(event) => {
                    // The move already happened on crossing; drop just lands.
                    event.preventDefault();
                    setDragId(null);
                    setOverId(null);
                  }}
                >
                  <button
                    className={cn(
                      "hover:bg-muted/60 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                      isActive && "bg-muted font-medium",
                      dragId === kb.id && "cursor-grabbing",
                    )}
                    data-active={isActive}
                    type="button"
                    onClick={() => onSelect(kb.id)}
                  >
                    <LibraryBig className="text-muted-foreground size-4 shrink-0" />
                    <span className="min-w-0 truncate">{kb.name}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          ))}

        {/* 共享知识库（2026-09-10 纯展示）：后期规划的共享库分组预览——静态行
            （无按钮、不可拖拽、不可选中），数据未接后端，仅演示信息架构。 */}
        <div className="mt-4 flex flex-col gap-0.5 px-2" data-testid="kb-shared-group">
          <div className="flex items-center gap-1.5 px-2 pb-1">
            <button
              aria-expanded={sharedOpen}
              className="text-muted-foreground hover:text-foreground -ml-1 mr-auto flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-medium whitespace-nowrap transition-colors"
              data-testid="kb-shared-toggle"
              type="button"
              onClick={() => setSharedOpen((open) => !open)}
            >
              <Users className="text-violet-600 dark:text-violet-500 size-3.5 shrink-0" />
              {tk.sharedKBs}
            </button>
          </div>
          {sharedOpen && (
            <ul className="flex flex-col gap-0.5">
              {tk.sharedKbSamples.map((sample) => (
                <li key={sample}>
                  <div className="text-muted-foreground flex w-full cursor-default items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm">
                    <Users className="size-4 shrink-0" />
                    <span className="min-w-0 truncate">{sample}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </ScrollArea>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{tk.createKB}</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-2">
            <Input
              autoFocus
              placeholder={tk.kbNamePlaceholder}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            <Textarea
              placeholder={tk.kbDescriptionPlaceholder}
              rows={3}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={resetAndClose}>
              {t.common.cancel}
            </Button>
            <Button
              disabled={!name.trim() || submitting}
              onClick={() => void handleCreate()}
            >
              {t.common.create}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
