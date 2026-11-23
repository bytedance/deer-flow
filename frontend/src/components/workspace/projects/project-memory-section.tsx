"use client";

import { Brain, FileText, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import { type Project } from "@/core/projects";
import {
  useProjectMemory,
  useProjectMemoryAction,
} from "@/core/projects/memory";

export function ProjectMemorySection({
  project,
  hasUnsavedInstructions,
  maxBytes,
}: {
  project: Project;
  hasUnsavedInstructions: boolean;
  maxBytes: number;
}) {
  const { t } = useI18n();
  const query = useProjectMemory(project.id);
  const action = useProjectMemoryAction(project.id);
  const memory = query.data;
  const readOnly = project.status === "archived";
  const onError = () => toast.error(t.projects.memoryActionFailed);

  return (
    <section
      className="mt-8 flex flex-col gap-4 border-t pt-6"
      aria-label={t.projects.memoryTitle}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-medium">
          <Brain className="size-4" />
          {t.projects.memoryTitle}
          {memory && (
            <span className="text-muted-foreground font-normal">
              {memory.facts.length} / {memory.max_facts}
            </span>
          )}
        </h2>
        {memory && (
          <label className="flex items-center gap-2 text-xs">
            {t.projects.memoryAutoExtract}
            <Switch
              checked={memory.enabled}
              disabled={readOnly || action.isPending}
              aria-label={t.projects.memoryAutoExtract}
              onCheckedChange={(enabled) =>
                action.mutate({ kind: "toggle", enabled }, { onError })
              }
            />
          </label>
        )}
      </div>
      <p className="text-muted-foreground text-xs leading-relaxed">
        {t.projects.memoryDescription}
      </p>
      {query.isError ? (
        <div role="alert" className="text-sm">
          {t.projects.memoryLoadFailed}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void query.refetch()}
          >
            {t.trash.retry}
          </Button>
        </div>
      ) : !memory ? (
        <p className="text-muted-foreground text-sm">{t.common.loading}</p>
      ) : memory.facts.length === 0 ? (
        <div className="text-muted-foreground rounded-lg border border-dashed p-6 text-center text-sm">
          {t.projects.memoryEmpty}
        </div>
      ) : (
        <ul className="divide-y rounded-lg border">
          {memory.facts.map((fact) => {
            const tooLong =
              new TextEncoder().encode(
                [project.instructions.trimEnd(), `- ${fact.content}`]
                  .filter(Boolean)
                  .join("\n"),
              ).length > maxBytes;
            const blocked =
              hasUnsavedInstructions || tooLong || readOnly || action.isPending;
            return (
              <li
                key={fact.id}
                className="flex flex-wrap items-start gap-3 p-4"
              >
                <p className="min-w-40 flex-1 text-sm leading-relaxed break-words">
                  {fact.content}
                </p>
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={blocked}
                    title={
                      hasUnsavedInstructions
                        ? t.projects.memorySaveFirst
                        : tooLong
                          ? t.projects.instructionsTooLong(maxBytes)
                          : undefined
                    }
                    onClick={() =>
                      action.mutate(
                        {
                          kind: "promote",
                          factId: fact.id,
                          instructions: project.instructions,
                        },
                        {
                          onError,
                          onSuccess: () =>
                            toast.success(t.projects.memoryPromoted),
                        },
                      )
                    }
                  >
                    <FileText className="size-3.5" />
                    {t.projects.memoryPromote}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    disabled={action.isPending}
                    aria-label={`${t.common.delete}: ${fact.content}`}
                    onClick={() =>
                      action.mutate(
                        { kind: "delete", factId: fact.id },
                        { onError },
                      )
                    }
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {hasUnsavedInstructions && (
        <p className="text-muted-foreground text-xs">
          {t.projects.memorySaveFirst}
        </p>
      )}
    </section>
  );
}
