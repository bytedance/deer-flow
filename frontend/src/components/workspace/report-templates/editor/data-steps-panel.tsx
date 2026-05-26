"use client";

import { useCallback } from "react";
import { Plus, Trash2, Database, GitBranch } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

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
  const addDataStep = useCallback(() => {
    const newId = `data_${Date.now().toString(36)}`;
    onUpdateDataSteps((prev) => [
      ...prev,
      { id: newId, script: "" },
    ]);
    onSelect(newId);
  }, [onUpdateDataSteps, onSelect]);

  const removeDataStep = useCallback(
    (id: string) => {
      onUpdateDataSteps((prev) => prev.filter((s) => s.id !== id));
      if (selectedId === id) onSelect(null);
    },
    [onUpdateDataSteps, selectedId, onSelect],
  );

  const updateDataStep = useCallback(
    (id: string, updates: Partial<DataStep>) => {
      onUpdateDataSteps((prev) =>
        prev.map((s) => (s.id === id ? { ...s, ...updates } : s)),
      );
    },
    [onUpdateDataSteps],
  );

  const addTransform = useCallback(() => {
    const newId = `transform_${Date.now().toString(36)}`;
    onUpdateTransforms((prev) => [
      ...prev,
      { id: newId, script: "" },
    ]);
    onSelect(newId);
  }, [onUpdateTransforms, onSelect]);

  const removeTransform = useCallback(
    (id: string) => {
      onUpdateTransforms((prev) => prev.filter((t) => t.id !== id));
      if (selectedId === id) onSelect(null);
    },
    [onUpdateTransforms, selectedId, onSelect],
  );

  const updateTransform = useCallback(
    (id: string, updates: Partial<Transform>) => {
      onUpdateTransforms((prev) =>
        prev.map((t) => (t.id === id ? { ...t, ...updates } : t)),
      );
    },
    [onUpdateTransforms],
  );

  return (
    <div className="space-y-6">
      {/* Data Steps */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Database className="h-4 w-4" />
            Data Steps
          </h3>
          <Button variant="outline" size="sm" onClick={addDataStep}>
            <Plus className="mr-1 h-3 w-3" />
            Add
          </Button>
        </div>

        {dataSteps.length === 0 ? (
          <p className="py-4 text-center text-xs text-muted-foreground">
            No data steps. Add scripts that fetch data.
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
                    onChange={(e) => {
                      const oldId = step.id;
                      onUpdateDataSteps((prev) =>
                        prev.map((s) =>
                          s.id === oldId ? { ...s, id: e.target.value } : s,
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
                    <Label className="text-xs">Script</Label>
                    <Input
                      value={step.script}
                      onChange={(e) =>
                        updateDataStep(step.id, { script: e.target.value })
                      }
                      className="h-7 text-xs font-mono"
                      placeholder="skill_name/script_name"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">Args (JSON)</Label>
                    <Input
                      value={step.args ? JSON.stringify(step.args) : ""}
                      onChange={(e) => {
                        try {
                          const args = e.target.value
                            ? JSON.parse(e.target.value)
                            : undefined;
                          updateDataStep(step.id, { args });
                        } catch {
                          // ignore invalid JSON while typing
                        }
                      }}
                      className="h-7 text-xs font-mono"
                      placeholder='{"key": "value"}'
                    />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* Transforms */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <GitBranch className="h-4 w-4" />
            Transforms
          </h3>
          <Button variant="outline" size="sm" onClick={addTransform}>
            <Plus className="mr-1 h-3 w-3" />
            Add
          </Button>
        </div>

        {transforms.length === 0 ? (
          <p className="py-4 text-center text-xs text-muted-foreground">
            No transforms. Add data transformation steps.
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
                    onChange={(e) => {
                      const oldId = transform.id;
                      onUpdateTransforms((prev) =>
                        prev.map((t) =>
                          t.id === oldId ? { ...t, id: e.target.value } : t,
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
                    <Label className="text-xs">Script</Label>
                    <Input
                      value={transform.script}
                      onChange={(e) =>
                        updateTransform(transform.id, { script: e.target.value })
                      }
                      className="h-7 text-xs font-mono"
                      placeholder="skill_name/transform_name"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">Input Source</Label>
                    <Input
                      value={transform.input ?? ""}
                      onChange={(e) =>
                        updateTransform(transform.id, {
                          input: e.target.value || undefined,
                        })
                      }
                      className="h-7 text-xs font-mono"
                      placeholder="$.data.step_id"
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
