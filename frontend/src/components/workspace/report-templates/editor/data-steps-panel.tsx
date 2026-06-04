"use client";

import { Database, GitBranch, Plus, Trash2 } from "@/components/ui/icons";
import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useI18n } from "@/core/i18n/hooks";
import type { DataStep, Transform } from "@/core/report-templates/use-template-dsl";

interface DataStepsPanelProps {
  dataSteps: DataStep[];
  transforms: Transform[];
  onUpdateDataSteps: (updater: (prev: DataStep[]) => DataStep[]) => void;
  onUpdateTransforms: (updater: (prev: Transform[]) => Transform[]) => void;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

export function DataStepsPanel({
  dataSteps,
  transforms,
  onUpdateDataSteps,
  onUpdateTransforms,
  selectedId,
  onSelect,
}: DataStepsPanelProps) {
  const { t } = useI18n();

  const addDataStep = useCallback(() => {
    const newId = `data_${Date.now().toString(36)}`;
    onUpdateDataSteps((prev) => [...prev, { id: newId, script: "" }]);
    onSelect(newId);
  }, [onSelect, onUpdateDataSteps]);

  const removeDataStep = useCallback(
    (id: string) => {
      onUpdateDataSteps((prev) => prev.filter((step) => step.id !== id));
      if (selectedId === id) onSelect(null);
    },
    [onSelect, onUpdateDataSteps, selectedId],
  );

  const updateDataStep = useCallback(
    (id: string, updates: Partial<DataStep>) => {
      onUpdateDataSteps((prev) =>
        prev.map((step) => (step.id === id ? { ...step, ...updates } : step)),
      );
    },
    [onUpdateDataSteps],
  );

  const addTransform = useCallback(() => {
    const newId = `transform_${Date.now().toString(36)}`;
    onUpdateTransforms((prev) => [...prev, { id: newId, script: "" }]);
    onSelect(newId);
  }, [onSelect, onUpdateTransforms]);

  const removeTransform = useCallback(
    (id: string) => {
      onUpdateTransforms((prev) =>
        prev.filter((transform) => transform.id !== id),
      );
      if (selectedId === id) onSelect(null);
    },
    [onSelect, onUpdateTransforms, selectedId],
  );

  const updateTransform = useCallback(
    (id: string, updates: Partial<Transform>) => {
      onUpdateTransforms((prev) =>
        prev.map((transform) =>
          transform.id === id ? { ...transform, ...updates } : transform,
        ),
      );
    },
    [onUpdateTransforms],
  );

  return (
    <div className="space-y-6">
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Database className="h-4 w-4" />
            {t.editor.dataSteps}
          </h3>
          <Button variant="outline" size="sm" onClick={addDataStep}>
            <Plus className="mr-1 h-3 w-3" />
            {t.editor.addDataStep}
          </Button>
        </div>

        {dataSteps.length === 0 ? (
          <p className="py-4 text-center text-xs text-muted-foreground">
            {t.editor.noDataSteps}
          </p>
        ) : (
          <div className="space-y-2">
            {dataSteps.map((step) => (
              <Card
                key={step.id}
                className={selectedId === step.id ? "border-primary" : ""}
              >
                <CardHeader className="flex flex-row items-center gap-2 p-3 pb-1">
                  <Database className="h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    value={step.id}
                    onChange={(event) => {
                      const oldId = step.id;
                      onUpdateDataSteps((prev) =>
                        prev.map((item) =>
                          item.id === oldId
                            ? { ...item, id: event.target.value }
                            : item,
                        ),
                      );
                    }}
                    className="h-6 flex-1 border-0 p-0 text-sm font-mono shadow-none"
                    placeholder="step_id"
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 text-muted-foreground hover:text-destructive"
                    onClick={() => removeDataStep(step.id)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </CardHeader>
                <CardContent className="space-y-2 p-3 pt-1">
                  <div>
                    <Label className="text-xs">{t.editor.script}</Label>
                    <Input
                      value={step.script}
                      onChange={(event) =>
                        updateDataStep(step.id, { script: event.target.value })
                      }
                      className="h-7 text-xs font-mono"
                      placeholder={t.editor.scriptPlaceholder}
                    />
                  </div>
                  <div>
                    <Label className="text-xs">{t.editor.argsJson}</Label>
                    <Input
                      value={step.args ? JSON.stringify(step.args) : ""}
                      onChange={(event) => {
                        try {
                          const args = event.target.value
                            ? JSON.parse(event.target.value)
                            : undefined;
                          updateDataStep(step.id, { args });
                        } catch {
                          // Ignore invalid JSON while typing.
                        }
                      }}
                      className="h-7 text-xs font-mono"
                      placeholder={t.editor.argsPlaceholder}
                    />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      <div>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <GitBranch className="h-4 w-4" />
            {t.editor.transforms}
          </h3>
          <Button variant="outline" size="sm" onClick={addTransform}>
            <Plus className="mr-1 h-3 w-3" />
            {t.editor.addTransform}
          </Button>
        </div>

        {transforms.length === 0 ? (
          <p className="py-4 text-center text-xs text-muted-foreground">
            {t.editor.noTransforms}
          </p>
        ) : (
          <div className="space-y-2">
            {transforms.map((transform) => (
              <Card
                key={transform.id}
                className={selectedId === transform.id ? "border-primary" : ""}
              >
                <CardHeader className="flex flex-row items-center gap-2 p-3 pb-1">
                  <GitBranch className="h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    value={transform.id}
                    onChange={(event) => {
                      const oldId = transform.id;
                      onUpdateTransforms((prev) =>
                        prev.map((item) =>
                          item.id === oldId
                            ? { ...item, id: event.target.value }
                            : item,
                        ),
                      );
                    }}
                    className="h-6 flex-1 border-0 p-0 text-sm font-mono shadow-none"
                    placeholder="transform_id"
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 text-muted-foreground hover:text-destructive"
                    onClick={() => removeTransform(transform.id)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </CardHeader>
                <CardContent className="space-y-2 p-3 pt-1">
                  <div>
                    <Label className="text-xs">{t.editor.script}</Label>
                    <Input
                      value={transform.script}
                      onChange={(event) =>
                        updateTransform(transform.id, {
                          script: event.target.value,
                        })
                      }
                      className="h-7 text-xs font-mono"
                      placeholder={t.editor.transformScriptPlaceholder}
                    />
                  </div>
                  <div>
                    <Label className="text-xs">{t.editor.inputSource}</Label>
                    <Input
                      value={transform.input ?? ""}
                      onChange={(event) =>
                        updateTransform(transform.id, {
                          input: event.target.value || undefined,
                        })
                      }
                      className="h-7 text-xs font-mono"
                      placeholder={t.editor.transformInputPlaceholder}
                    />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
