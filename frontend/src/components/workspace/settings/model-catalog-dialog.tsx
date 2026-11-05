"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { GatewayApiError } from "@/core/api/errors";
import { useI18n } from "@/core/i18n/hooks";
import {
  discoverModels,
  importCatalogModel,
  type CatalogModel,
  type ManagedModel,
  type ManagedModelProvider,
  type ModelConnection,
} from "@/core/models/management";

import { ModelConnectionFields } from "./model-connection-fields";

export function ModelCatalogDialog({
  models,
  providers,
  close,
  saved,
}: {
  models: ManagedModel[];
  providers: ManagedModelProvider[];
  close: () => void;
  saved: () => Promise<void>;
}) {
  const { t } = useI18n();
  const text = t.settings.models;
  const [connectionOpen, setConnectionOpen] = useState(true);
  const [connection, setConnection] = useState<ModelConnection>({
    provider: "openai",
  });
  const source = connection.saved_model_name ?? "";
  const [catalog, setCatalog] = useState<CatalogModel[] | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [results, setResults] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const operation = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      operation.current?.abort();
    };
  }, []);
  const provider = providers.find((item) => item.id === connection.provider);
  const valid =
    !!provider &&
    (!provider.custom_endpoint || !!connection.base_url) &&
    (!provider.requires_api_key ||
      !!connection.api_key?.trim() ||
      !!connection.saved_model_name);
  const visible =
    catalog?.filter((item) =>
      item.id.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
    ) ?? [];
  const pendingIds = selected.filter(
    (id) => !catalog?.find((item) => item.id === id)?.configured,
  );
  function change(next: ModelConnection) {
    setConnection(next);
    setCatalog(null);
    setSelected([]);
    setResults({});
    setMessage("");
    setProgress("");
  }
  function errorText(error: unknown) {
    if (error instanceof GatewayApiError) {
      if (error.status === 409) return text.revisionConflict;
      if (error.code === "authentication_failed")
        return text.authentication_failed;
      if (error.code === "missing_api_key") return text.missing_api_key;
      if (error.code === "discovery_unsupported")
        return text.discovery_unsupported;
      if (error.code === "response_limit") return text.response_limit;
    }
    return text.discovery_failed;
  }
  async function discover() {
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true);
    setCatalog(null);
    setSelected([]);
    setResults({});
    setMessage("");
    setProgress("");
    try {
      const result = await discoverModels(connection, controller.signal);
      if (mounted.current && !controller.signal.aborted) {
        setCatalog(result.models);
        setConnectionOpen(false);
        setTruncated(result.truncated);
      }
    } catch (error) {
      if (mounted.current && !controller.signal.aborted)
        setMessage(errorText(error));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  async function importSelected() {
    const controller = new AbortController();
    operation.current = controller;
    const ids = [...pendingIds];
    setBusy(true);
    setMessage("");
    try {
      for (const [index, id] of ids.entries()) {
        if (controller.signal.aborted || !mounted.current) break;
        setProgress(`${index + 1} / ${ids.length} · ${id}`);
        setResults((previous) => ({ ...previous, [id]: text.working }));
        try {
          const result = await importCatalogModel(
            connection,
            id,
            controller.signal,
          );
          if (!mounted.current || controller.signal.aborted) break;
          setResults((previous) => ({
            ...previous,
            [id]:
              result.status === "failed"
                ? text[result.message]
                : result.status === "existing"
                  ? text.alreadyConfigured
                  : text.saved,
          }));
          if (result.status !== "failed") {
            setCatalog(
              (previous) =>
                previous?.map((item) =>
                  item.id === id ? { ...item, configured: true } : item,
                ) ?? null,
            );
            setSelected((previous) => previous.filter((name) => name !== id));
          }
        } catch (error) {
          if (!mounted.current || controller.signal.aborted) break;
          setResults((previous) => ({
            ...previous,
            [id]:
              error instanceof GatewayApiError
                ? errorText(error)
                : text.importUncertain,
          }));
        }
      }
    } finally {
      // A cancelled HTTP response may already have committed. Refresh even on dismissal;
      // importing again checks the server catalog before probing or writing.
      await saved().catch(() => undefined);
      if (mounted.current) {
        setBusy(false);
        setProgress("");
        if (controller.signal.aborted) {
          setMessage(text.importStopped);
          setResults((previous) =>
            Object.fromEntries(
              Object.entries(previous).map(([id, result]) => [
                id,
                result === text.working ? text.importUncertain : result,
              ]),
            ),
          );
        }
      }
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent className="flex h-[90vh] max-w-2xl flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle>{text.importTitle}</DialogTitle>
          <DialogDescription>{text.importDescription}</DialogDescription>
        </DialogHeader>
        <details
          open={connectionOpen}
          onToggle={(event) => setConnectionOpen(event.currentTarget.open)}
          className="min-w-0 shrink-0"
        >
          <summary className="cursor-pointer text-sm font-medium">
            {text.connectionSettings} ·{" "}
            {provider?.custom_endpoint
              ? text.customProvider
              : provider?.display_name}
          </summary>
          <fieldset disabled={busy} className="mt-3 grid min-w-0 gap-3">
            {models.length > 0 && (
              <label className="grid min-w-0 gap-1 text-sm">
                {text.savedConnection}
                <select
                  className="bg-background h-9 w-full max-w-full min-w-0 rounded border px-2"
                  value={source}
                  onChange={(event) => {
                    const model = models.find(
                      (item) => item.name === event.target.value,
                    );
                    change(
                      model
                        ? {
                            provider: model.provider,
                            ...(model.base_url
                              ? { base_url: model.base_url }
                              : {}),
                            saved_model_name: model.name,
                            expected_revision: model.revision,
                          }
                        : { provider: "openai" },
                    );
                  }}
                >
                  <option value="">{text.newConnection}</option>
                  {models
                    .filter(
                      (model) =>
                        model.has_api_key ||
                        model.provider === "openai-compatible",
                    )
                    .map((model) => (
                      <option key={model.name} value={model.name}>
                        {model.display_name || model.model}
                      </option>
                    ))}
                </select>
              </label>
            )}
            <ModelConnectionFields
              value={connection}
              providers={providers}
              canKeepKey={
                !!models.find((model) => model.name === source)?.has_api_key
              }
              onChange={change}
            />
            <Button
              variant="outline"
              disabled={!valid || busy}
              onClick={() => void discover()}
            >
              {text.fetchModels}
            </Button>
          </fieldset>
        </details>
        {message && (
          <p role="status" className="text-sm">
            {message}
          </p>
        )}
        {catalog && (
          <>
            <div className="shrink-0 space-y-2">
              <Input
                aria-label={text.searchModels}
                placeholder={text.searchModels}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span>
                  {text.catalogCount(
                    visible.length,
                    catalog.length,
                    pendingIds.length,
                  )}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() =>
                    setSelected([
                      ...new Set([
                        ...selected,
                        ...visible
                          .filter((item) => !item.configured)
                          .map((item) => item.id),
                      ]),
                    ])
                  }
                >
                  {text.selectVisible}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => setSelected([])}
                >
                  {text.clearSelection}
                </Button>
              </div>
              {truncated && (
                <p role="status" className="text-sm">
                  {text.catalogTruncated}
                </p>
              )}
            </div>
            <div className="min-h-0 flex-1 overflow-auto rounded border">
              {visible.length === 0 && (
                <p className="p-4 text-sm">{text.noCatalogResults}</p>
              )}
              {visible.map((item) => (
                <label
                  key={item.id}
                  className="flex items-start gap-3 border-b p-3 text-sm last:border-b-0"
                >
                  <input
                    type="checkbox"
                    className="mt-1"
                    disabled={busy || item.configured}
                    checked={selected.includes(item.id) || item.configured}
                    onChange={(event) =>
                      setSelected((previous) =>
                        event.target.checked
                          ? [...previous, item.id]
                          : previous.filter((id) => id !== item.id),
                      )
                    }
                  />
                  <span className="min-w-0 flex-1 break-all">
                    <span>{item.id}</span>
                    {(results[item.id] ?? item.configured) && (
                      <span className="text-muted-foreground block text-xs">
                        {results[item.id] ?? text.alreadyConfigured}
                      </span>
                    )}
                  </span>
                </label>
              ))}
            </div>
          </>
        )}
        {progress && (
          <p role="status" className="shrink-0 truncate text-sm">
            {progress}
          </p>
        )}
        <div className="mt-auto flex shrink-0 justify-end gap-2">
          {busy ? (
            <Button
              variant="outline"
              onClick={() => operation.current?.abort()}
            >
              {text.stopImport}
            </Button>
          ) : (
            <Button variant="outline" onClick={close}>
              {text.closeCatalog}
            </Button>
          )}
          <Button
            disabled={busy || !pendingIds.length}
            onClick={() => void importSelected()}
          >
            {text.testAndAdd(pendingIds.length)}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
