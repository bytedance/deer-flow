"use client";

import { PencilIcon, Trash2 } from "lucide-react";
import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import { MCPConfigRequestError } from "@/core/mcp/api";
import {
  useEnableMCPServer,
  useMCPConfig,
  useMCPServerMutation,
} from "@/core/mcp/hooks";
import { readPluginIcon, withPluginIcon } from "@/core/mcp/icon";
import {
  formatMCPServerDefinition,
  MCPServerDefinitionError,
  parseMCPServerDefinition,
} from "@/core/mcp/parse";
import type { MCPServerConfig } from "@/core/mcp/types";
import { env } from "@/env";

import {
  catalogForServer,
  type CatalogPlugin,
  type PluginCategory,
} from "./plugin-catalog";
import {
  PluginDirectory,
  PluginRow,
  type PluginDirectoryEntry,
} from "./plugin-directory";
import { PluginIcon } from "./plugin-icon";
import { PluginIconPicker } from "./plugin-icon-picker";

type MCPPluginManagerProps = {
  query?: string;
  catalog?: PluginDirectoryEntry[];
  category?: PluginCategory | "all";
  installedOnly?: boolean;
  toolbar?: ReactNode;
  definitions?: CatalogPlugin[];
};

export function MCPPluginManager(props: MCPPluginManagerProps) {
  const { config, isLoading, error } = useMCPConfig();
  // Keep the directory mounted while MCP discovery completes. Replacing the
  // entire subtree can swallow a click on an independently available plugin.
  return (
    <MCPServerList
      {...props}
      servers={error ? undefined : config?.mcp_servers}
      isLoading={isLoading}
      error={error}
    />
  );
}

function MCPServerList({
  servers,
  query = "",
  catalog = [],
  category = "all",
  installedOnly = false,
  toolbar,
  definitions = [],
  isLoading = false,
  error,
}: MCPPluginManagerProps & {
  servers?: Record<string, MCPServerConfig>;
  isLoading?: boolean;
  error?: Error | null;
}) {
  const { t } = useI18n();
  const { isPending, mutate: enableMCPServer } = useEnableMCPServer();
  const { isPending: isWriting, mutate: mutateServer } = useMCPServerMutation();
  const [editor, setEditor] = useState<
    { mode: "add" } | { mode: "edit"; name: string } | null
  >(null);
  const [definition, setDefinition] = useState("");
  const [draftIcon, setDraftIcon] = useState<string | null | undefined>();
  const [iconBusy, setIconBusy] = useState(false);
  let previewEntries: [string, MCPServerConfig][] = [];
  try {
    previewEntries = Object.entries(parseMCPServerDefinition(definition));
  } catch {
    /* JSON can be incomplete while typing. */
  }
  const previewEntry = previewEntries[0];
  const previewName =
    editor?.mode === "edit" ? editor.name : (previewEntry?.[0] ?? "");
  const previewMetadata = catalogForServer(
    previewName,
    previewEntry?.[1],
    definitions,
  );
  const previewIcon =
    draftIcon === undefined && previewEntry
      ? readPluginIcon(previewEntry[1])
      : draftIcon;
  const [definitionError, setDefinitionError] = useState<string | null>(null);
  const [pendingRemoval, setPendingRemoval] = useState<string | null>(null);

  const readOnly = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";
  const current = servers ?? {};
  const entries = Object.entries(current);
  const isMutating = isPending || isWriting;

  function displayServerName(name: string | null) {
    return name === null || name.length === 0
      ? t.settings.tools.unnamedServer
      : name;
  }

  function closeEditor() {
    setDraftIcon(undefined);
    setIconBusy(false);
    setEditor(null);
    setDefinition("");
    setDefinitionError(null);
  }

  function openAddEditor() {
    setDraftIcon(undefined);
    setIconBusy(false);
    setDefinition("");
    setDefinitionError(null);
    setEditor({ mode: "add" });
  }

  function openEditEditor(name: string, config: MCPServerConfig) {
    setDraftIcon(readPluginIcon(config) ?? null);
    setIconBusy(false);
    setDefinition(
      formatMCPServerDefinition(name, withPluginIcon(config, null)),
    );
    setDefinitionError(null);
    setEditor({ mode: "edit", name });
  }

  function handleSaveDefinition() {
    if (editor === null || iconBusy) {
      return;
    }

    let parsed: Record<string, MCPServerConfig>;
    try {
      parsed = parseMCPServerDefinition(definition);
    } catch (parseError) {
      if (parseError instanceof MCPServerDefinitionError) {
        const messages = {
          emptyDefinition: t.settings.tools.definitionEmpty,
          invalidJson: t.settings.tools.definitionInvalidJson,
          rootNotObject: t.settings.tools.definitionRootNotObject,
          emptyServerMap: t.settings.tools.definitionNoServers,
          serverConfigNotObject:
            t.settings.tools.definitionServerNotObject.replace(
              "{name}",
              parseError.serverName ?? "",
            ),
        };
        setDefinitionError(messages[parseError.code]);
      } else {
        setDefinitionError(t.settings.tools.definitionInvalidJson);
      }
      return;
    }

    if (draftIcon !== undefined) {
      const entries = Object.entries(parsed);
      if (entries.length !== 1) {
        setDefinitionError(
          editor.mode === "edit"
            ? t.settings.tools.editSingleServer
            : t.capabilities.icon.singleServer,
        );
        return;
      }
      const [name, config] = entries[0]!;
      parsed = { [name]: withPluginIcon(config, draftIcon) };
    }

    if (editor.mode === "add") {
      const duplicate = Object.keys(parsed).find((name) =>
        Object.hasOwn(current, name),
      );
      if (duplicate !== undefined) {
        setDefinitionError(
          t.settings.tools.serverAlreadyExists.replace("{name}", duplicate),
        );
        return;
      }
      setDefinitionError(null);
      mutateServer(
        { operation: "create", servers: parsed },
        { onSuccess: closeEditor },
      );
    } else {
      const editedEntries = Object.entries(parsed);
      if (editedEntries.length !== 1) {
        setDefinitionError(t.settings.tools.editSingleServer);
        return;
      }
      const [editedName, editedConfig] = editedEntries[0]!;
      if (editedName !== editor.name) {
        setDefinitionError(
          t.settings.tools.editServerNameMismatch.replace(
            "{name}",
            editor.name,
          ),
        );
        return;
      }
      setDefinitionError(null);
      mutateServer(
        {
          operation: "update",
          serverName: editor.name,
          server: editedConfig,
        },
        { onSuccess: closeEditor },
      );
    }
  }

  function handleRemove(name: string) {
    mutateServer(
      { operation: "delete", serverName: name },
      { onSuccess: () => setPendingRemoval(null) },
    );
  }

  return (
    <div className="flex w-full flex-col gap-4">
      <div className="flex min-h-9 flex-wrap items-center justify-between gap-3">
        {toolbar ?? <span />}
        {isLoading && (
          <p role="status" className="text-muted-foreground text-sm">
            {t.common.loading}
          </p>
        )}
        {!isLoading && !error && (
          <Button
            size="sm"
            variant="outline"
            disabled={readOnly || isMutating}
            onClick={openAddEditor}
          >
            {t.capabilities.addPlugin}
          </Button>
        )}
      </div>

      {error && (
        <p role="alert" className="text-muted-foreground text-sm">
          {error instanceof MCPConfigRequestError && error.isAdminRequired
            ? t.settings.tools.adminRequired
            : `${t.common.error} ${error.message}`}
        </p>
      )}
      <PluginDirectory
        query={query}
        category={category}
        installedOnly={installedOnly}
        entries={[
          ...catalog.filter(
            (item) =>
              !entries.some(
                ([name, server]) =>
                  catalogForServer(name, server, definitions)?.id === item.id,
              ),
          ),
          ...entries.map(([name, config]): PluginDirectoryEntry => {
            const displayName = displayServerName(name);
            const metadata = catalogForServer(name, config, definitions);
            return {
              id: `mcp:${name}`,
              category: metadata?.category ?? "custom",
              search: `${name} ${config.description ?? ""} ${metadata?.aliases.join(" ") ?? ""} ${Object.values(metadata?.name ?? {}).join(" ")} ${Object.values(metadata?.description ?? {}).join(" ")}`,
              installed: true,
              node: (
                <PluginRow
                  name={displayName}
                  description={
                    config.description || t.capabilities.mcpDescription
                  }
                  label={
                    config.enabled
                      ? t.capabilities.enabled
                      : t.capabilities.disabled
                  }
                  icon={
                    <PluginIcon
                      name={name}
                      icon={readPluginIcon(config)}
                      asset={metadata?.icon}
                      capabilityId={metadata?.id}
                    />
                  }
                  onDetails={
                    readOnly || isMutating
                      ? undefined
                      : () => openEditEditor(name, config)
                  }
                  detailsLabel={`${t.capabilities.details} ${displayName}`}
                >
                  <Switch
                    checked={config.enabled}
                    aria-label={`${t.capabilities.enabled} ${displayName}`}
                    disabled={readOnly || isMutating}
                    onCheckedChange={(checked) =>
                      enableMCPServer({ serverName: name, enabled: checked })
                    }
                  />
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={`${t.common.edit} ${displayName}`}
                    disabled={readOnly || isMutating}
                    onClick={() => openEditEditor(name, config)}
                  >
                    <PencilIcon className="size-4" />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={`${t.common.delete} ${displayName}`}
                    disabled={readOnly || isMutating}
                    onClick={() => setPendingRemoval(name)}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </PluginRow>
              ),
            };
          }),
        ]}
      />

      <Dialog
        open={editor !== null}
        onOpenChange={(open) => !open && !isWriting && closeEditor()}
      >
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>
              {editor?.mode === "edit"
                ? t.settings.tools.editServer
                : t.settings.tools.addServer}
            </DialogTitle>
            <DialogDescription>
              {editor?.mode === "edit"
                ? t.settings.tools.editServerDescription.replace(
                    "{name}",
                    editor.name,
                  )
                : t.settings.tools.addServerDescription}
            </DialogDescription>
          </DialogHeader>
          <PluginIconPicker
            name={previewName}
            asset={previewMetadata?.icon}
            capabilityId={previewMetadata?.id}
            value={previewIcon}
            disabled={isWriting || previewEntries.length > 1}
            onChange={setDraftIcon}
            onBusyChange={setIconBusy}
          />
          {previewEntries.length > 1 && (
            <p className="text-muted-foreground text-xs">
              {t.capabilities.icon.singleServer}
            </p>
          )}
          <Textarea
            className="min-h-52 font-mono text-xs"
            aria-label={t.settings.tools.serverDefinitionLabel}
            spellCheck={false}
            value={definition}
            placeholder={t.settings.tools.addServerPlaceholder}
            onChange={(event) => setDefinition(event.target.value)}
          />
          {definitionError && (
            <div className="text-destructive text-sm" role="alert">
              {definitionError}
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={isWriting}
              onClick={closeEditor}
            >
              {t.common.cancel}
            </Button>
            <Button
              disabled={isWriting || iconBusy}
              onClick={handleSaveDefinition}
            >
              {isWriting ? t.common.loading : t.common.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={pendingRemoval !== null}
        onOpenChange={(open) => !open && setPendingRemoval(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.settings.tools.removeServer}</DialogTitle>
            <DialogDescription>
              {t.settings.tools.removeServerDescription.replace(
                "{name}",
                displayServerName(pendingRemoval),
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={isWriting}
              onClick={() => setPendingRemoval(null)}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              disabled={isWriting}
              onClick={() =>
                pendingRemoval !== null && handleRemove(pendingRemoval)
              }
            >
              {isWriting ? t.common.loading : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
