"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import {
  deleteProviderKey,
  getProviderKeyStatus,
  getUserModelPreferences,
  setProviderKey,
  setUserModelPreferences,
} from "@/core/models/api";
import { useProviderCatalog, useValidateProviderKey } from "@/core/models/hooks";
import type { ProviderId, ProviderModel } from "@/core/models/types";
import { useLocalSettings } from "@/core/settings";
import { getLocalSettings } from "@/core/settings/local";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

const FALLBACK_PROVIDER_LABELS: Record<
  ProviderId,
  { title: string; description: string }
> = {
  openai: {
    title: "OpenAI",
    description: "OpenAI API models.",
  },
  anthropic: {
    title: "Anthropic",
    description: "Claude models from Anthropic.",
  },
  gemini: {
    title: "Gemini",
    description: "Google Gemini API models.",
  },
  deepseek: {
    title: "DeepSeek",
    description: "DeepSeek chat and reasoning models.",
  },
  kimi: {
    title: "Kimi",
    description: "Moonshot Kimi models.",
  },
  zai: {
    title: "Z.ai",
    description: "Z.ai GLM models.",
  },
  minimax: {
    title: "Minimax",
    description: "MiniMax M2 series models.",
  },
  "epfl-rcp": {
    title: "EPFL RCP AIaaS",
    description: "EPFL RCP AI Inference-as-a-Service (OpenAI-compatible).",
  },
};
const SETTINGS_SYNC_POLL_MS = 2500;

function normalizeBoolMap(
  value: Record<string, boolean> | null | undefined,
): Record<string, boolean> {
  if (!value) {
    return {};
  }
  const entries = Object.entries(value)
    .filter(([key]) => key.trim().length > 0)
    .map(([key, enabled]) => [key.trim(), Boolean(enabled)] as const)
    .sort(([a], [b]) => a.localeCompare(b));
  return Object.fromEntries(entries);
}

function modelSettingsSignature(payload: {
  provider_enabled: Record<string, boolean>;
  enabled_models: Record<string, boolean>;
}) {
  return JSON.stringify({
    provider_enabled: normalizeBoolMap(payload.provider_enabled),
    enabled_models: normalizeBoolMap(payload.enabled_models),
  });
}

export function ModelSettingsPage() {
  const { t } = useI18n();
  const [settings, setSettings] = useLocalSettings();
  const {
    providers: catalogProviders,
    isLoading,
    error,
  } = useProviderCatalog();
  const appliedDefaultsRef = useRef(false);
  const lastSyncedSignatureRef = useRef("");

  useEffect(() => {
    if (appliedDefaultsRef.current || catalogProviders.length === 0) {
      return;
    }
    appliedDefaultsRef.current = true;
    const latest = getLocalSettings();
    const hasAnyEnabled = Object.values(latest.models.providers).some(
      (provider) => provider.enabled,
    );
    if (hasAnyEnabled) {
      return;
    }
    const updates: Partial<typeof latest.models.providers> = {};
    for (const provider of catalogProviders) {
      if (!provider.enabled_by_default) {
        continue;
      }
      updates[provider.id] = {
        ...latest.models.providers[provider.id],
        enabled: true,
      };
    }
    if (Object.keys(updates).length === 0) {
      return;
    }
    setSettings("models", {
      providers: {
        ...latest.models.providers,
        ...updates,
      },
      enabled_models: latest.models.enabled_models,
    });
  }, [catalogProviders, setSettings]);

  const providers = useMemo(
    () =>
      catalogProviders.map((provider) => {
        const fallback = FALLBACK_PROVIDER_LABELS[provider.id];
        return {
          ...provider,
          title: provider.display_name ?? fallback?.title ?? provider.id,
          description:
            provider.description ?? fallback?.description ?? "",
          config: settings.models.providers[provider.id],
        };
      }),
    [catalogProviders, settings.models.providers],
  );

  const localModelSettingsPayload = useMemo(() => {
    const providerEnabled = providers.reduce(
      (acc, provider) => {
        acc[provider.id] = Boolean(settings.models.providers[provider.id]?.enabled);
        return acc;
      },
      {} as Record<string, boolean>,
    );
    return {
      provider_enabled: providerEnabled,
      enabled_models: settings.models.enabled_models ?? {},
    };
  }, [providers, settings.models.enabled_models, settings.models.providers]);

  useEffect(() => {
    let cancelled = false;
    const applyRemote = async () => {
      try {
        const remote = await getUserModelPreferences();
        if (cancelled) {
          return;
        }
        const remotePayload = {
          provider_enabled: normalizeBoolMap(remote.provider_enabled ?? undefined),
          enabled_models: normalizeBoolMap(remote.enabled_models ?? undefined),
        };
        const remoteSignature = modelSettingsSignature(remotePayload);
        if (remoteSignature === lastSyncedSignatureRef.current) {
          return;
        }
        const latest = getLocalSettings();
        const mergedProviders = { ...latest.models.providers };
        for (const [providerId, enabled] of Object.entries(remotePayload.provider_enabled)) {
          if (providerId in mergedProviders) {
            mergedProviders[providerId as ProviderId] = {
              ...mergedProviders[providerId as ProviderId],
              enabled,
            };
          }
        }
        setSettings("models", {
          providers: mergedProviders,
          enabled_models: {
            ...latest.models.enabled_models,
            ...remotePayload.enabled_models,
          },
        });
        lastSyncedSignatureRef.current = remoteSignature;
      } catch {
        // Keep local settings when remote sync fails.
      }
    };

    void applyRemote();
    const interval = setInterval(() => {
      void applyRemote();
    }, SETTINGS_SYNC_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [setSettings]);

  useEffect(() => {
    const payload = {
      provider_enabled: normalizeBoolMap(localModelSettingsPayload.provider_enabled),
      enabled_models: normalizeBoolMap(localModelSettingsPayload.enabled_models),
    };
    const signature = modelSettingsSignature(payload);
    if (signature === lastSyncedSignatureRef.current) {
      return;
    }
    const timeout = setTimeout(() => {
      void setUserModelPreferences(payload)
        .then((saved) => {
          lastSyncedSignatureRef.current = modelSettingsSignature({
            provider_enabled: normalizeBoolMap(saved.provider_enabled ?? undefined),
            enabled_models: normalizeBoolMap(saved.enabled_models ?? undefined),
          });
        })
        .catch(() => {
          // Retry on next local change or polling cycle.
        });
    }, 350);
    return () => {
      clearTimeout(timeout);
    };
  }, [localModelSettingsPayload]);

  return (
    <SettingsSection
      title={t.settings.models.title}
      description={t.settings.models.description}
    >
      <div className="flex w-full flex-col gap-4">
        {isLoading && (
          <div className="text-muted-foreground text-sm">{t.common.loading}</div>
        )}
        {error instanceof Error && (
          <div className="text-sm text-rose-500">{error.message}</div>
        )}
        {!isLoading &&
          providers.map((provider) => (
            <ProviderSection
              key={provider.id}
              providerId={provider.id}
              providerTitle={provider.title}
              providerDescription={provider.description}
              providerRequiresApiKey={provider.requires_api_key}
              providerModels={provider.models}
              providerConfig={provider.config}
              setSettings={setSettings}
            />
          ))}
      </div>
    </SettingsSection>
  );
}

function ProviderSection({
  providerId,
  providerTitle,
  providerDescription,
  providerRequiresApiKey,
  providerModels,
  providerConfig,
  setSettings,
}: {
  providerId: ProviderId;
  providerTitle: string;
  providerDescription: string;
  providerRequiresApiKey: boolean;
  providerModels: ProviderModel[];
  providerConfig: {
    enabled: boolean;
    has_key: boolean;
    api_key?: string;
    last_validated_at?: string;
    last_validation_status?: "valid" | "invalid" | "unknown";
    last_validation_message?: string;
  };
  setSettings: ReturnType<typeof useLocalSettings>[1];
}) {
  const { t } = useI18n();
  const legacyKeyUploadedRef = useRef(false);
  const [pendingKey, setPendingKey] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const validationMutation = useValidateProviderKey();

  const updateProvider = useCallback(
    (updates: Partial<typeof providerConfig>) => {
      const latest = getLocalSettings();
      const latestProviders = latest.models.providers;
      const currentProvider =
        latestProviders[providerId] ?? providerConfig ?? { enabled: false, has_key: false };
      setSettings("models", {
        providers: {
          ...latestProviders,
          [providerId]: {
            ...currentProvider,
            ...updates,
          },
        },
        enabled_models: latest.models.enabled_models,
      });
    },
    [providerConfig, providerId, setSettings],
  );

  const handleProviderToggle = useCallback(
    (enabled: boolean) => {
      updateProvider({ enabled });
    },
    [updateProvider],
  );

  const handleValidate = useCallback(async () => {
    setIsSaving(true);
    try {
      if (pendingKey.trim()) {
        await setProviderKey(providerId, pendingKey.trim());
        setPendingKey("");
        updateProvider({ has_key: true });
      }
      const result = await validationMutation.mutateAsync({
        provider: providerId,
      });
      updateProvider({
        has_key: true,
        last_validated_at: new Date().toISOString(),
        last_validation_status: result.valid ? "valid" : "invalid",
        last_validation_message: result.message,
      });
    } finally {
      setIsSaving(false);
    }
  }, [pendingKey, providerId, updateProvider, validationMutation]);

  const handleRemoveKey = useCallback(async () => {
    setIsSaving(true);
    try {
      await deleteProviderKey(providerId);
      updateProvider({
        has_key: false,
        last_validated_at: undefined,
        last_validation_status: "unknown",
        last_validation_message: undefined,
      });
    } finally {
      setIsSaving(false);
    }
  }, [providerId, updateProvider]);

  useEffect(() => {
    if (legacyKeyUploadedRef.current) {
      return;
    }
    const legacyKey = providerConfig.api_key?.trim();
    if (!legacyKey) {
      return;
    }
    legacyKeyUploadedRef.current = true;
    setProviderKey(providerId, legacyKey)
      .then(() => {
        updateProvider({
          api_key: undefined,
          has_key: true,
        });
      })
      .catch(() => {
        legacyKeyUploadedRef.current = false;
      });
  }, [providerConfig.api_key, providerId, updateProvider]);

  useEffect(() => {
    if (!providerConfig.enabled) {
      return;
    }
    getProviderKeyStatus(providerId)
      .then((status) => {
        updateProvider({ has_key: status.has_key });
      })
      .catch(() => {
        // Keep last known key status if request fails.
      });
  }, [providerConfig.enabled, providerId, updateProvider]);

  return (
    <Item className="w-full" variant="outline">
      <ItemContent>
        <ItemTitle className="flex items-center justify-between gap-3">
          <span>{providerTitle}</span>
          <Switch
            checked={providerConfig.enabled}
            disabled={env.VITE_STATIC_WEBSITE_ONLY === "true"}
            onCheckedChange={handleProviderToggle}
          />
        </ItemTitle>
        <ItemDescription>{providerDescription}</ItemDescription>
        {providerConfig.enabled && (
          <div className="mt-4 flex w-full flex-col gap-3">
            {providerRequiresApiKey && (
              <div className="flex flex-col gap-2">
                <label className="text-sm font-medium">{t.settings.models.apiKeyLabel}</label>
                <div className="flex flex-col gap-2 md:flex-row">
                  <Input
                    value={pendingKey}
                    type="password"
                    placeholder={t.settings.models.apiKeyPlaceholder}
                    onChange={(event) => setPendingKey(event.target.value)}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    className="md:w-40"
                    disabled={
                      validationMutation.isPending ||
                      isSaving ||
                      (!pendingKey.trim() && !providerConfig.has_key) ||
                      env.VITE_STATIC_WEBSITE_ONLY === "true"
                    }
                    onClick={handleValidate}
                  >
                    {t.settings.models.validate}
                  </Button>
                  {providerConfig.has_key && (
                    <Button
                      type="button"
                      variant="ghost"
                      className="md:w-32"
                      disabled={isSaving || env.VITE_STATIC_WEBSITE_ONLY === "true"}
                      onClick={handleRemoveKey}
                    >
                      {t.common.remove}
                    </Button>
                  )}
                </div>
                {providerConfig.has_key && (
                  <div className="text-muted-foreground text-xs">
                    {t.settings.models.apiKeyStored}
                  </div>
                )}
                {providerConfig.last_validation_message && (
                  <div
                    className={cn(
                      "text-xs",
                      providerConfig.last_validation_status === "valid"
                        ? "text-emerald-600"
                        : "text-rose-500",
                    )}
                  >
                    {providerConfig.last_validation_message}
                  </div>
                )}
              </div>
            )}
            <ProviderModelsList models={providerModels} />
          </div>
        )}
      </ItemContent>
    </Item>
  );
}

function ProviderModelsList({
  models,
}: {
  models: ProviderModel[];
}) {
  const { t } = useI18n();
  const [settings, setSettings] = useLocalSettings();
  const enabledModels = settings.models.enabled_models;

  const toggleModel = useCallback(
    (modelId: string, enabled: boolean) => {
      const latest = getLocalSettings();
      const latestEnabledModels = latest.models.enabled_models ?? {};
      setSettings("models", {
        providers: latest.models.providers,
        enabled_models: {
          ...latestEnabledModels,
          [modelId]: enabled,
        },
      });
    },
    [setSettings],
  );

  if (models.length === 0) {
    return (
      <div className="text-muted-foreground text-sm">
        {t.settings.models.noModelsHint}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="text-sm font-medium">{t.settings.models.modelsLabel}</div>
      <div className="flex flex-col gap-2">
        {models.map((model) => {
          const enabled = enabledModels[model.id] ?? true;
          return (
            <Item key={model.id} className="w-full border border-border/50">
              <ItemContent>
                <ItemTitle className="text-sm">{model.display_name}</ItemTitle>
                {model.tier_label && (
                  <ItemDescription className="text-xs">
                    {model.tier_label}
                  </ItemDescription>
                )}
              </ItemContent>
              <div className="flex items-center">
                <Switch
                  checked={enabled}
                  onCheckedChange={(checked) => toggleModel(model.id, checked)}
                />
              </div>
            </Item>
          );
        })}
      </div>
    </div>
  );
}

