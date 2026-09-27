"use client";

import { RotateCcwIcon, UploadIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { PluginIconError, preparePluginIcon } from "@/core/mcp/icon";

import { PluginIcon } from "./plugin-icon";

export function PluginIconPicker({
  name,
  asset,
  capabilityId,
  value,
  disabled = false,
  onChange,
  onBusyChange,
}: {
  name: string;
  asset?: string | null;
  capabilityId?: string;
  value?: string | null;
  disabled?: boolean;
  onChange: (value: string | null) => void;
  onBusyChange: (value: boolean) => void;
}) {
  const { t } = useI18n();
  const copy = t.capabilities.icon;
  const input = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(
    () => () => {
      generation.current++;
    },
    [],
  );

  async function upload(file: File) {
    const current = ++generation.current;
    setError(null);
    setBusy(true);
    onBusyChange(true);
    try {
      const icon = await preparePluginIcon(file);
      if (generation.current === current) onChange(icon);
    } catch (error) {
      if (generation.current === current)
        setError(
          error instanceof PluginIconError
            ? copy.errors[error.code]
            : copy.errors.invalid,
        );
    } finally {
      if (generation.current === current) {
        setBusy(false);
        onBusyChange(false);
      }
    }
  }
  function reset() {
    generation.current++;
    setBusy(false);
    onBusyChange(false);
    setError(null);
    onChange(null);
  }
  return (
    <div className="space-y-2">
      <div className="bg-muted/30 flex items-center gap-4 rounded-xl border p-4">
        <button
          type="button"
          aria-label={copy.upload}
          disabled={disabled || busy}
          onClick={() => input.current?.click()}
          className="shrink-0 rounded-xl focus-visible:outline-2 focus-visible:outline-offset-4"
        >
          <PluginIcon
            name={name}
            icon={value}
            asset={asset}
            capabilityId={capabilityId}
            className="size-16"
          />
        </button>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{copy.title}</p>
          <p className="text-muted-foreground mt-1 text-xs leading-5">
            {copy.hint}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={disabled || busy}
              onClick={() => input.current?.click()}
            >
              <UploadIcon className="size-3.5" />
              {busy ? t.common.loading : copy.change}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={disabled || (!value && !busy)}
              onClick={reset}
            >
              <RotateCcwIcon className="size-3.5" />
              {copy.reset}
            </Button>
          </div>
        </div>
      </div>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        aria-label={copy.upload}
        disabled={disabled || busy}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) void upload(file);
        }}
      />
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
    </div>
  );
}
