"use client";

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
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { FormStep, FormField } from "@/core/report-templates/use-template-dsl";
import { cn } from "@/lib/utils";

const FORM_FIELD_TYPES = new Set([
  "text",
  "select",
  "multi-select",
  "date",
  "device-selector",
]);

function createDefaultField(type: string): FormField {
  const name = `field_${Date.now().toString(36)}`;
  switch (type) {
    case "select":
      return {
        name,
        type,
        label: "Select",
        required: false,
        options: [
          { label: "Option 1", value: "option_1" },
          { label: "Option 2", value: "option_2" },
        ],
      };
    case "multi-select":
      return {
        name,
        type,
        label: "Multi-Select",
        required: false,
        options: [
          { label: "Option 1", value: "option_1" },
          { label: "Option 2", value: "option_2" },
        ],
      };
    case "device-selector":
      return {
        name,
        type,
        label: "Device Selector",
        required: false,
        searchable: true,
      };
    case "date":
      return { name, type, label: "Date", required: false };
    default:
      return { name, type, label: "Text Input", required: false };
  }
}

interface FormStepsPanelProps {
  steps: FormStep[];
  onUpdate: (updater: (prev: FormStep[]) => FormStep[]) => void;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

export function FormStepsPanel({
  steps,
  onUpdate,
  selectedId,
  onSelect,
}: FormStepsPanelProps) {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const [dragOverStepId, setDragOverStepId] = useState<string | null>(null);
  const [isDragOverCanvas, setIsDragOverCanvas] = useState(false);

  const handleFieldDragOver = useCallback((e: React.DragEvent) => {
    const types = Array.from(e.dataTransfer.types);
    if (types.includes("application/template-component")) {
      e.preventDefault();
    }
  }, []);

  const handleCanvasDrop = useCallback(
    (e: React.DragEvent, targetStepId?: string) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOverCanvas(false);
      setDragOverStepId(null);
      const type = e.dataTransfer.getData("application/template-component");
      if (!type || !FORM_FIELD_TYPES.has(type)) return;

      const newField = createDefaultField(type);

      if (targetStepId) {
        onUpdate((prev) =>
          prev.map((s) =>
            s.id === targetStepId
              ? { ...s, fields: [...s.fields, newField] }
              : s,
          ),
        );
        onSelect(targetStepId);
      } else {
        const newId = `step_${Date.now().toString(36)}`;
        const newStep: FormStep = {
          id: newId,
          title: `Step ${(steps.length ?? 0) + 1}`,
          fields: [newField],
        };
        onUpdate((prev) => {
          const updated = [...prev, newStep];
          return updated.map((s, i) => ({
            ...s,
            next: i < updated.length - 1 ? updated[i + 1]!.id : undefined,
          }));
        });
        onSelect(newId);
      }
    },
    [steps.length, onUpdate, onSelect],
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const oldIndex = steps.findIndex((s) => s.id === active.id);
      const newIndex = steps.findIndex((s) => s.id === over.id);
      if (oldIndex === -1 || newIndex === -1) return;

      const reordered = arrayMove(steps, oldIndex, newIndex);
      // Auto-update next chain
      const updated = reordered.map((step, i) => ({
        ...step,
        next: i < reordered.length - 1 ? reordered[i + 1]!.id : undefined,
      }));
      onUpdate(() => updated);
    },
    [steps, onUpdate],
  );

  const addStep = useCallback(() => {
    const newId = `step_${Date.now().toString(36)}`;
    const newStep: FormStep = {
      id: newId,
      title: `Step ${(steps.length ?? 0) + 1}`,
      fields: [],
    };
    onUpdate((prev) => {
      const updated = [...prev, newStep];
      // Update next chain
      return updated.map((s, i) => ({
        ...s,
        next: i < updated.length - 1 ? updated[i + 1]!.id : undefined,
      }));
    });
    onSelect(newId);
  }, [steps.length, onUpdate, onSelect]);

  const removeStep = useCallback(
    (id: string) => {
      onUpdate((prev) => {
        const filtered = prev.filter((s) => s.id !== id);
        return filtered.map((s, i) => ({
          ...s,
          next: i < filtered.length - 1 ? filtered[i + 1]!.id : undefined,
        }));
      });
      if (selectedId === id) onSelect(null);
    },
    [onUpdate, selectedId, onSelect],
  );

  const updateStepTitle = useCallback(
    (id: string, title: string) => {
      onUpdate((prev) =>
        prev.map((s) => (s.id === id ? { ...s, title } : s)),
      );
    },
    [onUpdate],
  );

  if (steps.length === 0) {
    return (
      <div
        className={cn(
          "flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-12 text-muted-foreground transition-colors",
          isDragOverCanvas
            ? "border-primary bg-primary/5"
            : "border-transparent",
        )}
        onDragOver={(e) => {
          handleFieldDragOver(e);
          setIsDragOverCanvas(true);
        }}
        onDragLeave={() => setIsDragOverCanvas(false)}
        onDrop={(e) => handleCanvasDrop(e)}
      >
        <p className="mb-3 text-sm">
          {isDragOverCanvas
            ? "Drop to create a new step"
            : "No form steps yet"}
        </p>
        <Button variant="outline" size="sm" onClick={addStep}>
          <Plus className="mr-1 h-4 w-4" />
          Add First Step
        </Button>
      </div>
    );
  }

  return (
    <div
      className="space-y-3"
      onDragOver={(e) => {
        handleFieldDragOver(e);
        setIsDragOverCanvas(true);
      }}
      onDragLeave={() => setIsDragOverCanvas(false)}
      onDrop={(e) => handleCanvasDrop(e)}
    >
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext items={steps.map((s) => s.id)} strategy={verticalListSortingStrategy}>
          {steps.map((step, index) => (
            <SortableStepCard
              key={step.id}
              step={step}
              index={index}
              isSelected={selectedId === step.id}
              isDragOver={dragOverStepId === step.id}
              onSelect={() => onSelect(step.id)}
              onRemove={() => removeStep(step.id)}
              onTitleChange={(title) => updateStepTitle(step.id, title)}
              onFieldDragOver={(e) => {
                handleFieldDragOver(e);
                setDragOverStepId(step.id);
              }}
              onFieldDragLeave={() => setDragOverStepId(null)}
              onFieldDrop={(e) => {
                e.stopPropagation();
                handleCanvasDrop(e, step.id);
              }}
            />
          ))}
        </SortableContext>
      </DndContext>

      <Button variant="outline" size="sm" className="w-full" onClick={addStep}>
        <Plus className="mr-1 h-4 w-4" />
        Add Step
      </Button>
    </div>
  );
}

interface SortableStepCardProps {
  step: FormStep;
  index: number;
  isSelected: boolean;
  isDragOver: boolean;
  onSelect: () => void;
  onRemove: () => void;
  onTitleChange: (title: string) => void;
  onFieldDragOver: (e: React.DragEvent) => void;
  onFieldDragLeave: () => void;
  onFieldDrop: (e: React.DragEvent) => void;
}

function SortableStepCard({
  step,
  index,
  isSelected,
  isDragOver,
  onSelect,
  onRemove,
  onTitleChange,
  onFieldDragOver,
  onFieldDragLeave,
  onFieldDrop,
}: SortableStepCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: step.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <Card
      ref={setNodeRef}
      style={style}
      className={cn(
        isSelected && "border-primary",
        isDragOver && "border-primary/50 ring-2 ring-primary/20",
      )}
      onDragOver={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onFieldDragOver(e);
      }}
      onDragLeave={(e) => {
        const relatedTarget = e.relatedTarget as Node | null;
        if (relatedTarget && e.currentTarget.contains(relatedTarget)) return;
        onFieldDragLeave();
      }}
      onDrop={onFieldDrop}
    >
      <CardHeader className="flex flex-row items-center gap-2 p-3">
        <div
          {...attributes}
          {...listeners}
          className="cursor-grab touch-none text-muted-foreground hover:text-foreground"
        >
          <GripVertical className="h-4 w-4" />
        </div>
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-xs font-medium">
          {index + 1}
        </span>
        <Input
          value={step.title}
          onChange={(e) => onTitleChange(e.target.value)}
          onClick={onSelect}
          className="h-7 flex-1 border-0 p-0 text-sm font-medium shadow-none focus-visible:ring-1"
        />
        <span className="text-xs text-muted-foreground">
          {step.fields.length} field{step.fields.length !== 1 ? "s" : ""}
        </span>
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
      {isSelected && step.fields.length > 0 && (
        <CardContent className="px-3 pb-3 pt-0">
          <div className="space-y-1">
            {step.fields.map((field) => (
              <div
                key={field.name}
                className="flex items-center gap-2 rounded px-2 py-1 text-xs text-muted-foreground"
              >
                <span className="font-mono">{field.name}</span>
                <span className="text-muted-foreground/50">·</span>
                <span>{field.label || field.name}</span>
                <span className="ml-auto text-[10px]">{field.type}</span>
              </div>
            ))}
          </div>
        </CardContent>
      )}
    </Card>
  );
}
