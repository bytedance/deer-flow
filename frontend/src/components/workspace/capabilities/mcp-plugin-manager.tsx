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
import {
  formatMCPServerDefinition,
  MCPServerDefinitionError,
  parseMCPServerDefinition,
} from "@/core/mcp/parse";
import type { MCPServerConfig } from "@/core/mcp/types";
import { env } from "@/env";

import { CapabilityCard, CapabilityIcon } from "./capability-card";

type MCPPluginManagerProps = {
  query?: string;
  children?: ReactNode;
  toolbar?: ReactNode;
};

export function MCPPluginManager(props: MCPPluginManagerProps) {
  const { t } = useI18n();
  const { config, isLoading, error } = useMCPConfig();
  if (isLoading || error) {
    return (
      <div className="space-y-4">
        {props.toolbar}
        {isLoading ? (
          <p role="status" className="text-muted-foreground text-sm">
            {t.common.loading}
          </p>
        ) : (
          <p role="alert" className="text-muted-foreground text-sm">
            {error instanceof MCPConfigRequestError && error.isAdminRequired
              ? t.settings.tools.adminRequired
              : `${t.common.error} ${error?.message}`}
          </p>
        )}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {props.children}
        </div>
      </div>
    );
  }
  return <MCPServerList {...props} servers={config?.mcp_servers} />;
}

function MCPServerList({
  servers,
  query = "",
  children,
  toolbar,
}: MCPPluginManagerProps & {
  servers?: Record<string, MCPServerConfig>;
}) {
  const { t } = useI18n();
  const { isPending, mutate: enableMCPServer } = useEnableMCPServer();
  const { isPending: isWriting, mutate: mutateServer } = useMCPServerMutation();
  const [editor, setEditor] = useState<
    { mode: "add" } | { mode: "edit"; name: string } | null
  >(null);
  const [definition, setDefinition] = useState("");
  const [definitionError, setDefinitionError] = useState<string | null>(null);
  const [pendingRemoval, setPendingRemoval] = useState<string | null>(null);

  const readOnly = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";
  const current = servers ?? {};
  const entries = Object.entries(current).filter(([name, config]) =>
    `${name} ${config.description ?? ""}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );
  const isMutating = isPending || isWriting;

  function displayServerName(name: string | null) {
    return name === null || name.length === 0
      ? t.settings.tools.unnamedServer
      : name;
  }

  function closeEditor() {
    setEditor(null);
    setDefinition("");
    setDefinitionError(null);
  }

  function openAddEditor() {
    setDefinition("");
    setDefinitionError(null);
    setEditor({ mode: "add" });
  }

  function openEditEditor(name: string, config: MCPServerConfig) {
    setDefinition(formatMCPServerDefinition(name, config));
    setDefinitionError(null);
    setEditor({ mode: "edit", name });
  }

  function handleSaveDefinition() {
    if (editor === null) {
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
      <div className="flex flex-wrap items-center justify-between gap-3">
        {toolbar ?? <span />}
        <Button
          size="sm"
          variant="outline"
          disabled={readOnly || isMutating}
          onClick={openAddEditor}
        >
          {t.capabilities.addPlugin}
        </Button>
      </div>

      {entries.length === 0 && !children ? (
        <div className="text-muted-foreground text-sm">
          {query ? t.capabilities.noResults : t.settings.tools.empty}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {children}
          {entries.map(([name, config]) => {
            const displayName = displayServerName(name);
            const actions = (
              <>
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
              </>
            );
            return (
              <CapabilityCard
                key={name}
                name={displayName}
                description={
                  config.description || t.capabilities.mcpDescription
                }
                label={t.capabilities.mcpLabel}
                icon={<CapabilityIcon name={name} />}
                status={
                  <>
                    <span
                      className={
                        config.enabled
                          ? "size-1.5 rounded-full bg-emerald-500"
                          : "bg-muted-foreground/40 size-1.5 rounded-full"
                      }
                    />
                    {config.enabled
                      ? t.capabilities.enabled
                      : t.capabilities.disabled}
                  </>
                }
                onDetails={
                  readOnly || isMutating
                    ? undefined
                    : () => openEditEditor(name, config)
                }
                detailsLabel={`${t.capabilities.details} ${displayName}`}
              >
                {actions}
              </CapabilityCard>
            );
          })}
        </div>
      )}

      <Dialog
        open={editor !== null}
        onOpenChange={(open) => !open && !isWriting && closeEditor()}
      >
        <DialogContent>
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
            <Button disabled={isWriting} onClick={handleSaveDefinition}>
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
