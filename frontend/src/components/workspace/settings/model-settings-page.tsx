"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
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
import { GatewayApiError } from "@/core/api/errors";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { MODELS_QUERY_KEY } from "@/core/models/hooks";
import {
  loadManagedModels,
  loadManagedModelProviders,
  modelDraft,
  saveManagedModel,
  testManagedModel,
  type ManagedModel,
  type ManagedModelProvider,
} from "@/core/models/management";
import { isStaticWebsiteOnly } from "@/core/static-mode";

import { SettingsSection } from "./settings-section";

function modelManagementError(
  error: unknown,
  text: {
    failed: string;
    revisionConflict: string;
    keyOrCapabilities: string;
    invalidModel: string;
  },
) {
  if (error instanceof GatewayApiError) {
    if (error.status === 409) return text.revisionConflict;
    if (error.code === "model_key_or_capabilities")
      return text.keyOrCapabilities;
    if (error.status === 422) return text.invalidModel;
    return text.failed;
  }
  return error instanceof Error ? error.message : text.failed;
}

export function ModelSettingsPage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const text = t.settings.models;
  const client = useQueryClient();
  const canManage = user?.system_role === "admin" && !isStaticWebsiteOnly();
  const queryKey = ["managed-models", user?.id];
  const catalog = useQuery({
    queryKey,
    queryFn: ({ signal }) => loadManagedModels(signal),
    enabled: canManage,
  });
  const providers = useQuery({
    queryKey: ["managed-model-providers", user?.id],
    queryFn: ({ signal }) => loadManagedModelProviders(signal),
    enabled: canManage,
    staleTime: Infinity,
  });
  const [editing, setEditing] = useState<ManagedModel | "new" | null>(null);
  const [pending, setPending] = useState(false);
  async function refresh() {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["managed-models"] }),
      client.invalidateQueries({ queryKey: MODELS_QUERY_KEY }),
    ]);
  }
  async function toggle(model: ManagedModel) {
    setPending(true);
    try {
      await saveManagedModel({
        config: { ...modelDraft(model), enabled: !model.enabled },
        expected_revision: model.revision,
      });
      await refresh();
    } catch (error) {
      toast.error(modelManagementError(error, text));
    } finally {
      setPending(false);
    }
  }
  return (
    <SettingsSection title={text.title} description={text.description}>
      {!canManage ? (
        <p>{text.adminOnly}</p>
      ) : (
        <div className="space-y-4">
          <div className="flex gap-2">
            <Button
              disabled={pending || !providers.data}
              onClick={() => setEditing("new")}
            >
              {text.add}
            </Button>
            <Button
              variant="outline"
              disabled={pending || catalog.isFetching}
              onClick={() => {
                void catalog.refetch();
                void providers.refetch();
              }}
            >
              {text.reload}
            </Button>
          </div>
          {(catalog.isLoading || providers.isLoading) && (
            <p role="status">{text.loading}</p>
          )}
          {(catalog.error ?? providers.error) && (
            <div role="alert">
              <p>{text.failed}</p>
            </div>
          )}
          {catalog.data?.models.length === 0 && <p>{text.empty}</p>}
          {catalog.data?.models.map((model) => (
            <div
              key={`${model.source}:${model.name}`}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-4"
            >
              <div>
                <p className="font-medium">
                  {model.display_name || model.name}
                </p>
                <p className="text-muted-foreground text-sm">
                  {model.source === "managed" && (
                    <>
                      {model.provider === "openai-compatible"
                        ? text.customProvider
                        : (providers.data?.providers.find(
                            (p) => p.id === model.provider,
                          )?.display_name ?? model.provider)}{" "}
                      ·{" "}
                    </>
                  )}
                  {model.model} ·{" "}
                  {model.source === "config"
                    ? text.yaml
                    : model.enabled
                      ? text.enabled
                      : text.disabled}
                </p>
                {model.source === "managed" && model.conflict && (
                  <p role="alert">{text.conflict}</p>
                )}
              </div>
              {model.source === "managed" && (
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    disabled={pending || model.conflict}
                    onClick={() => setEditing(model)}
                  >
                    {text.edit}
                  </Button>
                  <Button
                    variant="outline"
                    disabled={pending || model.conflict}
                    onClick={() => void toggle(model)}
                  >
                    {model.enabled ? text.disable : text.enable}
                  </Button>
                </div>
              )}
            </div>
          ))}
          {editing && (
            <ModelEditor
              key={`${user?.id}:${editing === "new" ? "new" : editing.name}`}
              model={editing === "new" ? undefined : editing}
              close={() => setEditing(null)}
              saved={refresh}
              providers={providers.data?.providers ?? []}
            />
          )}
        </div>
      )}
    </SettingsSection>
  );
}

function ModelEditor({
  model,
  close,
  saved,
  providers,
}: {
  model?: ManagedModel;
  close: () => void;
  saved: () => Promise<void>;
  providers: ManagedModelProvider[];
}) {
  const { t } = useI18n();
  const text = t.settings.models;
  const [draft, setDraft] = useState(() => modelDraft(model));
  const [key, setKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState("");
  const active = useRef(true);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      abort.current?.abort();
    };
  }, []);
  const provider = providers.find((item) => item.id === draft.provider);
  const sameConnection =
    model?.provider === draft.provider &&
    (draft.provider !== "openai-compatible" ||
      model?.base_url === draft.base_url);
  const canKeepKey = sameConnection && model?.has_api_key;
  const requiresKey =
    provider?.requires_api_key ?? draft.provider !== "openai-compatible";
  const missingKey = requiresKey && ((!key.trim() && !canKeepKey) || clearKey);
  function changeProvider(value: string) {
    const rest = { ...draft };
    delete rest.base_url;
    delete rest.reasoning;
    setDraft({
      ...rest,
      provider: value,
      supports_vision: null,
      context_window: null,
      max_tokens: null,
      ...(value === "openai-compatible" ? { base_url: "" } : {}),
    });
    setKey("");
    setClearKey(false);
    setResult("");
    abort.current?.abort();
  }
  function body() {
    return {
      config: {
        ...draft,
        ...(clearKey ? { api_key: "" } : key ? { api_key: key } : {}),
      },
      expected_revision: model?.revision ?? null,
    };
  }
  async function submit(test: boolean) {
    if (missingKey && (test || draft.enabled)) {
      setResult(text.missing_api_key);
      return;
    }
    setPending(true);
    setResult("");
    try {
      if (test) {
        abort.current = new AbortController();
        const response = await testManagedModel(body(), abort.current.signal);
        if (active.current) setResult(text[response.message]);
      } else {
        await saveManagedModel(body());
        await saved();
        if (active.current) {
          toast.success(text.saved);
          close();
        }
      }
    } catch (error) {
      if (active.current) setResult(modelManagementError(error, text));
    } finally {
      if (active.current) setPending(false);
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !pending) close();
      }}
    >
      <DialogContent className="flex h-[90vh] flex-col overflow-hidden">
        <DialogHeader className="shrink-0">
          <DialogTitle>{model ? text.edit : text.add}</DialogTitle>
          <DialogDescription>{text.formDescription}</DialogDescription>
        </DialogHeader>
        <form
          className="flex min-h-0 flex-1 flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            void submit(false);
          }}
        >
          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            <fieldset disabled={pending} className="space-y-3">
              <div className="space-y-1">
                <label id="model-provider-label">{text.provider}</label>
                <Select
                  value={draft.provider}
                  onValueChange={changeProvider}
                  disabled={pending || providers.length === 0}
                >
                  <SelectTrigger
                    aria-labelledby="model-provider-label"
                    className="w-full"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {providers.map((item) => (
                      <SelectItem key={item.id} value={item.id}>
                        {item.custom_endpoint
                          ? text.customProvider
                          : item.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {provider?.custom_endpoint && (
                <label className="block space-y-1">
                  <span>{text.endpoint}</span>
                  <Input
                    type="url"
                    required
                    value={draft.base_url ?? ""}
                    onChange={(e) => {
                      setDraft({ ...draft, base_url: e.target.value });
                      setKey("");
                      setClearKey(false);
                      setResult("");
                    }}
                  />
                </label>
              )}
              {model && !sameConnection && (
                <p role="status">{text.providerChanged}</p>
              )}
              <label className="block space-y-1">
                <span>{text.modelId}</span>
                <Input
                  required
                  maxLength={200}
                  value={draft.model}
                  onChange={(e) => {
                    setDraft({ ...draft, model: e.target.value });
                    setResult("");
                  }}
                />
              </label>
              <label className="block space-y-1">
                <span>{text.apiKey}</span>
                <Input
                  type="password"
                  autoComplete="new-password"
                  disabled={clearKey}
                  required={
                    requiresKey && draft.enabled && !canKeepKey && !clearKey
                  }
                  value={key}
                  placeholder={
                    canKeepKey
                      ? text.keepKey
                      : requiresKey
                        ? text.requiredKey
                        : text.optionalKey
                  }
                  onChange={(e) => {
                    setKey(e.target.value);
                    setResult("");
                  }}
                />
              </label>
              {canKeepKey && (
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={clearKey}
                    onChange={(e) => {
                      setClearKey(e.target.checked);
                      setKey("");
                      setResult("");
                    }}
                  />
                  {text.clearKey}
                </label>
              )}
              <details>
                <summary className="cursor-pointer">{text.advanced}</summary>
                <div className="space-y-3 pt-3">
                  {model && (
                    <label className="block space-y-1">
                      <span>{text.name}</span>
                      <Input value={draft.name} disabled />
                    </label>
                  )}
                  <label className="block space-y-1">
                    <span>{text.displayName}</span>
                    <Input
                      maxLength={100}
                      value={draft.display_name}
                      onChange={(e) =>
                        setDraft({ ...draft, display_name: e.target.value })
                      }
                    />
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={draft.enabled}
                      onChange={(e) => {
                        setDraft({ ...draft, enabled: e.target.checked });
                        setResult("");
                      }}
                    />
                    {text.enabled}
                  </label>
                  <label className="block space-y-1">
                    <span>{text.contextWindow}</span>
                    <Input
                      type="number"
                      min={1}
                      step={1}
                      value={draft.context_window ?? ""}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          context_window: e.target.value
                            ? Number(e.target.value)
                            : null,
                        })
                      }
                    />
                  </label>
                  <label className="block space-y-1">
                    <span>{text.maxTokens}</span>
                    <Input
                      type="number"
                      min={1}
                      step={1}
                      value={draft.max_tokens ?? ""}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          max_tokens: e.target.value
                            ? Number(e.target.value)
                            : null,
                        })
                      }
                    />
                  </label>
                  <div className="space-y-1">
                    <label id="model-vision-label">{text.vision}</label>
                    <Select
                      value={
                        draft.supports_vision === null
                          ? "auto"
                          : String(draft.supports_vision)
                      }
                      onValueChange={(value) => {
                        setDraft({
                          ...draft,
                          supports_vision:
                            value === "auto" ? null : value === "true",
                        });
                        setResult("");
                      }}
                    >
                      <SelectTrigger aria-labelledby="model-vision-label">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="auto">
                          {text.providerDefault}
                        </SelectItem>
                        <SelectItem value="true">{text.enable}</SelectItem>
                        <SelectItem value="false">{text.disable}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </details>
            </fieldset>
          </div>
          {result && (
            <p role="status" className="text-sm">
              {result}
            </p>
          )}
          <DialogFooter className="shrink-0">
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={close}
            >
              {text.cancel}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={
                pending ||
                !provider ||
                !draft.model ||
                missingKey ||
                (provider.custom_endpoint && !draft.base_url)
              }
              onClick={() => void submit(true)}
            >
              {text.test}
            </Button>
            <Button type="submit" disabled={pending || !provider}>
              {pending ? text.working : text.save}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
