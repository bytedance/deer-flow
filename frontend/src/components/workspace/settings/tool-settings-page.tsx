"use client";

import { PencilIcon, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { MCPConfigRequestError } from "@/core/mcp/api";
import {
  useEnableMCPServer,
  useMCPConfig,
  useUpdateMCPConfig,
} from "@/core/mcp/hooks";
import {
  formatMCPServerDefinition,
  parseMCPServerDefinition,
} from "@/core/mcp/parse";
import type { MCPServerConfig } from "@/core/mcp/types";
import { env } from "@/env";

import { SettingsSection } from "./settings-section";

export function ToolSettingsPage() {
  const { t } = useI18n();
  const { config, isLoading, error } = useMCPConfig();
  const adminRequired =
    error instanceof MCPConfigRequestError && error.isAdminRequired;
  return (
    <SettingsSection
      title={t.settings.tools.title}
      description={t.settings.tools.description}
    >
      {isLoading ? (
        <div className="text-muted-foreground text-sm">{t.common.loading}</div>
      ) : adminRequired ? (
        <div className="text-muted-foreground text-sm">
          {t.settings.tools.adminRequired}
        </div>
      ) : error ? (
        <div>Error: {error.message}</div>
      ) : (
        config && <MCPServerList servers={config.mcp_servers} />
      )}
    </SettingsSection>
  );
}

function MCPServerList({
  servers,
}: {
  servers?: Record<string, MCPServerConfig>;
}) {
  const { t } = useI18n();
  const { isPending, mutate: enableMCPServer } = useEnableMCPServer();
  const { isPending: isWriting, mutate: updateConfig } = useUpdateMCPConfig();
  const [editor, setEditor] = useState<
    { mode: "add" } | { mode: "edit"; name: string } | null
  >(null);
  const [definition, setDefinition] = useState("");
  const [definitionError, setDefinitionError] = useState<string | null>(null);
  const [pendingRemoval, setPendingRemoval] = useState<string | null>(null);

  const readOnly = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";
  const current = servers ?? {};
  const entries = Object.entries(current);
  const isMutating = isPending || isWriting;

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
      setDefinitionError(
        parseError instanceof Error ? parseError.message : String(parseError),
      );
      return;
    }

    let next: Record<string, MCPServerConfig>;
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
      next = { ...current, ...parsed };
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
      next = { ...current, [editor.name]: editedConfig };
    }

    setDefinitionError(null);
    // PUT replaces the whole map, so the existing servers ride along
    // untouched — including fields this page never renders.
    updateConfig(
      { mcp_servers: next },
      {
        onSuccess: closeEditor,
      },
    );
  }

  function handleRemove(name: string) {
    const next = { ...current };
    delete next[name];
    updateConfig(
      { mcp_servers: next },
      { onSuccess: () => setPendingRemoval(null) },
    );
  }

  return (
    <div className="flex w-full flex-col gap-4">
      <div className="flex justify-end">
        <Button
          size="sm"
          variant="outline"
          disabled={readOnly || isMutating}
          onClick={openAddEditor}
        >
          {t.settings.tools.addServer}
        </Button>
      </div>

      {entries.length === 0 ? (
        <div className="text-muted-foreground text-sm">
          {t.settings.tools.empty}
        </div>
      ) : (
        entries.map(([name, config]) => (
          <Item className="w-full" variant="outline" key={name}>
            <ItemContent>
              <ItemTitle>
                <div className="flex items-center gap-2">
                  <div>{name}</div>
                </div>
              </ItemTitle>
              <ItemDescription className="line-clamp-4">
                {config.description}
              </ItemDescription>
            </ItemContent>
            <ItemActions className="gap-1">
              <Switch
                checked={config.enabled}
                disabled={readOnly || isMutating}
                onCheckedChange={(checked) =>
                  enableMCPServer({ serverName: name, enabled: checked })
                }
              />
              <Button
                size="icon"
                variant="ghost"
                aria-label={`${t.common.edit} ${name}`}
                disabled={readOnly || isMutating}
                onClick={() => openEditEditor(name, config)}
              >
                <PencilIcon className="size-4" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                aria-label={`${t.common.delete} ${name}`}
                disabled={readOnly || isMutating}
                onClick={() => setPendingRemoval(name)}
              >
                <Trash2 className="size-4" />
              </Button>
            </ItemActions>
          </Item>
        ))
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
            spellCheck={false}
            value={definition}
            placeholder={t.settings.tools.addServerPlaceholder}
            onChange={(event) => setDefinition(event.target.value)}
          />
          {definitionError && (
            <div className="text-destructive text-sm">{definitionError}</div>
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
                pendingRemoval ?? "",
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
              onClick={() => pendingRemoval && handleRemove(pendingRemoval)}
            >
              {isWriting ? t.common.loading : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
