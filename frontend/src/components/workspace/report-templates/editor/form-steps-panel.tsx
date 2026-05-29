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
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/core/i18n/hooks";
import type { FormField, FormStep } from "@/core/report-templates/use-template-dsl";
import { cn } from "@/lib/utils";

const FORM_FIELD_TYPES = new Set([
  "text",
  "select",
  "multi-select",
  "date",
  "device-selector",
  "device-selector-multi",
]);

function createDefaultField(
  type: string,
  labels: {
    selectInput: string;
    multiSelectInput: string;
    deviceSelector: string;
    deviceMultiSelect: string;
    datePicker: string;
    textInput: string;
    optionOne: string;
    optionTwo: string;
  },
): FormField {
  const name = `field_${Date.now().toString(36)}`;

  switch (type) {
    case "select":
      return {
        name,
        type,
        label: labels.selectInput,
        required: false,
        options: [
          { label: labels.optionOne, value: "option_1" },
          { label: labels.optionTwo, value: "option_2" },
        ],
      };
    case "multi-select":
      return {
        name,
        type,
        label: labels.multiSelectInput,
        required: false,
        options: [
          { label: labels.optionOne, value: "option_1" },
          { label: labels.optionTwo, value: "option_2" },
        ],
      };
    case "device-selector":
      return {
        name,
        type,
        label: labels.deviceSelector,
        required: false,
        searchable: true,
      };
    case "device-selector-multi":
      return {
        name,
        type,
        label: labels.deviceMultiSelect,
        required: false,
        searchable: true,
      };
    case "date":
      return { name, type, label: labels.datePicker, required: false };
    default:
      return { name, type, label: labels.textInput, required: false };
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
  const { t } = useI18n();
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const [dragOverStepId, setDragOverStepId] = useState<string | null>(null);
  const [isDragOverCanvas, setIsDragOverCanvas] = useState(false);

  const handleFieldDragOver = useCallback((event: React.DragEvent) => {
    const types = Array.from(event.dataTransfer.types);
    if (types.includes("application/template-component")) {
      event.preventDefault();
    }
  }, []);

  const handleCanvasDrop = useCallback(
    (event: React.DragEvent, targetStepId?: string) => {
      event.preventDefault();
      event.stopPropagation();
      setIsDragOverCanvas(false);
      setDragOverStepId(null);

      const type = event.dataTransfer.getData("application/template-component");
      if (!type || !FORM_FIELD_TYPES.has(type)) return;

      const newField = createDefaultField(type, t.editor);

      if (targetStepId) {
        onUpdate((prev) =>
          prev.map((step) =>
            step.id === targetStepId
              ? { ...step, fields: [...step.fields, newField] }
              : step,
          ),
        );
        onSelect(targetStepId);
        return;
      }

      const newId = `step_${Date.now().toString(36)}`;
      const newStep: FormStep = {
        id: newId,
        title: `${t.editor.stepDefaultTitle} ${(steps.length ?? 0) + 1}`,
        fields: [newField],
      };

      onUpdate((prev) => {
        const updated = [...prev, newStep];
        return updated.map((step, index) => ({
          ...step,
          next: index < updated.length - 1 ? updated[index + 1]!.id : undefined,
        }));
      });
      onSelect(newId);
    },
    [onSelect, onUpdate, steps.length, t.editor],
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const oldIndex = steps.findIndex((step) => step.id === active.id);
      const newIndex = steps.findIndex((step) => step.id === over.id);
      if (oldIndex === -1 || newIndex === -1) return;

      const reordered = arrayMove(steps, oldIndex, newIndex);
      const updated = reordered.map((step, index) => ({
        ...step,
        next: index < reordered.length - 1 ? reordered[index + 1]!.id : undefined,
      }));

      onUpdate(() => updated);
    },
    [onUpdate, steps],
  );

  const addStep = useCallback(() => {
    const newId = `step_${Date.now().toString(36)}`;
    const newStep: FormStep = {
      id: newId,
      title: `${t.editor.stepDefaultTitle} ${(steps.length ?? 0) + 1}`,
      fields: [],
    };

    onUpdate((prev) => {
      const updated = [...prev, newStep];
      return updated.map((step, index) => ({
        ...step,
        next: index < updated.length - 1 ? updated[index + 1]!.id : undefined,
      }));
    });
    onSelect(newId);
  }, [onSelect, onUpdate, steps.length, t.editor.stepDefaultTitle]);

  const removeStep = useCallback(
    (id: string) => {
      onUpdate((prev) => {
        const filtered = prev.filter((step) => step.id !== id);
        return filtered.map((step, index) => ({
          ...step,
          next: index < filtered.length - 1 ? filtered[index + 1]!.id : undefined,
        }));
      });
      if (selectedId === id) onSelect(null);
    },
    [onSelect, onUpdate, selectedId],
  );

  const updateStepTitle = useCallback(
    (id: string, title: string) => {
      onUpdate((prev) =>
        prev.map((step) => (step.id === id ? { ...step, title } : step)),
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
        onDragOver={(event) => {
          handleFieldDragOver(event);
          setIsDragOverCanvas(true);
        }}
        onDragLeave={() => setIsDragOverCanvas(false)}
        onDrop={(event) => handleCanvasDrop(event)}
      >
        <p className="mb-3 text-sm">
          {isDragOverCanvas
            ? t.editor.dropToCreateStep
            : t.editor.noFormSteps}
        </p>
        <Button variant="outline" size="sm" onClick={addStep}>
          <Plus className="mr-1 h-4 w-4" />
          {t.editor.addFirstStep}
        </Button>
      </div>
    );
  }

  return (
    <div
      className="space-y-3"
      onDragOver={(event) => {
        handleFieldDragOver(event);
        setIsDragOverCanvas(true);
      }}
      onDragLeave={() => setIsDragOverCanvas(false)}
      onDrop={(event) => handleCanvasDrop(event)}
    >
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={steps.map((step) => step.id)}
          strategy={verticalListSortingStrategy}
        >
          {steps.map((step, index) => (
            <SortableStepCard
              key={step.id}
              step={step}
              index={index}
              isSelected={selectedId === step.id}
              isDragOver={dragOverStepId === step.id}
              fieldsLabel={t.editor.fields}
              onSelect={() => onSelect(step.id)}
              onRemove={() => removeStep(step.id)}
              onTitleChange={(title) => updateStepTitle(step.id, title)}
              onFieldDragOver={(event) => {
                handleFieldDragOver(event);
                setDragOverStepId(step.id);
              }}
              onFieldDragLeave={() => setDragOverStepId(null)}
              onFieldDrop={(event) => {
                event.stopPropagation();
                handleCanvasDrop(event, step.id);
              }}
            />
          ))}
        </SortableContext>
      </DndContext>

      <Button variant="outline" size="sm" className="w-full" onClick={addStep}>
        <Plus className="mr-1 h-4 w-4" />
        {t.editor.addStep}
      </Button>
    </div>
  );
}

interface SortableStepCardProps {
  step: FormStep;
  index: number;
  isSelected: boolean;
  isDragOver: boolean;
  fieldsLabel: string;
  onSelect: () => void;
  onRemove: () => void;
  onTitleChange: (title: string) => void;
  onFieldDragOver: (event: React.DragEvent) => void;
  onFieldDragLeave: () => void;
  onFieldDrop: (event: React.DragEvent) => void;
}

function SortableStepCard({
  step,
  index,
  isSelected,
  isDragOver,
  fieldsLabel,
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
      onDragOver={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onFieldDragOver(event);
      }}
      onDragLeave={(event) => {
        const relatedTarget = event.relatedTarget as Node | null;
        if (relatedTarget && event.currentTarget.contains(relatedTarget)) return;
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
          onChange={(event) => onTitleChange(event.target.value)}
          onClick={onSelect}
          className="h-7 flex-1 border-0 p-0 text-sm font-medium shadow-none focus-visible:ring-1"
        />
        <span className="text-xs text-muted-foreground">
          {step.fields.length} {fieldsLabel}
        </span>
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
      {isSelected && step.fields.length > 0 && (
        <CardContent className="px-3 pb-3 pt-0">
          <div className="space-y-1">
            {step.fields.map((field) => (
              <div
                key={field.name}
                className="flex items-center gap-2 rounded px-2 py-1 text-xs text-muted-foreground"
              >
                <span className="font-mono">{field.name}</span>
                <span className="text-muted-foreground/50">/</span>
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
