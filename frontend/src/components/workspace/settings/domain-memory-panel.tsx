"use client";

import { DownloadIcon, PlusIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  useCreateDomainFact,
  useDomainMemory,
  useExportDomainMemory,
} from "@/core/memory/hooks";
import type { DomainFactCreateInput } from "@/core/memory/types";
import { useMemoryEventSubscription } from "@/core/memory/use-memory-events";
import { truncateFactPreview } from "@/core/memory/utils";
import { formatTimeAgo } from "@/core/utils/datetime";

export function DomainMemoryPanel() {
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [domainFilter, setDomainFilter] = useState("");
  const [entityFilter, setEntityFilter] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  useMemoryEventSubscription();
  const [createForm, setCreateForm] = useState<DomainFactCreateInput>({
    content: "",
    domain: "",
    entity_id: "",
    confidence: 0.9,
  });

  const { domainFacts, isLoading, error } = useDomainMemory(
    activeQuery,
    {
      domain: domainFilter || undefined,
      entityId: entityFilter || undefined,
    },
  );
  const createMutation = useCreateDomainFact();
  const exportMutation = useExportDomainMemory();

  function handleSearch() {
    const trimmed = query.trim();
    if (!trimmed) {
      toast.error("Enter a search query");
      return;
    }
    setActiveQuery(trimmed);
  }

  async function handleExport() {
    try {
      const data = await exportMutation.mutateAsync({
        domain: domainFilter || undefined,
        entityId: entityFilter || undefined,
      });
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `domain-memory-${Date.now()}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast.success(`Exported ${data.length} domain fact(s)`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleCreate() {
    if (!createForm.content.trim() || !createForm.domain.trim() || !createForm.entity_id.trim()) {
      toast.error("Content, domain, and entity are required");
      return;
    }
    try {
      await createMutation.mutateAsync(createForm);
      toast.success("Domain fact created");
      setCreateOpen(false);
      setCreateForm({ content: "", domain: "", entity_id: "", confidence: 0.9 });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search domain facts..."
          className="sm:max-w-xs"
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSearch();
          }}
        />
        <Input
          value={domainFilter}
          onChange={(e) => setDomainFilter(e.target.value)}
          placeholder="Domain filter"
          className="sm:max-w-[140px]"
        />
        <Input
          value={entityFilter}
          onChange={(e) => setEntityFilter(e.target.value)}
          placeholder="Entity filter"
          className="sm:max-w-[140px]"
        />
        <Button variant="outline" onClick={handleSearch}>
          Search
        </Button>
      </div>

      <div className="flex gap-2">
        <Button variant="outline" onClick={() => setCreateOpen(true)}>
          <PlusIcon className="mr-2 h-4 w-4" />
          Create Fact
        </Button>
        <Button
          variant="outline"
          onClick={() => void handleExport()}
          disabled={exportMutation.isPending}
        >
          <DownloadIcon className="mr-2 h-4 w-4" />
          Export
        </Button>
      </div>

      {!activeQuery ? (
        <div className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
          Enter a search query to find domain facts.
        </div>
      ) : isLoading ? (
        <div className="text-muted-foreground text-sm">Searching...</div>
      ) : error ? (
        <div className="text-destructive text-sm">Error: {error.message}</div>
      ) : domainFacts.length === 0 ? (
        <div className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
          No domain facts match &quot;{activeQuery}&quot;.
        </div>
      ) : (
        <div className="space-y-3">
          <div className="text-muted-foreground text-sm">
            {domainFacts.length} result(s)
          </div>
          {domainFacts.map((fact) => (
            <div
              key={fact.id}
              className="flex flex-col gap-2 rounded-md border p-3"
            >
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                <Badge variant="secondary">{fact.domain}</Badge>
                <span className="text-muted-foreground">{fact.entity_id}</span>
                <span>
                  <span className="text-muted-foreground">Confidence:</span>{" "}
                  {fact.confidence.toFixed(2)}
                </span>
                {fact.created_at && (
                  <span>
                    <span className="text-muted-foreground">Created:</span>{" "}
                    {formatTimeAgo(fact.created_at)}
                  </span>
                )}
              </div>
              <p className="text-sm [overflow-wrap:anywhere]">
                {truncateFactPreview(fact.content)}
              </p>
              <div className="text-muted-foreground text-xs">
                Score: {fact.similarity_score.toFixed(2)} → Adjusted:{" "}
                {fact.adjusted_score.toFixed(2)}
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Domain Fact</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Content</label>
              <Textarea
                value={createForm.content}
                onChange={(e) =>
                  setCreateForm((prev) => ({ ...prev, content: e.target.value }))
                }
                placeholder="Fact content"
                rows={3}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium">Domain</label>
                <Input
                  value={createForm.domain}
                  onChange={(e) =>
                    setCreateForm((prev) => ({ ...prev, domain: e.target.value }))
                  }
                  placeholder="e.g., equipment"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Entity ID</label>
                <Input
                  value={createForm.entity_id}
                  onChange={(e) =>
                    setCreateForm((prev) => ({
                      ...prev,
                      entity_id: e.target.value,
                    }))
                  }
                  placeholder="e.g., pump_a"
                />
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Confidence</label>
              <Input
                type="number"
                min="0"
                max="1"
                step="0.01"
                value={createForm.confidence}
                onChange={(e) =>
                  setCreateForm((prev) => ({
                    ...prev,
                    confidence: Number(e.target.value),
                  }))
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => void handleCreate()}
              disabled={createMutation.isPending}
            >
              {createMutation.isPending ? "Creating..." : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
