"use client";

import { PlusIcon, Trash2Icon, PencilIcon } from "lucide-react";
import { useEffect, useState } from "react";
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
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
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
import { useI18n } from "@/core/i18n/hooks";
import { ModelsAdminRequestError } from "@/core/models/api";
import {
  useAdminModels,
  useDeleteModel,
  useUpdateModels,
} from "@/core/models/hooks";
import type { FullModelConfig } from "@/core/models/types";

import { SettingsSection } from "./settings-section";

/** Known provider entries shown in the provider select dropdown. */
interface ProviderOption {
  value: string;
  label: string;
}

const CUSTOM_PROVIDER_VALUE = "__custom__";

function getProviderOptions(
  t: ReturnType<typeof useI18n>["t"],
): ProviderOption[] {
  return [
    {
      value: "langchain_openai:ChatOpenAI",
      label: t.settings.models.providers.openai,
    },
    {
      value: "deerflow.models.patched_deepseek:PatchedChatDeepSeek",
      label: t.settings.models.providers.deepseek,
    },
    {
      value: "langchain_anthropic:ChatAnthropic",
      label: t.settings.models.providers.anthropic,
    },
    {
      value: "langchain_google_genai:ChatGoogleGenerativeAI",
      label: t.settings.models.providers.gemini,
    },
    {
      value: "langchain_ollama:ChatOllama",
      label: t.settings.models.providers.ollama,
    },
    {
      value: "deerflow.models.patched_openai:PatchedChatOpenAI",
      label: t.settings.models.providers.patchedOpenAI,
    },
    {
      value: "deerflow.models.patched_mimo:PatchedChatMiMo",
      label: t.settings.models.providers.mimo,
    },
    {
      value: "deerflow.models.patched_stepfun:PatchedChatStepFun",
      label: t.settings.models.providers.stepfun,
    },
    {
      value: "deerflow.models.patched_minimax:PatchedChatMiniMax",
      label: t.settings.models.providers.minimax,
    },
    {
      value: "deerflow.models.vllm_provider:VllmChatModel",
      label: t.settings.models.providers.vllm,
    },
    {
      value: "deerflow.models.mindie_provider:MindIEChatModel",
      label: t.settings.models.providers.mindie,
    },
    { value: CUSTOM_PROVIDER_VALUE, label: t.settings.models.providers.custom },
  ];
}

function resolveProviderValue(use: string): string {
  const known = [
    "langchain_openai:ChatOpenAI",
    "deerflow.models.patched_deepseek:PatchedChatDeepSeek",
    "langchain_anthropic:ChatAnthropic",
    "langchain_google_genai:ChatGoogleGenerativeAI",
    "langchain_ollama:ChatOllama",
    "deerflow.models.patched_openai:PatchedChatOpenAI",
    "deerflow.models.patched_mimo:PatchedChatMiMo",
    "deerflow.models.patched_stepfun:PatchedChatStepFun",
    "deerflow.models.patched_minimax:PatchedChatMiniMax",
    "deerflow.models.vllm_provider:VllmChatModel",
    "deerflow.models.mindie_provider:MindIEChatModel",
  ];
  return known.includes(use) ? use : CUSTOM_PROVIDER_VALUE;
}

function emptyModelConfig(): FullModelConfig {
  return {
    name: "",
    display_name: "",
    description: "",
    use: "",
    model: "",
    api_key: "",
    api_base: "",
    base_url: "",
    timeout: undefined,
    request_timeout: undefined,
    max_retries: undefined,
    max_tokens: undefined,
    temperature: undefined,
    supports_vision: false,
    supports_thinking: false,
    supports_reasoning_effort: false,
    when_thinking_enabled: undefined,
    when_thinking_disabled: undefined,
  };
}

export function ModelSettingsPage() {
  const { t } = useI18n();
  const { models, isLoading, error } = useAdminModels();
  const { mutate: updateModels, isPending: isSaving } = useUpdateModels();
  const { mutate: deleteModel, isPending: isDeleting } = useDeleteModel();

  const [editingModel, setEditingModel] = useState<FullModelConfig | null>(
    null,
  );
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const adminRequired =
    error instanceof ModelsAdminRequestError && error.isAdminRequired;

  const handleSave = (draft: FullModelConfig) => {
    const updated = editingModel
      ? models.map((m) => (m.name === editingModel.name ? draft : m))
      : [...models, draft];
    updateModels(updated, {
      onSuccess: () => {
        toast.success(t.settings.models.saved);
        setDialogOpen(false);
        setEditingModel(null);
      },
      onError: (err) => {
        toast.error(err.message);
      },
    });
  };

  const handleDelete = (name: string) => {
    deleteModel(name, {
      onSuccess: () => {
        toast.success(t.settings.models.deleted);
        setDeleteTarget(null);
      },
      onError: (err) => {
        toast.error(err.message);
      },
    });
  };

  const openEdit = (model: FullModelConfig) => {
    setEditingModel(model);
    setDialogOpen(true);
  };

  const openAdd = () => {
    setEditingModel(null);
    setDialogOpen(true);
  };

  return (
    <SettingsSection
      title={t.settings.models.title}
      description={t.settings.models.description}
    >
      {isLoading ? (
        <div className="text-muted-foreground text-sm">{t.common.loading}</div>
      ) : adminRequired ? (
        <div className="text-muted-foreground text-sm">
          {t.settings.models.adminRequired}
        </div>
      ) : error ? (
        <div className="text-destructive text-sm">{error.message}</div>
      ) : (
        <>
          <div className="mb-4 flex items-center justify-between">
            <span className="text-muted-foreground text-sm">
              {models.length}{" "}
              {models.length === 1
                ? t.settings.models.countSingular
                : t.settings.models.countPlural}
            </span>
            <Button size="sm" onClick={openAdd} disabled={isSaving}>
              <PlusIcon className="mr-1 size-4" />
              {t.settings.models.addModel}
            </Button>
          </div>

          {models.length === 0 ? (
            <div className="text-muted-foreground text-sm">
              {t.settings.models.empty}
            </div>
          ) : (
            <div className="flex w-full flex-col gap-3">
              {models.map((m) => (
                <Item className="w-full" variant="outline" key={m.name}>
                  <ItemContent>
                    <ItemTitle>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm">{m.name}</span>
                        {m.supports_thinking && (
                          <span className="bg-secondary text-secondary-foreground rounded px-1.5 py-0.5 text-[10px] font-medium">
                            Think
                          </span>
                        )}
                        {m.supports_vision && (
                          <span className="bg-secondary text-secondary-foreground rounded px-1.5 py-0.5 text-[10px] font-medium">
                            Vision
                          </span>
                        )}
                        {m.supports_reasoning_effort && (
                          <span className="bg-secondary text-secondary-foreground rounded px-1.5 py-0.5 text-[10px] font-medium">
                            Effort
                          </span>
                        )}
                      </div>
                    </ItemTitle>
                    <ItemDescription className="line-clamp-3">
                      {m.display_name && (
                        <span className="font-medium">{m.display_name}</span>
                      )}
                      {m.display_name && m.description && " — "}
                      {m.description}
                      {!m.display_name && !m.description && (
                        <span>
                          <code className="text-[11px]">{m.use}</code> →{" "}
                          {m.model}
                        </span>
                      )}
                    </ItemDescription>
                  </ItemContent>
                  <ItemActions>
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => openEdit(m)}
                      disabled={isSaving}
                      aria-label={t.settings.models.editModel}
                    >
                      <PencilIcon className="size-4" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => setDeleteTarget(m.name)}
                      disabled={isDeleting}
                      aria-label={t.settings.models.deleteModel}
                    >
                      <Trash2Icon className="text-destructive size-4" />
                    </Button>
                  </ItemActions>
                </Item>
              ))}
            </div>
          )}
        </>
      )}

      {/* Add / Edit dialog */}
      <ModelFormDialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open) setEditingModel(null);
        }}
        initial={editingModel}
        onSave={handleSave}
        isSaving={isSaving}
      />

      {/* Delete confirmation */}
      <Dialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.settings.models.deleteModel}</DialogTitle>
            <DialogDescription>
              {t.settings.models.deleteConfirm}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteTarget(null)}
              disabled={isDeleting}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteTarget && handleDelete(deleteTarget)}
              disabled={isDeleting}
            >
              {t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SettingsSection>
  );
}

// ---------------------------------------------------------------------------
// Add / Edit form dialog
// ---------------------------------------------------------------------------

function ModelFormDialog({
  open,
  onOpenChange,
  initial,
  onSave,
  isSaving,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial: FullModelConfig | null;
  onSave: (draft: FullModelConfig) => void;
  isSaving: boolean;
}) {
  const { t } = useI18n();
  const isEditing = initial !== null;
  const [draft, setDraft] = useState<FullModelConfig>(emptyModelConfig());
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Raw textarea content for the thinking JSON fields, tracked separately
  // so that a JSON parse error does not silently revert to the last valid value.
  const [whenThinkingEnabledText, setWhenThinkingEnabledText] = useState("");
  const [whenThinkingEnabledError, setWhenThinkingEnabledError] =
    useState(false);
  const [whenThinkingDisabledText, setWhenThinkingDisabledText] = useState("");
  const [whenThinkingDisabledError, setWhenThinkingDisabledError] =
    useState(false);

  // Sync draft when dialog opens with new initial data.
  useEffect(() => {
    if (open) {
      const next = initial ?? emptyModelConfig();
      setDraft(next);
      setShowAdvanced(false);
      setWhenThinkingEnabledText(
        next.when_thinking_enabled
          ? JSON.stringify(next.when_thinking_enabled, null, 2)
          : "",
      );
      setWhenThinkingEnabledError(false);
      setWhenThinkingDisabledText(
        next.when_thinking_disabled
          ? JSON.stringify(next.when_thinking_disabled, null, 2)
          : "",
      );
      setWhenThinkingDisabledError(false);
    }
  }, [open, initial]);

  const set = (key: keyof FullModelConfig, value: unknown) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = () => {
    if (!draft.name.trim()) return;
    if (!draft.use.trim()) return;
    if (!draft.model.trim()) return;

    // Clean up empty optional fields.
    const cleaned = { ...draft };
    for (const k of [
      "api_key",
      "api_base",
      "base_url",
      "display_name",
      "description",
    ] as const) {
      if (cleaned[k] === "")
        (cleaned as Record<string, unknown>)[k] = undefined;
    }
    onSave(cleaned);
  };

  const inputClass = "col-span-3" as const;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[85vh] sm:max-w-lg"
        aria-describedby={undefined}
      >
        <DialogHeader>
          <DialogTitle>
            {isEditing
              ? t.settings.models.editModel
              : t.settings.models.addModel}
          </DialogTitle>
        </DialogHeader>

        <ScrollArea className="max-h-[60vh]">
          <div className="grid grid-cols-[120px_1fr] items-center gap-x-4 gap-y-4 pr-4">
            {/* Name */}
            <label className="text-right text-sm font-medium">
              {t.settings.models.name} *
            </label>
            <Input
              className={inputClass}
              value={draft.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="deepseek-v4-flash"
              disabled={isEditing}
            />

            {/* Display name */}
            <label className="text-right text-sm font-medium">
              {t.settings.models.displayName}
            </label>
            <Input
              className={inputClass}
              value={draft.display_name ?? ""}
              onChange={(e) => set("display_name", e.target.value || undefined)}
              placeholder="DeepSeek V4 Flash"
            />

            {/* Description */}
            <label className="text-right text-sm font-medium">
              {t.settings.models.description}
            </label>
            <Input
              className={inputClass}
              value={draft.description ?? ""}
              onChange={(e) => set("description", e.target.value || undefined)}
              placeholder={t.settings.models.descriptionPlaceholder}
            />

            {/* Provider class */}
            <label className="text-right text-sm font-medium">
              {t.settings.models.providerClass} *
            </label>
            <div className="col-span-3 space-y-2">
              <Select
                value={resolveProviderValue(draft.use)}
                onValueChange={(v) => {
                  if (v === CUSTOM_PROVIDER_VALUE) {
                    set("use", "");
                  } else {
                    set("use", v);
                  }
                }}
              >
                <SelectTrigger>
                  <SelectValue
                    placeholder={t.settings.models.providers.placeholder}
                  />
                </SelectTrigger>
                <SelectContent>
                  {getProviderOptions(t).map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {resolveProviderValue(draft.use) === CUSTOM_PROVIDER_VALUE && (
                <Input
                  value={draft.use}
                  onChange={(e) => set("use", e.target.value)}
                  placeholder="package.module:ClassName"
                />
              )}
            </div>

            {/* Model ID */}
            <label className="text-right text-sm font-medium">
              {t.settings.models.modelId} *
            </label>
            <Input
              className={inputClass}
              value={draft.model}
              onChange={(e) => set("model", e.target.value)}
              placeholder="gpt-4"
            />

            {/* API Key */}
            <label className="text-right text-sm font-medium">
              {t.settings.models.apiKey}
            </label>
            <Input
              className={inputClass}
              type="password"
              value={draft.api_key! ?? ""}
              onChange={(e) => set("api_key", e.target.value || undefined)}
              placeholder={
                isEditing
                  ? t.settings.models.apiKeyPlaceholderEdit
                  : t.settings.models.apiKeyPlaceholder
              }
            />

            {/* API Base */}
            <label className="text-right text-sm font-medium">
              {t.settings.models.apiBase}
            </label>
            <Input
              className={inputClass}
              value={draft.api_base ?? draft.base_url ?? ""}
              onChange={(e) => {
                const val = e.target.value || undefined;
                set("api_base", val);
                set("base_url", val);
              }}
              placeholder="https://api.openai.com/v1"
            />

            {/* Capability toggles */}
            <label className="text-right text-sm font-medium">
              {t.settings.models.capabilities}
            </label>
            <div className="col-span-3 flex flex-wrap gap-x-6 gap-y-2">
              <ToggleField
                label={t.settings.models.supportsThinking}
                checked={draft.supports_thinking ?? false}
                onChange={(v) => set("supports_thinking", v)}
              />
              <ToggleField
                label={t.settings.models.supportsVision}
                checked={draft.supports_vision ?? false}
                onChange={(v) => set("supports_vision", v)}
              />
              <ToggleField
                label={t.settings.models.supportsReasoningEffort}
                checked={draft.supports_reasoning_effort ?? false}
                onChange={(v) => set("supports_reasoning_effort", v)}
              />
            </div>

            {/* Advanced toggle */}
            <div className="col-span-4 mt-2">
              <button
                type="button"
                className="text-muted-foreground text-xs hover:underline"
                onClick={() => setShowAdvanced(!showAdvanced)}
              >
                {showAdvanced
                  ? t.settings.models.advancedHide
                  : t.settings.models.advanced}
              </button>
            </div>

            {showAdvanced && (
              <>
                {/* Timeout */}
                <label className="text-right text-sm font-medium">
                  {t.settings.models.timeout}
                </label>
                <Input
                  className={inputClass}
                  type="number"
                  value={draft.timeout ?? draft.request_timeout ?? ""}
                  onChange={(e) => {
                    const v = e.target.value
                      ? parseFloat(e.target.value)
                      : undefined;
                    set("timeout", v);
                    set("request_timeout", v);
                  }}
                  placeholder="600"
                />

                {/* Max retries */}
                <label className="text-right text-sm font-medium">
                  {t.settings.models.maxRetries}
                </label>
                <Input
                  className={inputClass}
                  type="number"
                  value={draft.max_retries ?? ""}
                  onChange={(e) =>
                    set(
                      "max_retries",
                      e.target.value ? parseInt(e.target.value) : undefined,
                    )
                  }
                  placeholder="2"
                />

                {/* Max tokens */}
                <label className="text-right text-sm font-medium">
                  {t.settings.models.maxTokens}
                </label>
                <Input
                  className={inputClass}
                  type="number"
                  value={draft.max_tokens ?? ""}
                  onChange={(e) =>
                    set(
                      "max_tokens",
                      e.target.value ? parseInt(e.target.value) : undefined,
                    )
                  }
                  placeholder="8192"
                />

                {/* Temperature */}
                <label className="text-right text-sm font-medium">
                  {t.settings.models.temperature}
                </label>
                <Input
                  className={inputClass}
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                  value={draft.temperature ?? ""}
                  onChange={(e) =>
                    set(
                      "temperature",
                      e.target.value ? parseFloat(e.target.value) : undefined,
                    )
                  }
                  placeholder="0.7"
                />

                {/* when_thinking_enabled */}
                <label className="text-right text-sm font-medium">
                  {t.settings.models.whenThinkingEnabled}
                </label>
                <div className="col-span-3 space-y-1">
                  <Textarea
                    className={inputClass}
                    rows={3}
                    value={whenThinkingEnabledText}
                    onChange={(e) => {
                      const rawText = e.target.value;
                      setWhenThinkingEnabledText(rawText);
                      try {
                        const v = rawText.trim()
                          ? JSON.parse(rawText)
                          : undefined;
                        set("when_thinking_enabled", v);
                        setWhenThinkingEnabledError(false);
                      } catch {
                        setWhenThinkingEnabledError(true);
                      }
                    }}
                    placeholder='{"extra_body": {"thinking": {"type": "enabled"}}}'
                  />
                  {whenThinkingEnabledError && (
                    <p className="text-destructive text-xs">
                      {t.settings.models.invalidJson}
                    </p>
                  )}
                </div>

                {/* when_thinking_disabled */}
                <label className="text-right text-sm font-medium">
                  {t.settings.models.whenThinkingDisabled}
                </label>
                <div className="col-span-3 space-y-1">
                  <Textarea
                    className={inputClass}
                    rows={3}
                    value={whenThinkingDisabledText}
                    onChange={(e) => {
                      const rawText = e.target.value;
                      setWhenThinkingDisabledText(rawText);
                      try {
                        const v = rawText.trim()
                          ? JSON.parse(rawText)
                          : undefined;
                        set("when_thinking_disabled", v);
                        setWhenThinkingDisabledError(false);
                      } catch {
                        setWhenThinkingDisabledError(true);
                      }
                    }}
                    placeholder='{"extra_body": {"thinking": {"type": "disabled"}}}'
                  />
                  {whenThinkingDisabledError && (
                    <p className="text-destructive text-xs">
                      {t.settings.models.invalidJson}
                    </p>
                  )}
                </div>
              </>
            )}
          </div>
        </ScrollArea>

        <DialogFooter className="mt-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t.common.cancel}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={
              isSaving ||
              !draft.name.trim() ||
              !draft.use.trim() ||
              !draft.model.trim() ||
              whenThinkingEnabledError ||
              whenThinkingDisabledError
            }
          >
            {t.common.save}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ToggleField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <Switch checked={checked} onCheckedChange={onChange} />
      <span className="text-muted-foreground">{label}</span>
    </label>
  );
}
