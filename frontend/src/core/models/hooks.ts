import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";

import { useLocalSettings } from "../settings";
import { getLocalSettings } from "../settings/local";

import { getProviderKeyStatus, loadProviderCatalog, validateProviderKey } from "./api";
import type { ProviderCatalog, ProviderId, ProviderModel, RuntimeModelSpec } from "./types";

const CATALOG_QUERY_OPTIONS = {
  staleTime: Infinity,
  gcTime: Infinity,
  retry: false,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
  refetchOnMount: false,
} as const;

export function useProviderCatalog({ enabled = true }: { enabled?: boolean } = {}) {
  const query = useQuery({
    queryKey: ["provider-catalog"],
    queryFn: loadProviderCatalog,
    enabled,
    ...CATALOG_QUERY_OPTIONS,
  });
  return {
    providers: query.data?.providers ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}

export function useValidateProviderKey() {
  return useMutation({
    mutationFn: async ({
      provider,
    }: {
      provider: ProviderId;
    }) => {
      return validateProviderKey(provider);
    },
  });
}

export function useModels({ enabled = true }: { enabled?: boolean } = {}) {
  const [settings, setSettings] = useLocalSettings();
  const { providers, isLoading, error } = useProviderCatalog({ enabled });
  const syncedProviderSignatureRef = useRef("");

  useEffect(() => {
    if (!enabled || providers.length === 0) {
      return;
    }
    const providerSignature = providers
      .map((provider) => provider.id)
      .sort()
      .join(",");
    if (syncedProviderSignatureRef.current === providerSignature) {
      return;
    }
    syncedProviderSignatureRef.current = providerSignature;

    void Promise.all(
      providers.map(async (provider) => {
        try {
          const status = await getProviderKeyStatus(provider.id);
          return [provider.id, status.has_key] as const;
        } catch {
          return [provider.id, undefined] as const;
        }
      }),
    ).then((results) => {
      const latest = getLocalSettings();
      const updates: Partial<typeof latest.models.providers> = {};
      for (const [providerId, hasKey] of results) {
        if (typeof hasKey === "boolean") {
          updates[providerId] = {
            ...latest.models.providers[providerId],
            has_key: hasKey,
          };
        }
      }
      if (Object.keys(updates).length > 0) {
        setSettings("models", {
          providers: {
            ...latest.models.providers,
            ...updates,
          },
          enabled_models: latest.models.enabled_models,
        });
      }
    });
  }, [enabled, providers, setSettings]);

  const models = useMemo(() => {
    const enabledMap = settings.models.enabled_models ?? {};
    return providers
      .flatMap((provider) => provider.models)
      .filter((model) => {
        const providerEnabled = settings.models.providers[model.provider]?.enabled;
        return providerEnabled && enabledMap[model.id] !== false;
      })
      .sort((a, b) => a.display_name.localeCompare(b.display_name));
  }, [providers, settings.models.enabled_models, settings.models.providers]);

  return { models, providers, isLoading, error };
}

export function resolveThinkingEffortForModel(
  model: ProviderModel | undefined,
  preferredEffort: string | null | undefined,
): string | undefined {
  if (!model?.supports_adaptive_thinking) {
    return undefined;
  }
  const allowedEfforts = (model.adaptive_thinking_efforts ?? [])
    .map((effort) => effort.trim().toLowerCase())
    .filter((effort) => effort.length > 0);
  const safeDefault =
    allowedEfforts.find((effort) => effort === "medium") ??
    allowedEfforts.find(
      (effort) =>
        effort === (model.default_thinking_effort ?? "").trim().toLowerCase(),
    ) ??
    allowedEfforts[0] ??
    "medium";
  if (typeof preferredEffort !== "string") {
    return safeDefault;
  }
  const normalized = preferredEffort.trim().toLowerCase();
  if (!normalized) {
    return safeDefault;
  }
  return allowedEfforts.includes(normalized) ? normalized : safeDefault;
}

export function getRuntimeModelSpec(
  model: ProviderModel | undefined,
  thinkingEffort?: string,
): RuntimeModelSpec | undefined {
  if (!model) {
    return undefined;
  }
  const resolvedThinkingEffort = resolveThinkingEffortForModel(model, thinkingEffort);
  return {
    provider: model.provider,
    model_id: model.model_id,
    tier: model.tier ?? undefined,
    thinking_effort: resolvedThinkingEffort,
    supports_vision: model.supports_vision,
  };
}

export function providerCatalogById(
  providers: ProviderCatalog[],
): Record<ProviderId, ProviderCatalog | undefined> {
  return providers.reduce(
    (acc, provider) => {
      acc[provider.id] = provider;
      return acc;
    },
    {} as Record<ProviderId, ProviderCatalog | undefined>,
  );
}

