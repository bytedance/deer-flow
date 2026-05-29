"use client";

import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Plus, Trash2 } from "lucide-react";
import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useI18n } from "@/core/i18n/hooks";
import type { Section } from "@/core/report-templates/use-template-dsl";

const COMPONENT_TYPES = [
  "markdown",
  "card",
  "card_group",
  "table",
  "echart",
  "image",
] as const;

interface SectionsPanelProps {
  sections: Section[];
  onUpdate: (updater: (prev: Section[]) => Section[]) => void;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  availableSources: string[];
}

export function SectionsPanel({
  sections,
  onUpdate,
  selectedId,
  onSelect,
}: SectionsPanelProps) {
  const { t } = useI18n();
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const componentLabels: Record<(typeof COMPONENT_TYPES)[number], string> = {
    markdown: t.editor.markdown,
    card: t.editor.card,
    card_group: t.editor.cardGroup,
    table: t.editor.table,
    echart: t.editor.chart,
    image: t.editor.image,
  };

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const oldIndex = sections.findIndex((section) => section.id === active.id);
      const newIndex = sections.findIndex((section) => section.id === over.id);
      if (oldIndex === -1 || newIndex === -1) return;

      onUpdate(() => arrayMove(sections, oldIndex, newIndex));
    },
    [onUpdate, sections],
  );

  const addSection = useCallback(() => {
    const newId = `section_${Date.now().toString(36)}`;
    onUpdate((prev) => [
      ...prev,
      {
        id: newId,
        title: t.editor.newSection,
        component: "markdown",
      },
    ]);
    onSelect(newId);
  }, [onSelect, onUpdate, t.editor.newSection]);

  const removeSection = useCallback(
    (id: string) => {
      onUpdate((prev) => prev.filter((section) => section.id !== id));
      if (selectedId === id) onSelect(null);
    },
    [onSelect, onUpdate, selectedId],
  );

  const updateSection = useCallback(
    (id: string, updates: Partial<Section>) => {
      onUpdate((prev) =>
        prev.map((section) =>
          section.id === id ? { ...section, ...updates } : section,
        ),
      );
    },
    [onUpdate],
  );

  if (sections.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <p className="mb-3 text-sm">{t.editor.noSections}</p>
        <Button variant="outline" size="sm" onClick={addSection}>
          <Plus className="mr-1 h-4 w-4" />
          {t.editor.addSection}
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={sections.map((section) => section.id)}
          strategy={verticalListSortingStrategy}
        >
          {sections.map((section) => (
            <SortableSectionCard
              key={section.id}
              section={section}
              isSelected={selectedId === section.id}
              componentLabels={componentLabels}
              onSelect={() => onSelect(section.id)}
              onRemove={() => removeSection(section.id)}
              onUpdate={(updates) => updateSection(section.id, updates)}
            />
          ))}
        </SortableContext>
      </DndContext>

      <Button
        variant="outline"
        size="sm"
        className="w-full"
        onClick={addSection}
      >
        <Plus className="mr-1 h-4 w-4" />
        {t.editor.addSection}
      </Button>
    </div>
  );
}

interface SortableSectionCardProps {
  section: Section;
  isSelected: boolean;
  componentLabels: Record<(typeof COMPONENT_TYPES)[number], string>;
  onSelect: () => void;
  onRemove: () => void;
  onUpdate: (updates: Partial<Section>) => void;
}

function SortableSectionCard({
  section,
  isSelected,
  componentLabels,
  onSelect,
  onRemove,
  onUpdate,
}: SortableSectionCardProps) {
  const { t } = useI18n();
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: section.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <Card
      ref={setNodeRef}
      style={style}
      className={isSelected ? "border-primary" : ""}
    >
      <CardHeader className="flex flex-row items-center gap-2 p-3">
        <div
          {...attributes}
          {...listeners}
          className="cursor-grab touch-none text-muted-foreground hover:text-foreground"
        >
          <GripVertical className="h-4 w-4" />
        </div>

        <Input
          value={section.title}
          onChange={(event) => onUpdate({ title: event.target.value })}
          onClick={onSelect}
          className="h-7 flex-1 border-0 p-0 text-sm font-medium shadow-none focus-visible:ring-1"
          placeholder={t.editor.sectionTitlePlaceholder}
        />

        <Select
          value={section.component}
          onValueChange={(value) => onUpdate({ component: value })}
        >
          <SelectTrigger className="h-7 w-32 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {COMPONENT_TYPES.map((type) => (
              <SelectItem key={type} value={type}>
                {componentLabels[type]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Input
          value={section.source ?? ""}
          onChange={(event) =>
            onUpdate({ source: event.target.value || undefined })
          }
          onClick={onSelect}
          className="h-7 w-40 text-xs font-mono"
          placeholder={t.editor.sectionSourcePlaceholder}
        />

        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 text-muted-foreground hover:text-destructive"
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </CardHeader>
    </Card>
  );
}
