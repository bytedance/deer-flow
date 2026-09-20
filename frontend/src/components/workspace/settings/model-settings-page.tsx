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
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { MODELS_QUERY_KEY } from "@/core/models/hooks";
import {
  loadManagedModels,
  modelDraft,
  saveManagedModel,
  testManagedModel,
  type ManagedModel,
} from "@/core/models/management";
import { isStaticWebsiteOnly } from "@/core/static-mode";

import { SettingsSection } from "./settings-section";

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
      toast.error(error instanceof Error ? error.message : text.failed);
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
            <Button disabled={pending} onClick={() => setEditing("new")}>
              {text.add}
            </Button>
            <Button
              variant="outline"
              disabled={pending || catalog.isFetching}
              onClick={() => void catalog.refetch()}
            >
              {text.reload}
            </Button>
          </div>
          {catalog.isLoading && <p role="status">{text.loading}</p>}
          {catalog.error && (
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
}: {
  model?: ManagedModel;
  close: () => void;
  saved: () => Promise<void>;
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
      if (active.current)
        setResult(error instanceof Error ? error.message : text.failed);
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
              <p className="text-sm">{text.provider}: OpenAI compatible</p>
              <label className="block space-y-1">
                <span>{text.name}</span>
                <Input
                  required
                  pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,99}"
                  value={draft.name}
                  disabled={!!model}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
              </label>
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
              <label className="block space-y-1">
                <span>{text.endpoint}</span>
                <Input
                  type="url"
                  required
                  placeholder="https://api.example.com/v1"
                  value={draft.base_url}
                  onChange={(e) => {
                    setDraft({ ...draft, base_url: e.target.value });
                    setResult("");
                  }}
                />
              </label>
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
                <span>API Key</span>
                <Input
                  type="password"
                  autoComplete="new-password"
                  disabled={clearKey}
                  value={key}
                  placeholder={
                    model?.has_api_key ? text.keepKey : text.optionalKey
                  }
                  onChange={(e) => {
                    setKey(e.target.value);
                    setResult("");
                  }}
                />
              </label>
              {model?.has_api_key && (
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
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={draft.supports_vision}
                  onChange={(e) =>
                    setDraft({ ...draft, supports_vision: e.target.checked })
                  }
                />
                {text.vision}
              </label>
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
                pending || !draft.name || !draft.model || !draft.base_url
              }
              onClick={() => void submit(true)}
            >
              {text.test}
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? text.working : text.save}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
