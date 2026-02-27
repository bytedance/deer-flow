"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCreateAgent, useUpdateAgent } from "@/core/agents";
import type { Agent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { cn } from "@/lib/utils";

const AGENT_NAME_RE = /^[a-z0-9-]+$/;
const MODEL_INHERITED = "__inherited__";

interface AgentFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When provided, dialog is in edit mode */
  agent?: Agent | null;
}

export function AgentFormDialog({
  open,
  onOpenChange,
  agent,
}: AgentFormDialogProps) {
  const { t } = useI18n();
  const isEdit = !!agent;

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [model, setModel] = useState<string>(MODEL_INHERITED);
  const [toolGroupsRaw, setToolGroupsRaw] = useState("");
  const [soul, setSoul] = useState("");
  const [nameError, setNameError] = useState("");

  const { models } = useModels();
  const createAgent = useCreateAgent();
  const updateAgent = useUpdateAgent();

  const isPending = createAgent.isPending || updateAgent.isPending;

  // Populate form when editing
  useEffect(() => {
    if (agent) {
      setName(agent.name);
      setDescription(agent.description ?? "");
      setModel(agent.model ?? MODEL_INHERITED);
      setToolGroupsRaw(agent.tool_groups?.join(", ") ?? "");
      setSoul(agent.soul ?? "");
    } else {
      setName("");
      setDescription("");
      setModel(MODEL_INHERITED);
      setToolGroupsRaw("");
      setSoul("");
    }
    setNameError("");
  }, [agent, open]);

  function parseToolGroups(raw: string): string[] | null {
    const trimmed = raw.trim();
    if (!trimmed) return null;
    return trimmed
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function validateName(value: string): string {
    if (!value) return t.agents.name + " is required";
    if (!AGENT_NAME_RE.test(value)) return t.agents.nameHint;
    return "";
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    if (!isEdit) {
      const err = validateName(name);
      if (err) {
        setNameError(err);
        return;
      }
    }

    const tool_groups = parseToolGroups(toolGroupsRaw);
    const modelValue = model === MODEL_INHERITED ? null : model || null;

    try {
      if (isEdit && agent) {
        await updateAgent.mutateAsync({
          name: agent.name,
          request: {
            description: description || null,
            model: modelValue,
            tool_groups,
            soul: soul || null,
          },
        });
        toast.success(t.agents.updateSuccess);
      } else {
        await createAgent.mutateAsync({
          name,
          description: description || undefined,
          model: modelValue,
          tool_groups,
          soul,
        });
        toast.success(t.agents.createSuccess);
      }
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] max-w-2xl flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? t.agents.editTitle : t.agents.createTitle}
          </DialogTitle>
        </DialogHeader>

        <form
          id="agent-form"
          className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto pr-1"
          onSubmit={handleSubmit}
        >
          {/* Name — only editable on create */}
          <div className="grid gap-1.5">
            <label htmlFor="agent-name" className="text-sm font-medium">
              {t.agents.name}
            </label>
            <Input
              id="agent-name"
              value={name}
              placeholder={t.agents.namePlaceholder}
              disabled={isEdit}
              onChange={(e) => {
                setName(e.target.value);
                setNameError(validateName(e.target.value));
              }}
              className={cn(nameError && "border-destructive")}
              required={!isEdit}
            />
            {nameError ? (
              <p className="text-destructive text-xs">{nameError}</p>
            ) : (
              !isEdit && (
                <p className="text-muted-foreground text-xs">
                  {t.agents.nameHint}
                </p>
              )
            )}
          </div>

          {/* Description */}
          <div className="grid gap-1.5">
            <label htmlFor="agent-description" className="text-sm font-medium">
              {t.agents.descriptionLabel}
            </label>
            <Input
              id="agent-description"
              value={description}
              placeholder={t.agents.descriptionPlaceholder}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          {/* Soul (SOUL.md) */}
          <div className="grid min-h-0 flex-1 gap-1.5">
            <label htmlFor="agent-soul" className="text-sm font-medium">
              {t.agents.soul}
            </label>
            <Textarea
              id="agent-soul"
              value={soul}
              placeholder={t.agents.soulPlaceholder}
              onChange={(e) => setSoul(e.target.value)}
              className="min-h-[160px] flex-1 resize-none font-mono text-sm"
            />
            <p className="text-muted-foreground text-xs">{t.agents.soulHint}</p>
          </div>

          {/* Model */}
          <div className="grid gap-1.5">
            <span className="text-sm font-medium">{t.agents.model}</span>
            <Select value={model} onValueChange={setModel}>
              <SelectTrigger>
                <SelectValue placeholder={t.agents.modelInherited} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={MODEL_INHERITED}>{t.agents.modelInherited}</SelectItem>
                {models.map((m) => (
                  <SelectItem key={m.name} value={m.name}>
                    {m.display_name ?? m.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Tool Groups */}
          <div className="grid gap-1.5">
            <label htmlFor="agent-tool-groups" className="text-sm font-medium">
              {t.agents.toolGroups}
            </label>
            <Input
              id="agent-tool-groups"
              value={toolGroupsRaw}
              placeholder={t.agents.toolGroupsPlaceholder}
              onChange={(e) => setToolGroupsRaw(e.target.value)}
            />
            <p className="text-muted-foreground text-xs">
              {t.agents.toolGroupsPlaceholder}
            </p>
          </div>
        </form>

        <DialogFooter className="shrink-0 pt-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isPending}
          >
            {t.common.cancel}
          </Button>
          <Button type="submit" form="agent-form" disabled={isPending}>
            {isPending ? t.common.loading : t.common.save}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
