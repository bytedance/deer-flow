"use client";

import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { useUpdateAgent } from "@/core/agents";
import type { Agent, ReasoningEffort } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";

import {
  DEFAULT_MODEL_VALUE,
  INHERIT_VALUE,
  MAX_AGENT_OUTPUT_TOKENS,
  parseAgentModelSettingsDraft,
  resolveEffectiveModel,
  selectionToThinkingEnabled,
  thinkingEnabledToSelection,
} from "./agent-settings-dialog-helpers";

const REASONING_EFFORTS: ReasoningEffort[] = ["low", "medium", "high"];

interface AgentSettingsDialogProps {
  agent: Agent;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Edits a custom agent's model behavior (issue #4336): default model plus the
 * per-agent temperature / max_tokens overrides and thinking / reasoning
 * defaults. Persists through `PUT /api/agents/{name}`; changes take effect on
 * the agent's next run.
 */
export function AgentSettingsDialog({
  agent,
  open,
  onOpenChange,
}: AgentSettingsDialogProps) {
  const { t } = useI18n();
  const { models } = useModels();
  const updateAgent = useUpdateAgent();

  const [model, setModel] = useState(agent.model ?? DEFAULT_MODEL_VALUE);
  const [temperature, setTemperature] = useState(
    agent.model_settings?.temperature != null
      ? String(agent.model_settings.temperature)
      : "",
  );
  const [maxTokens, setMaxTokens] = useState(
    agent.model_settings?.max_tokens != null
      ? String(agent.model_settings.max_tokens)
      : "",
  );
  const [thinking, setThinking] = useState(
    thinkingEnabledToSelection(agent.thinking_enabled),
  );
  const [reasoningEffort, setReasoningEffort] = useState(
    agent.reasoning_effort ?? INHERIT_VALUE,
  );

  // The resolved profile gates which controls are meaningful: thinking and
  // reasoning-effort only apply when the selected model advertises support.
  // When the agent inherits the global default model, fall back to the
  // effective default (models[0]) so the controls are not hidden for it.
  const selectedModel = useMemo(
    () => resolveEffectiveModel(models, model),
    [models, model],
  );
  const supportsThinking = selectedModel?.supports_thinking ?? false;
  const supportsReasoningEffort =
    selectedModel?.supports_reasoning_effort ?? false;

  async function handleSave() {
    const parsedSettings = parseAgentModelSettingsDraft({
      temperature,
      maxTokens,
    });
    if (!parsedSettings.ok) {
      toast.error(
        parsedSettings.error === "temperature"
          ? t.agents.settingsInvalidTemperature
          : t.agents.settingsInvalidMaxTokens,
      );
      return;
    }

    try {
      await updateAgent.mutateAsync({
        name: agent.name,
        request: {
          model: model === DEFAULT_MODEL_VALUE ? null : model,
          model_settings: parsedSettings.modelSettings,
          thinking_enabled: supportsThinking
            ? selectionToThinkingEnabled(thinking)
            : null,
          reasoning_effort:
            supportsReasoningEffort && reasoningEffort !== INHERIT_VALUE
              ? (reasoningEffort as ReasoningEffort)
              : null,
        },
      });
      toast.success(t.agents.settingsSaved);
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t.agents.settingsTitle}</DialogTitle>
          <DialogDescription>{t.agents.settingsDescription}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-1">
          {/* Default model */}
          <div className="space-y-1.5">
            <span className="text-sm font-medium">
              {t.agents.settingsModel}
            </span>
            <Select value={model} onValueChange={setModel}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={DEFAULT_MODEL_VALUE}>
                  {t.agents.settingsModelDefault}
                </SelectItem>
                {models.map((m) => (
                  <SelectItem key={m.name} value={m.name}>
                    {m.display_name || m.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Temperature */}
          <div className="space-y-1.5">
            <span className="text-sm font-medium">
              {t.agents.settingsTemperature}
            </span>
            <Input
              type="number"
              min={0}
              max={2}
              step={0.1}
              value={temperature}
              placeholder={t.agents.settingsInherit}
              onChange={(e) => setTemperature(e.target.value)}
            />
            <p className="text-muted-foreground text-xs">
              {t.agents.settingsTemperatureHint}
            </p>
          </div>

          {/* Max output tokens */}
          <div className="space-y-1.5">
            <span className="text-sm font-medium">
              {t.agents.settingsMaxTokens}
            </span>
            <Input
              type="number"
              min={1}
              max={MAX_AGENT_OUTPUT_TOKENS}
              step={1}
              value={maxTokens}
              placeholder={t.agents.settingsMaxTokensPlaceholder}
              onChange={(e) => setMaxTokens(e.target.value)}
            />
          </div>

          {/* Thinking mode (only when the selected model supports it) */}
          {supportsThinking && (
            <div className="space-y-1.5">
              <span className="text-sm font-medium">
                {t.agents.settingsThinking}
              </span>
              <Select
                value={thinking}
                onValueChange={(value) => setThinking(value as typeof thinking)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={INHERIT_VALUE}>
                    {t.agents.settingsInherit}
                  </SelectItem>
                  <SelectItem value="on">
                    {t.agents.settingsThinkingOn}
                  </SelectItem>
                  <SelectItem value="off">
                    {t.agents.settingsThinkingOff}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Reasoning effort (only when supported) */}
          {supportsReasoningEffort && (
            <div className="space-y-1.5">
              <span className="text-sm font-medium">
                {t.agents.settingsReasoningEffort}
              </span>
              <Select
                value={reasoningEffort}
                onValueChange={setReasoningEffort}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={INHERIT_VALUE}>
                    {t.agents.settingsInherit}
                  </SelectItem>
                  {REASONING_EFFORTS.map((effort) => (
                    <SelectItem key={effort} value={effort}>
                      {effort}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={updateAgent.isPending}
          >
            {t.common.cancel}
          </Button>
          <Button onClick={handleSave} disabled={updateAgent.isPending}>
            {updateAgent.isPending ? t.common.loading : t.common.save}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
