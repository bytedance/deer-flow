"use client";

import { useCallback } from "react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Plus, Trash2 } from "lucide-react";

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

import type { Section } from "@/core/report-templates/use-template-dsl";

const COMPONENT_TYPES = [
  "markdown",
  "card",
  "card_group",
  "table",
  "echart",
  "image",
];

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
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;
      const oldIndex = sections.findIndex((s) => s.id === active.id);
      const newIndex = sections.findIndex((s) => s.id === over.id);
      if (oldIndex === -1 || newIndex === -1) return;
      onUpdate(() => arrayMove(sections, oldIndex, newIndex));
    },
    [sections, onUpdate],
  );

  const addSection = useCallback(() => {
    const newId = `section_${Date.now().toString(36)}`;
    onUpdate((prev) => [
      ...prev,
      { id: newId, title: "New Section", component: "markdown" },
    ]);
    onSelect(newId);
  }, [onUpdate, onSelect]);

  const removeSection = useCallback(
    (id: string) => {
      onUpdate((prev) => prev.filter((s) => s.id !== id));
      if (selectedId === id) onSelect(null);
    },
    [onUpdate, selectedId, onSelect],
  );

  const updateSection = useCallback(
    (id: string, updates: Partial<Section>) => {
      onUpdate((prev) =>
        prev.map((s) => (s.id === id ? { ...s, ...updates } : s)),
      );
    },
    [onUpdate],
  );

  if (sections.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <p className="mb-3 text-sm">No sections yet</p>
        <Button variant="outline" size="sm" onClick={addSection}>
          <Plus className="mr-1 h-4 w-4" />
          Add Section
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
        <SortableContext items={sections.map((s) => s.id)} strategy={verticalListSortingStrategy}>
          {sections.map((section) => (
            <SortableSectionCard
              key={section.id}
              section={section}
              isSelected={selectedId === section.id}
              onSelect={() => onSelect(section.id)}
              onRemove={() => removeSection(section.id)}
              onUpdate={(updates) => updateSection(section.id, updates)}
            />
          ))}
        </SortableContext>
      </DndContext>

      <Button variant="outline" size="sm" className="w-full" onClick={addSection}>
        <Plus className="mr-1 h-4 w-4" />
        Add Section
      </Button>
    </div>
  );
}

interface SortableSectionCardProps {
  section: Section;
  isSelected: boolean;
  onSelect: () => void;
  onRemove: () => void;
  onUpdate: (updates: Partial<Section>) => void;
}

function SortableSectionCard({
  section,
  isSelected,
  onSelect,
  onRemove,
  onUpdate,
}: SortableSectionCardProps) {
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
          onChange={(e) => onUpdate({ title: e.target.value })}
          onClick={onSelect}
          className="h-7 flex-1 border-0 p-0 text-sm font-medium shadow-none focus-visible:ring-1"
          placeholder="Section title"
        />

        <Select
          value={section.component}
          onValueChange={(v) => onUpdate({ component: v })}
        >
          <SelectTrigger className="h-7 w-32 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {COMPONENT_TYPES.map((type) => (
              <SelectItem key={type} value={type}>
                {type}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Input
          value={section.source ?? ""}
          onChange={(e) => onUpdate({ source: e.target.value || undefined })}
          onClick={onSelect}
          className="h-7 w-40 text-xs font-mono"
          placeholder="$.data.path"
        />

        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 text-muted-foreground hover:text-destructive"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </CardHeader>
    </Card>
  );
}
