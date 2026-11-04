"use client";

import { Input } from "@/components/ui/input";
import { useI18n } from "@/core/i18n/hooks";
import type {
  ManagedModelProvider,
  ModelConnection,
} from "@/core/models/management";

/** Shared connection fields; destination changes never carry credentials forward. */
export function ModelConnectionFields({
  value,
  providers,
  onChange,
  canKeepKey = false,
  allowClearKey = false,
  requireKey = true,
}: {
  value: ModelConnection;
  providers: ManagedModelProvider[];
  onChange: (value: ModelConnection) => void;
  canKeepKey?: boolean;
  allowClearKey?: boolean;
  requireKey?: boolean;
}) {
  const { t } = useI18n();
  const text = t.settings.models;
  const provider = providers.find((item) => item.id === value.provider);
  const requiresKey =
    provider?.requires_api_key ?? value.provider !== "openai-compatible";
  const clearKey = allowClearKey && canKeepKey && value.api_key === "";
  return (
    <div className="grid min-w-0 gap-3 sm:grid-cols-2">
      <label className="grid min-w-0 gap-1 text-sm">
        {text.provider}
        <select
          className="bg-background h-9 w-full max-w-full min-w-0 rounded border px-2"
          value={value.provider}
          disabled={providers.length === 0}
          onChange={(event) => {
            const next = providers.find(
              (item) => item.id === event.target.value,
            );
            onChange({
              provider: event.target.value,
              ...(next?.custom_endpoint ? { base_url: "" } : {}),
            });
          }}
        >
          {providers.map((item) => (
            <option key={item.id} value={item.id}>
              {item.custom_endpoint ? text.customProvider : item.display_name}
            </option>
          ))}
        </select>
      </label>
      {provider?.custom_endpoint && (
        <label className="grid min-w-0 gap-1 text-sm">
          {text.endpoint}
          <Input
            type="url"
            required
            value={value.base_url ?? ""}
            onChange={(event) =>
              onChange({
                provider: value.provider,
                base_url: event.target.value,
              })
            }
          />
        </label>
      )}
      <label
        className={`grid min-w-0 gap-1 text-sm ${provider?.custom_endpoint ? "sm:col-span-2" : ""}`}
      >
        {text.apiKey}
        <Input
          type="password"
          autoComplete="new-password"
          disabled={clearKey}
          required={requireKey && requiresKey && !canKeepKey && !clearKey}
          value={value.api_key ?? ""}
          placeholder={
            canKeepKey
              ? text.keepKey
              : requiresKey
                ? text.requiredKey
                : text.optionalKey
          }
          onChange={(event) =>
            onChange({ ...value, api_key: event.target.value || undefined })
          }
        />
      </label>
      {allowClearKey && canKeepKey && (
        <label className="flex items-center gap-2 sm:col-span-2">
          <input
            type="checkbox"
            checked={clearKey}
            onChange={(event) =>
              onChange({
                ...value,
                api_key: event.target.checked ? "" : undefined,
              })
            }
          />
          {text.clearKey}
        </label>
      )}
    </div>
  );
}
