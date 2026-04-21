"use client";

import { CheckIcon, PlusIcon, RefreshCwIcon, Trash2Icon } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import {
  useCreateModel,
  useDeleteModel,
  useDetectModels,
  useModels,
  useUpdateModel,
} from "@/core/models/hooks";
import type {
  DetectedModel,
  Model,
  ModelUpsertPayload,
} from "@/core/models/types";
import { env } from "@/env";

import { SettingsSection } from "./settings-section";

type ModelForm = {
  name: string;
  model: string;
  displayName: string;
  description: string;
  baseUrl: string;
  apiKey: string;
  contextLength: string;
  temperature: string;
  topP: string;
  frequencyPenalty: string;
  systemPrompt: string;
  supportsThinking: boolean;
  supportsReasoningEffort: boolean;
  supportsVision: boolean;
  modalities: string;
};

const emptyForm: ModelForm = {
  name: "",
  model: "",
  displayName: "",
  description: "",
  baseUrl: "",
  apiKey: "",
  contextLength: "",
  temperature: "",
  topP: "",
  frequencyPenalty: "",
  systemPrompt: "",
  supportsThinking: false,
  supportsReasoningEffort: false,
  supportsVision: false,
  modalities: "text",
};

function numberOrNull(value: string): number | null {
  if (value.trim() === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formFromDetected(
  model: DetectedModel,
  baseUrl: string,
  apiKey: string,
): ModelForm {
  return {
    ...emptyForm,
    name: model.name,
    model: model.id,
    displayName: model.display_name,
    baseUrl,
    apiKey,
    contextLength: model.context_length?.toString() ?? "",
    supportsThinking: model.supports_thinking,
    supportsReasoningEffort: model.supports_reasoning_effort,
    supportsVision: model.supports_vision,
    modalities: model.modalities.join(", "),
  };
}

function formFromModel(model: Model): ModelForm {
  return {
    ...emptyForm,
    name: model.name,
    model: model.model,
    displayName: model.display_name,
    description: model.description ?? "",
    baseUrl: model.base_url ?? "",
    contextLength: model.context_length?.toString() ?? "",
    supportsThinking: model.supports_thinking ?? false,
    supportsReasoningEffort: model.supports_reasoning_effort ?? false,
    supportsVision: model.supports_vision ?? false,
    modalities: (model.modalities ?? ["text"]).join(", "),
  };
}

function formToPayload(form: ModelForm): ModelUpsertPayload {
  return {
    name: form.name.trim(),
    model: form.model.trim(),
    display_name: form.displayName.trim() || form.name.trim(),
    description: form.description.trim() || null,
    base_url: form.baseUrl.trim() || null,
    api_key: form.apiKey.trim() || null,
    context_length: numberOrNull(form.contextLength),
    temperature: numberOrNull(form.temperature),
    top_p: numberOrNull(form.topP),
    frequency_penalty: numberOrNull(form.frequencyPenalty),
    system_prompt: form.systemPrompt.trim() || null,
    supports_thinking: form.supportsThinking,
    supports_reasoning_effort: form.supportsReasoningEffort,
    supports_vision: form.supportsVision,
    modalities: form.modalities
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  };
}

function getMissingRequiredFields(
  form: ModelForm,
  labels: { name: string; modelId: string; baseUrl: string; apiKey: string },
  isEditing: boolean,
): string[] {
  const missing: string[] = [];
  if (!form.name.trim()) {
    missing.push(labels.name);
  }
  if (!form.model.trim()) {
    missing.push(labels.modelId);
  }
  if (!form.baseUrl.trim()) {
    missing.push(labels.baseUrl);
  }
  if (!isEditing && !form.apiKey.trim()) {
    missing.push(labels.apiKey);
  }
  return missing;
}

export function ModelSettingsPage() {
  const { t } = useI18n();
  const copy = t.settings.models;
  const { models, isLoading, error } = useModels();
  const detectMutation = useDetectModels();
  const createMutation = useCreateModel();
  const updateMutation = useUpdateModel();
  const deleteMutation = useDeleteModel();
  const [detectBaseUrl, setDetectBaseUrl] = useState("");
  const [detectApiKey, setDetectApiKey] = useState("");
  const [form, setForm] = useState<ModelForm>(emptyForm);
  const [editingName, setEditingName] = useState<string | null>(null);

  const detectedModels = detectMutation.data?.models ?? [];
  const isStatic = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";
  const isSaving = createMutation.isPending || updateMutation.isPending;
  const submitDisabled = isStatic || isSaving;

  const existingNames = useMemo(
    () => new Set(models.map((model) => model.name)),
    [models],
  );

  async function handleDetect() {
    try {
      const result = await detectMutation.mutateAsync({
        baseUrl: detectBaseUrl,
        apiKey: detectApiKey,
      });
      toast.success(copy.detectSuccess(result.models.length));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleSubmit() {
    try {
      const missingFields = getMissingRequiredFields(
        form,
        {
          name: copy.name,
          modelId: copy.modelId,
          baseUrl: copy.baseUrl,
          apiKey: copy.apiKey,
        },
        Boolean(editingName),
      );
      if (missingFields.length > 0) {
        toast.error(copy.requiredFieldsMissing(missingFields.join(", ")));
        return;
      }
      const payload = formToPayload(form);
      if (editingName) {
        await updateMutation.mutateAsync({ name: editingName, payload });
        toast.success(copy.updateSuccess);
      } else {
        await createMutation.mutateAsync(payload);
        toast.success(copy.createSuccess);
      }
      setForm(emptyForm);
      setEditingName(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDelete(model: Model) {
    if (!window.confirm(copy.deleteConfirm(model.display_name || model.name))) {
      return;
    }
    try {
      await deleteMutation.mutateAsync(model.name);
      if (editingName === model.name) {
        setForm(emptyForm);
        setEditingName(null);
      }
      toast.success(copy.deleteSuccess);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <SettingsSection title={copy.title} description={copy.description}>
      <div className="space-y-6">
        <section className="space-y-3">
          <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
            <Input
              value={detectBaseUrl}
              onChange={(event) => setDetectBaseUrl(event.target.value)}
              placeholder={copy.baseUrlPlaceholder}
              disabled={isStatic}
            />
            <Input
              value={detectApiKey}
              onChange={(event) => setDetectApiKey(event.target.value)}
              placeholder={copy.apiKeyPlaceholder}
              type="password"
              disabled={isStatic}
            />
            <Button
              type="button"
              onClick={handleDetect}
              disabled={
                isStatic || detectMutation.isPending || !detectBaseUrl.trim()
              }
            >
              <RefreshCwIcon className="size-4" />
              {detectMutation.isPending ? copy.detecting : copy.detect}
            </Button>
          </div>
          {detectedModels.length > 0 && (
            <div className="grid gap-2">
              {detectedModels.map((model) => {
                const alreadyExists = existingNames.has(model.name);
                return (
                  <Item key={model.id} variant="outline">
                    <ItemContent>
                      <ItemTitle>{model.display_name}</ItemTitle>
                      <ItemDescription>
                        {model.id}
                        {model.context_length
                          ? ` · ${model.context_length.toLocaleString()} tokens`
                          : ""}
                      </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                      <Button
                        type="button"
                        size="sm"
                        variant={alreadyExists ? "secondary" : "outline"}
                        onClick={() => {
                          setForm(
                            formFromDetected(
                              model,
                              detectBaseUrl,
                              detectApiKey,
                            ),
                          );
                          setEditingName(alreadyExists ? model.name : null);
                        }}
                      >
                        {alreadyExists ? (
                          <CheckIcon className="size-4" />
                        ) : (
                          <PlusIcon className="size-4" />
                        )}
                        {alreadyExists ? copy.edit : copy.add}
                      </Button>
                    </ItemActions>
                  </Item>
                );
              })}
            </div>
          )}
        </section>

        <section className="space-y-3 rounded-lg border p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="font-medium">
              {editingName ? copy.editModel : copy.manualModel}
            </div>
            {editingName && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setForm(emptyForm);
                  setEditingName(null);
                }}
              >
                {copy.clear}
              </Button>
            )}
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label={copy.name}>
              <Input
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
                placeholder="gpt-4o"
                disabled={isStatic}
              />
            </Field>
            <Field label={copy.modelId}>
              <Input
                value={form.model}
                onChange={(event) =>
                  setForm({ ...form, model: event.target.value })
                }
                placeholder="gpt-4o"
                disabled={isStatic}
              />
            </Field>
            <Field label={copy.displayName}>
              <Input
                value={form.displayName}
                onChange={(event) =>
                  setForm({ ...form, displayName: event.target.value })
                }
                placeholder="GPT-4o"
                disabled={isStatic}
              />
            </Field>
            <Field label={copy.baseUrl}>
              <Input
                value={form.baseUrl}
                onChange={(event) =>
                  setForm({ ...form, baseUrl: event.target.value })
                }
                placeholder="https://api.openai.com/v1"
                disabled={isStatic}
              />
            </Field>
            <Field label={copy.apiKey}>
              <Input
                value={form.apiKey}
                onChange={(event) =>
                  setForm({ ...form, apiKey: event.target.value })
                }
                type="password"
                placeholder={editingName ? copy.keepApiKey : "$OPENAI_API_KEY"}
                disabled={isStatic}
              />
            </Field>
            <Field label={copy.contextLength}>
              <Input
                value={form.contextLength}
                onChange={(event) =>
                  setForm({ ...form, contextLength: event.target.value })
                }
                inputMode="numeric"
                placeholder="128000"
                disabled={isStatic}
              />
            </Field>
            <Field label={copy.temperature}>
              <Input
                value={form.temperature}
                onChange={(event) =>
                  setForm({ ...form, temperature: event.target.value })
                }
                inputMode="decimal"
                placeholder="0.7"
                disabled={isStatic}
              />
            </Field>
            <Field label={copy.topP}>
              <Input
                value={form.topP}
                onChange={(event) =>
                  setForm({ ...form, topP: event.target.value })
                }
                inputMode="decimal"
                placeholder="1"
                disabled={isStatic}
              />
            </Field>
            <Field label={copy.frequencyPenalty}>
              <Input
                value={form.frequencyPenalty}
                onChange={(event) =>
                  setForm({ ...form, frequencyPenalty: event.target.value })
                }
                inputMode="decimal"
                placeholder="0"
                disabled={isStatic}
              />
            </Field>
            <Field label={copy.modalities}>
              <Input
                value={form.modalities}
                onChange={(event) =>
                  setForm({ ...form, modalities: event.target.value })
                }
                placeholder="text, vision"
                disabled={isStatic}
              />
            </Field>
          </div>
          <Field label={copy.descriptionLabel}>
            <Textarea
              value={form.description}
              onChange={(event) =>
                setForm({ ...form, description: event.target.value })
              }
              disabled={isStatic}
            />
          </Field>
          <Field label={copy.systemPrompt}>
            <Textarea
              value={form.systemPrompt}
              onChange={(event) =>
                setForm({ ...form, systemPrompt: event.target.value })
              }
              disabled={isStatic}
            />
          </Field>
          <div className="grid gap-3 md:grid-cols-3">
            <CapabilitySwitch
              label={copy.supportsThinking}
              checked={form.supportsThinking}
              onCheckedChange={(checked) =>
                setForm({ ...form, supportsThinking: checked })
              }
              disabled={isStatic}
            />
            <CapabilitySwitch
              label={copy.supportsReasoningEffort}
              checked={form.supportsReasoningEffort}
              onCheckedChange={(checked) =>
                setForm({ ...form, supportsReasoningEffort: checked })
              }
              disabled={isStatic}
            />
            <CapabilitySwitch
              label={copy.supportsVision}
              checked={form.supportsVision}
              onCheckedChange={(checked) =>
                setForm({ ...form, supportsVision: checked })
              }
              disabled={isStatic}
            />
          </div>
          <div className="flex justify-end">
            <Button
              type="button"
              onClick={handleSubmit}
              disabled={submitDisabled}
            >
              {isSaving
                ? copy.saving
                : editingName
                  ? copy.saveChanges
                  : copy.save}
            </Button>
          </div>
        </section>

        <section className="space-y-3">
          <div className="font-medium">{copy.configuredModels}</div>
          {isLoading ? (
            <div className="text-muted-foreground text-sm">
              {t.common.loading}
            </div>
          ) : error ? (
            <div className="text-destructive text-sm">
              {error instanceof Error ? error.message : String(error)}
            </div>
          ) : (
            <div className="grid gap-2">
              {models.map((model) => (
                <Item key={model.name} variant="outline">
                  <ItemContent>
                    <ItemTitle>
                      <div className="flex flex-wrap items-center gap-2">
                        <span>{model.display_name}</span>
                        {model.supports_thinking && (
                          <Badge>{copy.thinking}</Badge>
                        )}
                        {model.supports_vision && <Badge>{copy.vision}</Badge>}
                      </div>
                    </ItemTitle>
                    <ItemDescription>
                      {model.name} · {model.model}
                      {model.base_url ? ` · ${model.base_url}` : ""}
                    </ItemDescription>
                  </ItemContent>
                  <ItemActions>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setForm(formFromModel(model));
                        setEditingName(model.name);
                      }}
                    >
                      {copy.edit}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => handleDelete(model)}
                      disabled={isStatic || deleteMutation.isPending}
                      title={t.common.delete}
                    >
                      <Trash2Icon className="size-4" />
                    </Button>
                  </ItemActions>
                </Item>
              ))}
              {models.length === 0 && (
                <div className="text-muted-foreground text-sm">
                  {copy.empty}
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </SettingsSection>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="grid gap-1.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function CapabilitySwitch({
  label,
  checked,
  disabled,
  onCheckedChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm">
      <span>{label}</span>
      <Switch
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
      />
    </label>
  );
}
