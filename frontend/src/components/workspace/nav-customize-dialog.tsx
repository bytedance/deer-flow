"use client";

import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  GripVerticalIcon,
  LockIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useNavGateContext } from "@/components/workspace/nav-gate";
import { useI18n } from "@/core/i18n/hooks";
import { useLocalSettings } from "@/core/settings/hooks";
import {
  mergeNavLayout,
  moveNavItem,
  resolveNavLayout,
  type NavGroup,
} from "@/core/settings/nav-layout";
import { cn } from "@/lib/utils";

import { NAV_ITEMS, type NavItemDefinition } from "./nav-registry";

function SortableRow({
  item,
  group,
  disabled,
  disabledReason,
  indicator,
  onMove,
}: {
  item: NavItemDefinition;
  group: NavGroup;
  disabled: boolean;
  disabledReason: string;
  indicator: boolean;
  onMove: () => void;
}) {
  const { t } = useI18n();
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: item.key, data: { group } });
  const Icon = item.icon;
  const label = item.label(t);
  const moveLabel =
    group === "primary"
      ? t.sidebar.moveToMore(label)
      : t.sidebar.moveToMenu(label);
  // A disabled feature is still movable, so only the label is greyed and
  // explained; the drag handle and the move button stay operative.
  const description = (
    <>
      <Icon
        className={cn(
          "size-4",
          disabled ? "text-muted-foreground/50" : "text-muted-foreground",
        )}
      />
      <span
        className={cn(
          "flex-1 truncate text-sm",
          disabled && "text-muted-foreground/50",
        )}
      >
        {label}
      </span>
    </>
  );

  return (
    <li
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
      }}
      className={cn(
        "bg-background flex items-center gap-2 rounded-md border px-2 py-1.5",
        isDragging && "z-10 opacity-70 shadow-md",
        indicator && "shadow-[inset_0_2px_0_var(--primary)]",
      )}
    >
      <button
        type="button"
        className="text-muted-foreground cursor-grab touch-none"
        aria-label={t.sidebar.dragToReorder(label)}
        {...attributes}
        {...listeners}
        aria-describedby={
          disabled
            ? `${item.key}-dialog-disabled-reason`
            : attributes["aria-describedby"]
        }
      >
        <GripVerticalIcon className="size-4" />
      </button>
      {disabled ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <div
              className="flex min-w-0 flex-1 cursor-help items-center gap-2"
              aria-label={label}
              aria-describedby={`${item.key}-dialog-disabled-reason`}
            >
              {description}
            </div>
          </TooltipTrigger>
          <TooltipContent side="top">{disabledReason}</TooltipContent>
        </Tooltip>
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {description}
        </div>
      )}
      {disabled && (
        <span id={`${item.key}-dialog-disabled-reason`} className="sr-only">
          {disabledReason}
        </span>
      )}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={moveLabel}
            aria-describedby={
              disabled ? `${item.key}-dialog-disabled-reason` : undefined
            }
            onClick={onMove}
          >
            {group === "primary" ? <ArrowRightIcon /> : <ArrowLeftIcon />}
          </Button>
        </TooltipTrigger>
        <TooltipContent side="left">{moveLabel}</TooltipContent>
      </Tooltip>
    </li>
  );
}

function LockedRow({ item }: { item: NavItemDefinition }) {
  const { t } = useI18n();
  const Icon = item.icon;
  return (
    <li className="text-muted-foreground flex items-center gap-2 rounded-md border border-dashed px-2 py-1.5">
      <LockIcon className="size-4" aria-hidden />
      <Icon className="size-4" />
      <span className="flex-1 truncate text-sm">{item.label(t)}</span>
      {item.fixedPosition === "first" && (
        <span className="text-xs">{t.sidebar.pinnedHint}</span>
      )}
    </li>
  );
}

function GroupList({
  group,
  ids,
  indicatorAtEnd,
  children,
}: {
  group: NavGroup;
  ids: string[];
  indicatorAtEnd: boolean;
  children: React.ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: group });
  return (
    <ul
      ref={setNodeRef}
      data-group={group}
      className={cn(
        "flex min-h-10 flex-col gap-1.5 rounded-md p-1",
        isOver && "bg-accent/60",
        indicatorAtEnd && "shadow-[inset_0_-2px_0_var(--primary)]",
      )}
    >
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        {children}
      </SortableContext>
    </ul>
  );
}

function CustomizeDialogBody() {
  const { t } = useI18n();
  const gate = useNavGateContext();
  const [settings, setSettings] = useLocalSettings();

  const resolved = resolveNavLayout(NAV_ITEMS, settings.navLayout, gate);
  // Disabled entries are still configurable: the user may want to place a
  // feature before it is turned on. Only fixed entries (New chat) are locked.
  const isSortable = (item: NavItemDefinition) => item.configurable;
  const lockedRows = resolved.primary.filter((item) => !isSortable(item));
  const basePrimary = resolved.primary
    .filter(isSortable)
    .map((item) => item.key);
  const baseMore = resolved.more.filter(isSortable).map((item) => item.key);

  // Committed order inside the dialog. It starts from the saved layout and
  // follows it when the gate or another tab changes it, but a local move must
  // render before the settings write comes back.
  const [lists, setLists] = useState({
    primary: basePrimary,
    more: baseMore,
  });
  const listsRef = useRef(lists);
  const dragStartRef = useRef<{
    activeId: string;
    sourceGroup: NavGroup;
  } | null>(null);
  const baseKey = `${basePrimary.join("\u0000")}\u0001${baseMore.join("\u0000")}`;
  const lastBaseKeyRef = useRef(baseKey);
  const applyLists = (next: { primary: string[]; more: string[] }) => {
    listsRef.current = next;
    setLists(next);
  };
  useEffect(() => {
    if (lastBaseKeyRef.current === baseKey) return;
    lastBaseKeyRef.current = baseKey;
    if (dragStartRef.current) return;
    applyLists({ primary: basePrimary, more: baseMore });
  });

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const itemsByKey = new Map(NAV_ITEMS.map((item) => [item.key, item]));

  const save = (primary: string[], more: string[]) => {
    setSettings("navLayout", mergeNavLayout(settings.navLayout, primary, more));
  };

  const move = (key: string, target: NavGroup) => {
    const current = listsRef.current;
    const next = moveNavItem(
      { version: 1, primary: current.primary, more: current.more },
      key,
      target,
    );
    applyLists(next);
    save(next.primary, next.more);
  };

  // A drag never reorders the committed lists; it only moves a drop indicator
  // in the target group. The saved order is the position under that indicator.
  const [dropTarget, setDropTarget] = useState<{
    group: NavGroup;
    index: number;
  } | null>(null);
  const dropTargetRef = useRef<typeof dropTarget>(null);

  const applyDropTarget = (next: typeof dropTarget) => {
    dropTargetRef.current = next;
    setDropTarget(next);
  };

  const targetGroupOf = (over: DragOverEvent["over"]): NavGroup | undefined => {
    if (!over) return undefined;
    const overId = String(over.id);
    if (overId === "primary" || overId === "more") return overId;
    return over.data.current?.group as NavGroup | undefined;
  };

  const clearDrag = () => {
    dragStartRef.current = null;
    applyDropTarget(null);
  };

  const handleDragStart = ({ active }: DragStartEvent) => {
    const activeId = String(active.id);
    const current = listsRef.current;
    const sourceGroup = current.primary.includes(activeId)
      ? "primary"
      : current.more.includes(activeId)
        ? "more"
        : undefined;
    if (!sourceGroup) return;
    dragStartRef.current = { activeId, sourceGroup };
    applyDropTarget(null);
  };

  const handleDragOver = ({ over }: DragOverEvent) => {
    const start = dragStartRef.current;
    if (!start || !over) return;
    const overId = String(over.id);
    const target = targetGroupOf(over);
    // Same-group dragging keeps the native sortable transform; only a
    // cross-group drag needs a drop indicator of its own.
    if (!target || target === start.sourceGroup) {
      applyDropTarget(null);
      return;
    }

    const current = listsRef.current;
    const targetList = target === "primary" ? current.primary : current.more;
    const index =
      overId === target ? targetList.length : targetList.indexOf(overId);
    if (index === -1) return;

    const currentTarget = dropTargetRef.current;
    applyDropTarget(
      currentTarget?.group === target && currentTarget.index === index
        ? currentTarget
        : { group: target, index },
    );
  };

  const handleDragCancel = () => {
    clearDrag();
  };

  const handleDragEnd = ({ over }: DragEndEvent) => {
    const start = dragStartRef.current;
    const target = dropTargetRef.current;
    const current = listsRef.current;
    clearDrag();
    if (!start || !over) return;

    if (target) {
      // The indicator showed this slot, so this is exactly the order to save.
      const next = moveNavItem(
        { version: 1, primary: current.primary, more: current.more },
        start.activeId,
        target.group,
        target.index,
      );
      applyLists(next);
      save(next.primary, next.more);
      return;
    }

    // Same-group: dnd-kit only moved the row visually; apply the final order.
    const overId = String(over.id);
    const overGroup = targetGroupOf(over);
    if (!overGroup || overId === overGroup) return;
    const baseList = overGroup === "primary" ? current.primary : current.more;
    const overIndex = baseList.indexOf(overId);
    if (overIndex === -1) return;
    const next = moveNavItem(
      { version: 1, primary: current.primary, more: current.more },
      start.activeId,
      overGroup,
      overIndex,
    );
    applyLists(next);
    save(next.primary, next.more);
  };

  const primaryIds = lists.primary;
  const moreIds = lists.more;

  const renderRow = (key: string, group: NavGroup, indicator = false) => {
    const item = itemsByKey.get(key);
    if (!item) return null;
    const disabled = item.isDisabled?.(gate) === true;
    return (
      <SortableRow
        key={key}
        item={item}
        group={group}
        disabled={disabled}
        disabledReason={
          item.disabledReason?.(t) ?? t.sidebar.featureDisabledTooltip
        }
        indicator={indicator}
        onMove={() => move(key, group === "primary" ? "more" : "primary")}
      />
    );
  };

  return (
    <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-md">
      <DialogHeader>
        <DialogTitle>{t.sidebar.customize}</DialogTitle>
        <DialogDescription>{t.sidebar.customizeDescription}</DialogDescription>
      </DialogHeader>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnd={handleDragEnd}
        onDragCancel={handleDragCancel}
      >
        <div className="flex flex-col gap-4">
          <section>
            <h3 className="text-muted-foreground mb-2 text-xs font-medium tracking-wide uppercase">
              {t.sidebar.menuGroup}
            </h3>
            <GroupList
              group="primary"
              ids={primaryIds}
              indicatorAtEnd={
                dropTarget?.group === "primary" &&
                dropTarget.index >= primaryIds.length
              }
            >
              {lockedRows.map((item) => (
                <LockedRow key={item.key} item={item} />
              ))}
              {primaryIds.map((key, index) =>
                renderRow(
                  key,
                  "primary",
                  dropTarget?.group === "primary" && dropTarget.index === index,
                ),
              )}
            </GroupList>
          </section>
          <section>
            <h3 className="text-muted-foreground mb-2 text-xs font-medium tracking-wide uppercase">
              {t.sidebar.moreGroup}
            </h3>
            <GroupList
              group="more"
              ids={moreIds}
              indicatorAtEnd={
                dropTarget?.group === "more" &&
                dropTarget.index >= moreIds.length
              }
            >
              {moreIds.map((key, index) =>
                renderRow(
                  key,
                  "more",
                  dropTarget?.group === "more" && dropTarget.index === index,
                ),
              )}
              {moreIds.length === 0 && (
                <li className="text-muted-foreground rounded-md border border-dashed px-3 py-4 text-center text-xs">
                  {t.sidebar.emptyMoreGroup}
                </li>
              )}
            </GroupList>
          </section>
        </div>
      </DndContext>
    </DialogContent>
  );
}

export function NavCustomizeDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open && <CustomizeDialogBody />}
    </Dialog>
  );
}
