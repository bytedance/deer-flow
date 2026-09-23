"use client";

import dynamic from "next/dynamic";
import type { ComponentType } from "react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { capabilityCopy } from "@/core/capabilities/copy";
import { useInstallCapability } from "@/core/capabilities/hooks";
import type { PluginManifest } from "@/core/capabilities/types";
import { useI18n } from "@/core/i18n/hooks";

export type PluginSettingsProps = {
  plugin: PluginManifest;
  onSaved: () => void;
  canManage: boolean;
};
function ConfiguredPluginSettings({
  plugin,
  onSaved,
  canManage,
}: PluginSettingsProps) {
  const { locale } = useI18n();
  const copy = capabilityCopy(locale);
  const install = useInstallCapability();
  const [fields, setFields] = useState<Record<string, string>>({
    name: plugin.id,
  });
  const [error, setError] = useState<string | null>(null);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      let configuration: Record<string, unknown>;
      if (plugin.adapter === "business") {
        configuration = Object.fromEntries(
          Object.entries(fields).filter(([key]) => key !== "name"),
        );
      } else {
        const url = new URL(fields.url ?? "");
        if (
          !["https:", "http:"].includes(url.protocol) ||
          url.username ||
          url.password
        )
          throw new Error(copy.invalidUrl);
        configuration = {
          enabled: true,
          type: "http",
          url: url.toString(),
          description:
            plugin.description[locale] ?? plugin.description["en-US"],
          ...(fields.authorization
            ? { headers: { Authorization: fields.authorization } }
            : {}),
        };
      }
      await install.mutateAsync({
        plugin_id: plugin.id,
        name: fields.name?.trim() ?? "",
        configuration,
      });
      toast.success(copy.saved);
      onSaved();
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    }
  }
  return (
    <form className="space-y-4" onSubmit={(event) => void save(event)}>
      <p className="text-muted-foreground text-sm leading-6">
        {plugin.setup[locale] ?? plugin.setup["en-US"]}
      </p>
      {Object.entries(plugin.config_schema.properties ?? {}).map(
        ([key, schema]) => (
          <div key={key} className="space-y-1.5">
            <label
              htmlFor={`plugin-field-${key}`}
              className="text-sm font-medium"
            >
              {copy[key as keyof typeof copy] ?? schema.title ?? key}
            </label>
            <Input
              id={`plugin-field-${key}`}
              type={schema.format === "password" ? "password" : "text"}
              autoComplete="off"
              required={plugin.config_schema.required?.includes(key)}
              value={fields[key] ?? ""}
              disabled={!canManage || install.isPending}
              onChange={(event) =>
                setFields((previous) => ({
                  ...previous,
                  [key]: event.target.value,
                }))
              }
            />
          </div>
        ),
      )}
      <p className="text-muted-foreground text-xs leading-5">
        {copy.accountHint}
      </p>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      <Button type="submit" disabled={!canManage || install.isPending}>
        {copy.save}
      </Button>
    </form>
  );
}
const LarkSettings = dynamic(() =>
  import("./lark-plugin-settings").then((module) => module.LarkPluginSettings),
);
/** One registration per integration flow, never one conditional per catalog item. */
export const pluginSettingsAdapters: Record<
  string,
  ComponentType<PluginSettingsProps>
> = {
  mcp: ConfiguredPluginSettings,
  business: ConfiguredPluginSettings,
  lark: () => <LarkSettings />,
};
