"use client";

import { CheckIcon } from "lucide-react";
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
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAgent, useUpdateAgent } from "@/core/agents";
import type { Agent, ReasoningEffort } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { useSkills } from "@/core/skills/hooks";
import { cn } from "@/lib/utils";

import {
  DEFAULT_MODEL_VALUE,
  INHERIT_VALUE,
  MAX_AGENT_OUTPUT_TOKENS,
  parseAgentModelSettingsDraft,
  resolveEffectiveModel,
  seedSkillsSelection,
  selectionToThinkingEnabled,
  skillsSelectionToPayload,
  thinkingEnabledToSelection,
} from "./agent-settings-dialog-helpers";

const REASONING_EFFORTS: ReasoningEffort[] = ["low", "medium", "high"];

interface AgentSettingsDialogProps {
  agent: Agent;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Edits a custom agent's configuration: system prompt (SOUL.md), skill
 * allowlist, and per-agent model behavior (the model fields shipped in issue
 * #4336; this adds prompt + skills). The full agent — including SOUL.md, which
 * the gallery list endpoint omits — is fetched on open so the editor seeds from
 * authoritative data and an unchanged save can never clobber SOUL.md with a
 * value it never loaded. Persists through `PUT /api/agents/{name}`; changes
 * take effect on the agent's next run.
 */
export function AgentSettingsDialog({
  agent,
  open,
  onOpenChange,
}: AgentSettingsDialogProps) {
  const { t } = useI18n();
  const { agent: full, isLoading, error } = useAgent(open ? agent.name : null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t.agents.settingsTitle}</DialogTitle>
          <DialogDescription>{t.agents.settingsDescription}</DialogDescription>
        </DialogHeader>

        {full ? (
          // Keyed on name so switching agents (defensive) re-seeds form state.
          <AgentSettingsForm
            key={full.name}
            agent={full}
            onOpenChange={onOpenChange}
          />
        ) : (
          <div className="text-muted-foreground py-8 text-center text-sm">
            {isLoading
              ? t.common.loading
              : error instanceof Error
                ? error.message
                : t.agents.settingsLoadError}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function AgentSettingsForm({
  agent,
  onOpenChange,
}: {
  agent: Agent;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const { models } = useModels();
  const { skills } = useSkills();
  const updateAgent = useUpdateAgent();

  const [soul, setSoul] = useState(agent.soul ?? "");

  const initialSkills = useMemo(
    () => seedSkillsSelection(agent.skills),
    [agent.skills],
  );
  const [useAllSkills, setUseAllSkills] = useState(initialSkills.useAll);
  const [selectedSkills, setSelectedSkills] = useState<string[]>(
    initialSkills.selected,
  );

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

  // Choices = enabled skills, unioned with any already-selected skill whose
  // enabled flag is off or that is no longer present, so editing the set never
  // silently drops an existing allowlist entry.
  const skillOptions = useMemo(() => {
    const enabled = skills.filter((s) => s.enabled).map((s) => s.name);
    const extra = selectedSkills.filter((name) => !enabled.includes(name));
    return [...enabled, ...extra];
  }, [skills, selectedSkills]);

  function toggleSkill(name: string) {
    setSelectedSkills((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  }

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
          soul,
          skills: skillsSelectionToPayload(useAllSkills, selectedSkills),
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
    <>
      <div className="space-y-5 py-1">
        {/* System prompt (SOUL.md) */}
        <div className="space-y-1.5">
          <span className="text-sm font-medium">
            {t.agents.settingsSystemPrompt}
          </span>
          <Textarea
            value={soul}
            onChange={(e) => setSoul(e.target.value)}
            placeholder={t.agents.settingsSystemPromptPlaceholder}
            className="max-h-72 min-h-32"
          />
          <p className="text-muted-foreground text-xs">
            {t.agents.settingsSystemPromptHint}
          </p>
        </div>

        {/* Skills */}
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium">
              {t.agents.settingsSkills}
            </span>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground text-xs">
                {t.agents.settingsSkillsUseAll}
              </span>
              <Switch
                checked={useAllSkills}
                onCheckedChange={setUseAllSkills}
              />
            </div>
          </div>
          {useAllSkills ? (
            <p className="text-muted-foreground text-xs">
              {t.agents.settingsSkillsUseAllHint}
            </p>
          ) : skillOptions.length === 0 ? (
            <p className="text-muted-foreground text-xs">
              {t.agents.settingsSkillsEmpty}
            </p>
          ) : (
            <ScrollArea className="max-h-48 rounded-md border">
              <div className="flex flex-col p-1">
                {skillOptions.map((name) => {
                  const selected = selectedSkills.includes(name);
                  return (
                    <button
                      key={name}
                      type="button"
                      onClick={() => toggleSkill(name)}
                      className="hover:bg-accent flex items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm"
                    >
                      <CheckIcon
                        className={cn(
                          "h-4 w-4 shrink-0",
                          selected ? "opacity-100" : "opacity-0",
                        )}
                      />
                      <span className="truncate">{name}</span>
                    </button>
                  );
                })}
              </div>
            </ScrollArea>
          )}
        </div>

        {/* Model behavior (issue #4336) */}
        <div className="space-y-4 border-t pt-4">
          <span className="text-sm font-medium">
            {t.agents.settingsSectionModel}
          </span>

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
    </>
  );
}
