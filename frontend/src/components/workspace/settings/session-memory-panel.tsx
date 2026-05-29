"use client";

import { DownloadIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/core/i18n/hooks";
import { useExportSessionMemory, useSessionMemory } from "@/core/memory/hooks";
import { useMemoryEventSubscription } from "@/core/memory/use-memory-events";
import { truncateFactPreview } from "@/core/memory/utils";
import { formatTimeAgo } from "@/core/utils/datetime";

interface SessionMemoryPanelProps {
  initialThreadId?: string;
}

export function SessionMemoryPanel({ initialThreadId }: SessionMemoryPanelProps) {
  const { t } = useI18n();
  const s = t.settings.memory.session;

  const [threadId, setThreadId] = useState(initialThreadId ?? "");
  const [activeThreadId, setActiveThreadId] = useState<string | null>(
    initialThreadId ?? null,
  );

  useEffect(() => {
    if (initialThreadId) {
      setThreadId(initialThreadId);
      setActiveThreadId(initialThreadId);
    }
  }, [initialThreadId]);

  useMemoryEventSubscription();
  const { sessionMemory, isLoading, error } = useSessionMemory(activeThreadId);
  const exportMutation = useExportSessionMemory();

  function handleLoad() {
    const trimmed = threadId.trim();
    if (!trimmed) {
      toast.error(s.loadRequired);
      return;
    }
    setActiveThreadId(trimmed);
  }

  async function handleExport() {
    if (!activeThreadId) return;
    try {
      const data = await exportMutation.mutateAsync(activeThreadId);
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `session-memory-${activeThreadId}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast.success(s.exportSuccess);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <Input
          value={threadId}
          onChange={(e) => setThreadId(e.target.value)}
          placeholder={s.threadIdPlaceholder}
          className="max-w-sm"
          onKeyDown={(e) => {
            if (e.key === "Enter") handleLoad();
          }}
        />
        <Button variant="outline" onClick={handleLoad}>
          {s.loadButton}
        </Button>
        {activeThreadId && (
          <Button
            variant="outline"
            onClick={() => void handleExport()}
            disabled={exportMutation.isPending}
          >
            <DownloadIcon className="mr-2 h-4 w-4" />
            {s.exportButton}
          </Button>
        )}
      </div>

      {!activeThreadId ? (
        <div className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
          {s.emptyState}
        </div>
      ) : isLoading ? (
        <div className="text-muted-foreground text-sm">{s.loading}</div>
      ) : error ? (
        <div className="text-destructive text-sm">
          {t.settings.memory.errorPrefix}: {error.message}
        </div>
      ) : !sessionMemory || sessionMemory.facts.length === 0 ? (
        <div className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
          {s.noFacts.replace("{threadId}", activeThreadId)}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="text-muted-foreground text-sm">
            {s.factCount.replace("{count}", String(sessionMemory.facts.length))}{" "}
            <Badge variant="secondary">{activeThreadId}</Badge>
          </div>
          {sessionMemory.facts.map((fact) => (
            <div
              key={fact.id}
              className="flex flex-col gap-2 rounded-md border p-3"
            >
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                <span>
                  <span className="text-muted-foreground">
                    {s.categoryLabel}:
                  </span>{" "}
                  {fact.category}
                </span>
                <span>
                  <span className="text-muted-foreground">
                    {s.confidenceLabel}:
                  </span>{" "}
                  {fact.confidence.toFixed(2)}
                </span>
                {fact.created_at && (
                  <span>
                    <span className="text-muted-foreground">
                      {s.createdLabel}:
                    </span>{" "}
                    {formatTimeAgo(fact.created_at)}
                  </span>
                )}
              </div>
              <p className="text-sm [overflow-wrap:anywhere]">
                {truncateFactPreview(fact.content)}
              </p>
              {fact.source_error && (
                <div className="text-muted-foreground text-xs">
                  {s.correctionLabel}: {fact.source_error}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
