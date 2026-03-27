"use client";

import {
  ArrowUpRightIcon,
  AudioLinesIcon,
  BotIcon,
  BoxesIcon,
  ImageIcon,
  PlusIcon,
  RefreshCwIcon,
  SaveIcon,
  SearchIcon,
  Trash2Icon,
  VideoIcon,
  WandSparklesIcon,
} from "lucide-react";
import type { ComponentType, Dispatch, SetStateAction } from "react";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import {
  useDiscoverModelServiceProvider,
  useModelServicesConfig,
  useSaveModelServicesConfig,
  useTestModelServiceProvider,
} from "@/core/model-services/hooks";
import type {
  DiscoveredProviderModel,
  ModelServiceDefaults,
  ModelServiceModel,
  ModelServiceProvider,
  ModelServicesConfig,
  ModelServicesConfigWrite,
  ProviderModality,
  ProviderTestResult,
  ProviderType,
  RegisteredModel,
} from "@/core/model-services/types";
import {
  groupModelsByProvider,
  groupProviderModelsByFamily,
  getProviderMeta,
  type ProviderMeta,
  providerModalityOrder,
} from "@/core/models/provider-catalog";
import { env } from "@/env";
import { cn, externalLinkClass } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

const modalityMeta: Record<
  ProviderModality,
  { icon: ComponentType<{ className?: string }> }
> = {
  text: { icon: BotIcon },
  image: { icon: ImageIcon },
  video: { icon: VideoIcon },
  audio: { icon: AudioLinesIcon },
};

const providerTypeOptions: ProviderType[] = [
  "openai-compatible",
  "anthropic-native",
  "gemini-native",
  "custom",
];

type DisplayProviderEntry = {
  selectionId: string;
  providerKey: string;
  label: string;
  meta: ProviderMeta;
  editableProvider?: ModelServiceProvider;
  registeredModels: RegisteredModel[];
  staticModels: RegisteredModel[];
  configuredModalities: ProviderModality[];
  providerModalities: ProviderModality[];
};

export function ModelServicesSettingsPage() {
  const { t } = useI18n();
  const isStaticDemo = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";
  const { config, isLoading, error } = useModelServicesConfig();
  const saveMutation = useSaveModelServicesConfig();
  const discoverMutation = useDiscoverModelServiceProvider();
  const testMutation = useTestModelServiceProvider();

  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<ModelServicesConfig | null>(null);
  const [selectedProviderId, setSelectedProviderId] = useState<string>();
  const [formError, setFormError] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, ProviderTestResult>>({});
  const [headerDrafts, setHeaderDrafts] = useState<Record<string, string>>({});
  const [extraBodyDrafts, setExtraBodyDrafts] = useState<Record<string, string>>({});
  const [discoverDialogOpen, setDiscoverDialogOpen] = useState(false);
  const [discoverQuery, setDiscoverQuery] = useState("");
  const [discoveredModels, setDiscoveredModels] = useState<DiscoveredProviderModel[]>([]);
  const [selectedDiscoveredModelIds, setSelectedDiscoveredModelIds] = useState<string[]>([]);

  useEffect(() => {
    if (!config) {
      return;
    }
    setDraft(initializeDraft(config));
    setHeaderDrafts(buildHeaderDrafts(config));
    setExtraBodyDrafts(buildExtraBodyDrafts(config));
  }, [config]);

  const registeredModels = useMemo(
    () => buildRegisteredModels(config, draft),
    [config, draft],
  );

  const providerEntries = useMemo(
    () => buildProviderEntries(draft, registeredModels),
    [draft, registeredModels],
  );

  const filteredProviders = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) {
      return providerEntries;
    }
    return providerEntries.filter((provider) => {
      if (provider.label.toLowerCase().includes(normalizedQuery)) {
        return true;
      }
      return provider.registeredModels.some((model) =>
        `${model.display_name ?? ""} ${model.model} ${model.name}`
          .toLowerCase()
          .includes(normalizedQuery),
      );
    });
  }, [providerEntries, query]);

  useEffect(() => {
    if (filteredProviders.length === 0) {
      setSelectedProviderId(undefined);
      return;
    }
    if (!selectedProviderId || !filteredProviders.some((provider) => provider.selectionId === selectedProviderId)) {
      setSelectedProviderId(filteredProviders[0]?.selectionId);
    }
  }, [filteredProviders, selectedProviderId]);

  const selectedProviderEntry = useMemo(
    () => filteredProviders.find((provider) => provider.selectionId === selectedProviderId)
      ?? providerEntries.find((provider) => provider.selectionId === selectedProviderId),
    [filteredProviders, providerEntries, selectedProviderId],
  );

  const selectedProvider = selectedProviderEntry?.editableProvider;

  const selectedProviderTestResult = useMemo(
    () => (selectedProvider?.id ? testResults[selectedProvider.id] : undefined),
    [selectedProvider?.id, testResults],
  );

  const defaultModelOptions = useMemo(
    () => ({
      text: registeredModels.filter((model) => model.enabled && model.modalities.includes("text")),
      image: registeredModels.filter((model) => model.enabled && model.modalities.includes("image")),
      video: registeredModels.filter((model) => model.enabled && model.modalities.includes("video")),
      audio: registeredModels.filter((model) => model.enabled && model.modalities.includes("audio")),
    }),
    [registeredModels],
  );

  const updateProvider = (providerId: string, updater: (provider: ModelServiceProvider) => ModelServiceProvider) => {
    setDraft((prev) => {
      if (!prev) {
        return prev;
      }
      return {
        ...prev,
        providers: prev.providers.map((provider) =>
          provider.id === providerId ? updater(provider) : provider,
        ),
      };
    });
  };

  const addProvider = () => {
    const provider = createEmptyProvider();
    setDraft((prev) => {
      const next = prev ?? {
        providers: [],
        defaults: {},
        registered_models: [],
      };
      return {
        ...next,
        providers: [...next.providers, provider],
      };
    });
    setQuery("");
    setSelectedProviderId(provider.id);
  };

  const deleteProvider = (providerId: string) => {
    const providerToDelete = draft?.providers.find((provider) => provider.id === providerId);
    setDraft((prev) => {
      if (!prev) {
        return prev;
      }
      const providers = prev.providers.filter((provider) => provider.id !== providerId);
      const defaults = clearDefaultsForProvider(prev.defaults, prev.providers.find((provider) => provider.id === providerId));
      return { ...prev, providers, defaults };
    });
    setTestResults((prev) => {
      const next = { ...prev };
      delete next[providerId];
      return next;
    });
    setHeaderDrafts((prev) => {
      const next = { ...prev };
      delete next[providerId];
      return next;
    });
    setExtraBodyDrafts((prev) => {
      const next = { ...prev };
      for (const model of providerToDelete?.models ?? []) {
        delete next[model.id];
      }
      return next;
    });
    setSelectedProviderId((prev) => (prev === providerId ? undefined : prev));
  };

  const addModel = () => {
    if (!selectedProvider) {
      return;
    }
    const model = createEmptyModel(selectedProvider.id);
    updateProvider(selectedProvider.id, (provider) => ({
      ...provider,
      models: [...provider.models, model],
    }));
  };

  const deleteModel = (modelId: string) => {
    if (!selectedProvider) {
      return;
    }
    const modelToDelete = selectedProvider.models.find((model) => model.id === modelId);
    updateProvider(selectedProvider.id, (provider) => ({
      ...provider,
      models: provider.models.filter((model) => model.id !== modelId),
    }));
    setDraft((prev) => {
      if (!prev) {
        return prev;
      }
      return {
        ...prev,
        defaults: clearDefaultsForModel(prev.defaults, modelToDelete),
      };
    });
    setExtraBodyDrafts((prev) => {
      const next = { ...prev };
      if (modelToDelete) {
        delete next[modelToDelete.id];
      }
      return next;
    });
  };

  const saveDraft = async () => {
    if (!draft) {
      return false;
    }
    try {
      setFormError(null);
      const payload = toWriteConfig(draft, headerDrafts, extraBodyDrafts);
      const saved = await saveMutation.mutateAsync(payload);
      setDraft(initializeDraft(saved));
      setHeaderDrafts(buildHeaderDrafts(saved));
      setExtraBodyDrafts(buildExtraBodyDrafts(saved));
      return true;
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
      return false;
    }
  };

  const saveThenRunTest = async (providerId: string) => {
    if (!draft) {
      return;
    }
    const saved = await saveDraft();
    if (!saved) {
      return;
    }
    try {
      setFormError(null);
      const result = await testMutation.mutateAsync(providerId);
      setTestResults((prev) => ({ ...prev, [providerId]: result }));
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    }
  };

  const openDiscoverModels = async (providerId: string) => {
    if (!draft) {
      return;
    }
    const saved = await saveDraft();
    if (!saved) {
      return;
    }
    try {
      setFormError(null);
      const response = await discoverMutation.mutateAsync(providerId);
      setDiscoveredModels(response.models);
      setSelectedDiscoveredModelIds([]);
      setDiscoverQuery("");
      setDiscoverDialogOpen(true);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    }
  };

  const filteredDiscoveredModels = useMemo(() => {
    const normalizedQuery = discoverQuery.trim().toLowerCase();
    if (!normalizedQuery) {
      return discoveredModels;
    }
    return discoveredModels.filter((model) =>
      `${model.display_name} ${model.id} ${model.owned_by ?? ""}`
        .toLowerCase()
        .includes(normalizedQuery),
    );
  }, [discoverQuery, discoveredModels]);

  const groupedDiscoveredModels = useMemo(
    () => groupDiscoveredModels(filteredDiscoveredModels),
    [filteredDiscoveredModels],
  );

  const importDiscoveredModels = () => {
    if (!selectedProvider || selectedDiscoveredModelIds.length === 0) {
      return;
    }

    const selectedIds = new Set(selectedDiscoveredModelIds);
    const selectedModels = discoveredModels.filter(
      (model) => selectedIds.has(model.id) && !model.already_configured,
    );
    if (selectedModels.length === 0) {
      setDiscoverDialogOpen(false);
      return;
    }

    const existingNames = new Set(registeredModels.map((model) => model.name));
    for (const model of selectedProvider.models) {
      existingNames.add(model.name);
    }

    const importedModels = selectedModels.map((model) => {
      const name = buildDraftModelName(selectedProvider.id, model.id, existingNames);
      existingNames.add(name);
      return createImportedModel(selectedProvider.id, model, name);
    });

    updateProvider(selectedProvider.id, (provider) => ({
      ...provider,
      models: [...provider.models, ...importedModels],
    }));
    setDiscoveredModels((prev) =>
      prev.map((model) =>
        selectedIds.has(model.id)
          ? { ...model, already_configured: true }
          : model,
      ),
    );
    setSelectedDiscoveredModelIds([]);
    setDiscoverDialogOpen(false);
  };

  return (
    <SettingsSection
      title={t.settings.modelServices.title}
      description={t.settings.modelServices.description}
    >
      {isLoading ? (
        <div className="text-muted-foreground text-sm">{t.common.loading}</div>
      ) : error ? (
        <div className="text-destructive text-sm">{error.message}</div>
      ) : (
        <div className="space-y-6">
          {formError ? (
            <div className="text-destructive rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm">
              {formError}
            </div>
          ) : null}

          <Card className="gap-0 py-0">
            <CardHeader className="border-b">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <CardTitle className="text-base">
                    {t.settings.modelServices.defaultModelsTitle}
                  </CardTitle>
                  <CardDescription>
                    {t.settings.modelServices.defaultModelsDescription}
                  </CardDescription>
                </div>
                <Button onClick={saveDraft} disabled={saveMutation.isPending || isStaticDemo}>
                  <SaveIcon className="size-4" />
                  {saveMutation.isPending
                    ? t.settings.modelServices.saving
                    : t.settings.modelServices.saveChanges}
                </Button>
              </div>
            </CardHeader>
            <CardContent className="grid gap-4 py-6 md:grid-cols-2 xl:grid-cols-4">
              <DefaultModelField
                label={t.settings.modelServices.defaultTextModel}
                value={draft?.defaults.text_model_name}
                options={defaultModelOptions.text}
                onChange={(value) =>
                  setDraft((prev) =>
                    prev
                      ? { ...prev, defaults: { ...prev.defaults, text_model_name: emptyToUndefined(value) } }
                      : prev,
                  )
                }
              />
              <DefaultModelField
                label={t.settings.modelServices.defaultImageModel}
                value={draft?.defaults.image_model_name}
                options={defaultModelOptions.image}
                onChange={(value) =>
                  setDraft((prev) =>
                    prev
                      ? { ...prev, defaults: { ...prev.defaults, image_model_name: emptyToUndefined(value) } }
                      : prev,
                  )
                }
              />
              <DefaultModelField
                label={t.settings.modelServices.defaultVideoModel}
                value={draft?.defaults.video_model_name}
                options={defaultModelOptions.video}
                onChange={(value) =>
                  setDraft((prev) =>
                    prev
                      ? { ...prev, defaults: { ...prev.defaults, video_model_name: emptyToUndefined(value) } }
                      : prev,
                  )
                }
              />
              <DefaultModelField
                label={t.settings.modelServices.defaultAudioModel}
                value={draft?.defaults.audio_model_name}
                options={defaultModelOptions.audio}
                onChange={(value) =>
                  setDraft((prev) =>
                    prev
                      ? { ...prev, defaults: { ...prev.defaults, audio_model_name: emptyToUndefined(value) } }
                      : prev,
                  )
                }
              />
            </CardContent>
          </Card>

          <div className="grid gap-6 xl:grid-cols-[320px_1fr]">
            <Card className="gap-0 overflow-hidden py-0">
              <CardHeader className="border-b px-4 py-4">
                <CardTitle className="text-base">
                  {t.settings.modelServices.providersTitle}
                </CardTitle>
                <CardDescription>
                  {t.settings.modelServices.providersDescription}
                </CardDescription>
                <div className="relative mt-2">
                  <SearchIcon className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
                  <Input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder={t.settings.modelServices.searchPlaceholder}
                    className="pl-9"
                  />
                </div>
              </CardHeader>
              <ScrollArea className="h-[720px]">
                <div className="space-y-2 p-3">
                  <Button className="w-full" variant="outline" onClick={addProvider} disabled={isStaticDemo}>
                    <PlusIcon className="size-4" />
                    {t.settings.modelServices.addProvider}
                  </Button>
                  {filteredProviders.length === 0 ? (
                    <Empty className="min-h-[240px]">
                      <EmptyHeader>
                        <EmptyMedia variant="icon">
                          <BoxesIcon className="size-5" />
                        </EmptyMedia>
                        <EmptyTitle>{t.settings.modelServices.emptyTitle}</EmptyTitle>
                        <EmptyDescription>
                          {t.settings.modelServices.emptyDescription}
                        </EmptyDescription>
                      </EmptyHeader>
                    </Empty>
                  ) : (
                    filteredProviders.map((providerEntry) => {
                      const active = providerEntry.selectionId === selectedProviderId;
                      return (
                        <div
                          key={providerEntry.selectionId}
                          role="button"
                          tabIndex={0}
                          onClick={() => setSelectedProviderId(providerEntry.selectionId)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              setSelectedProviderId(providerEntry.selectionId);
                            }
                          }}
                          className={cn(
                            "w-full rounded-xl border p-3 text-left transition-colors",
                            active
                              ? "border-primary bg-primary/5"
                              : "hover:bg-muted/60 bg-background",
                          )}
                        >
                          <div className="flex items-start gap-3">
                            <ProviderAvatar
                              label={providerEntry.meta.shortLabel}
                              accentClass={providerEntry.meta.accentClass}
                            />
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center justify-between gap-3">
                                <div className="truncate font-medium">{providerEntry.label}</div>
                                <Switch checked={providerEntry.editableProvider?.enabled ?? true} disabled aria-readonly />
                              </div>
                              <div className="text-muted-foreground mt-1 text-xs">
                                {providerEntry.registeredModels
                                  .slice(0, 2)
                                  .map((model) => model.display_name ?? model.name)
                                  .join(" / ")}
                              </div>
                              <div className="mt-3 flex flex-wrap gap-2">
                                {providerEntry.providerModalities.map((modality) => (
                                  <CapabilityBadge
                                    key={`${providerEntry.selectionId}-${modality}`}
                                    modality={modality}
                                    label={t.settings.modelServices.capabilities[modality]}
                                  />
                                ))}
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </ScrollArea>
            </Card>

            <div className="space-y-6">
              {selectedProviderEntry ? (
                <>
                  <Card className="gap-0 py-0">
                    <CardHeader className="border-b">
                      <div className="flex flex-wrap items-start justify-between gap-4">
                        <div className="flex min-w-0 items-center gap-4">
                          <ProviderAvatar
                            label={selectedProviderEntry.meta.shortLabel}
                            accentClass={selectedProviderEntry.meta.accentClass}
                            size="lg"
                          />
                          <div className="min-w-0">
                            <CardTitle className="truncate text-xl">
                              {selectedProvider?.name ?? selectedProviderEntry.label ?? t.settings.modelServices.newProvider}
                            </CardTitle>
                            <CardDescription className="mt-1">
                              {selectedProviderEntry.registeredModels.length} {t.settings.modelServices.modelsCountSuffix}
                            </CardDescription>
                          </div>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          {(selectedProvider?.homepage ?? selectedProviderEntry.meta.homepage) ? (
                            <a
                              className={cn("text-sm font-medium", externalLinkClass)}
                              href={selectedProvider?.homepage ?? selectedProviderEntry.meta.homepage}
                              rel="noreferrer"
                              target="_blank"
                            >
                              {t.settings.modelServices.openProvider}
                              <ArrowUpRightIcon className="ml-1 inline size-4" />
                            </a>
                          ) : null}
                          {selectedProvider ? (
                            <>
                              <Button
                                variant="outline"
                                onClick={() => void openDiscoverModels(selectedProvider.id)}
                                disabled={discoverMutation.isPending || saveMutation.isPending || isStaticDemo}
                              >
                                <RefreshCwIcon className="size-4" />
                                {discoverMutation.isPending
                                  ? t.settings.modelServices.discoveringModels
                                  : t.settings.modelServices.discoverModels}
                              </Button>
                              <Button
                                variant="outline"
                                onClick={() => void saveThenRunTest(selectedProvider.id)}
                                disabled={testMutation.isPending || saveMutation.isPending || isStaticDemo}
                              >
                                <WandSparklesIcon className="size-4" />
                                {t.settings.modelServices.testConnection}
                              </Button>
                              <Button
                                variant="outline"
                                onClick={() => deleteProvider(selectedProvider.id)}
                                disabled={isStaticDemo}
                              >
                                <Trash2Icon className="size-4" />
                                {t.settings.modelServices.deleteProvider}
                              </Button>
                            </>
                          ) : (
                            <Button
                              variant="outline"
                              onClick={() => addProviderFromEntry(selectedProviderEntry, setDraft, setQuery, setSelectedProviderId)}
                              disabled={isStaticDemo}
                            >
                              <PlusIcon className="size-4" />
                              {t.settings.modelServices.createManagedProvider}
                            </Button>
                          )}
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-6 py-6">
                      {selectedProviderEntry.staticModels.length > 0 ? (
                        <SectionBlock
                          title={t.settings.modelServices.systemModelsTitle}
                          description={t.settings.modelServices.systemModelsDescription}
                        >
                          <div className="flex flex-wrap gap-2">
                            <Badge variant="outline">{t.settings.modelServices.sourceConfig}</Badge>
                            {selectedProvider ? (
                              <Badge variant="outline">{t.settings.modelServices.sourceProvider}</Badge>
                            ) : null}
                          </div>
                          <div className="space-y-3">
                            {groupProviderModelsByFamily(selectedProviderEntry.staticModels).map((group) => (
                              <div key={group.family} className="rounded-lg border p-3">
                                <div className="text-sm font-medium">{group.family}</div>
                                <div className="mt-2 flex flex-wrap gap-2">
                                  {group.models.map((model) => (
                                    <Badge key={model.name} variant="secondary">
                                      {model.display_name ?? model.name}
                                    </Badge>
                                  ))}
                                </div>
                              </div>
                            ))}
                          </div>
                        </SectionBlock>
                      ) : null}

                      {!selectedProvider ? (
                        <SectionBlock
                          title={t.settings.modelServices.createManagedProvider}
                          description={t.settings.modelServices.createManagedProviderDescription}
                        >
                          <Button
                            onClick={() => addProviderFromEntry(selectedProviderEntry, setDraft, setQuery, setSelectedProviderId)}
                            disabled={isStaticDemo}
                          >
                            <PlusIcon className="size-4" />
                            {t.settings.modelServices.createManagedProvider}
                          </Button>
                        </SectionBlock>
                      ) : null}

                      {selectedProvider ? (
                      <div className="grid gap-6 lg:grid-cols-2">
                        <SectionBlock
                          title={t.settings.modelServices.basicInfoTitle}
                          description={t.settings.modelServices.basicInfoDescription}
                        >
                          <LabeledField label={t.settings.modelServices.providerName}>
                            <Input
                              value={selectedProvider.name}
                              onChange={(event) =>
                                updateProvider(selectedProvider.id, (provider) => ({
                                  ...provider,
                                  name: event.target.value,
                                }))
                              }
                            />
                          </LabeledField>
                          <LabeledField label={t.settings.modelServices.providerType}>
                            <Select
                              value={selectedProvider.provider_type}
                              onValueChange={(value) =>
                                updateProvider(selectedProvider.id, (provider) => ({
                                  ...provider,
                                  provider_type: value as ProviderType,
                                }))
                              }
                            >
                              <SelectTrigger className="w-full">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {providerTypeOptions.map((value) => (
                                  <SelectItem key={value} value={value}>
                                    {value}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </LabeledField>
                          <LabeledField label={t.settings.modelServices.providerHomepage}>
                            <Input
                              value={selectedProvider.homepage ?? ""}
                              onChange={(event) =>
                                updateProvider(selectedProvider.id, (provider) => ({
                                  ...provider,
                                  homepage: event.target.value,
                                }))
                              }
                            />
                          </LabeledField>
                          <LabeledSwitch
                            label={t.settings.modelServices.enabled}
                            checked={selectedProvider.enabled}
                            onCheckedChange={(checked) =>
                              updateProvider(selectedProvider.id, (provider) => ({
                                ...provider,
                                enabled: checked,
                              }))
                            }
                          />
                          <LabeledField label={t.settings.modelServices.providerModalities}>
                            <ModalityEditor
                              value={selectedProvider.modalities}
                              onToggle={(modality) =>
                                updateProvider(selectedProvider.id, (provider) => ({
                                  ...provider,
                                  modalities: toggleModality(provider.modalities, modality),
                                }))
                              }
                              labels={t.settings.modelServices.capabilities}
                            />
                          </LabeledField>
                          <LabeledField label={t.settings.modelServices.providerNotes}>
                            <Textarea
                              value={selectedProvider.notes ?? ""}
                              onChange={(event) =>
                                updateProvider(selectedProvider.id, (provider) => ({
                                  ...provider,
                                  notes: event.target.value,
                                }))
                              }
                            />
                          </LabeledField>
                        </SectionBlock>

                        <SectionBlock
                          title={t.settings.modelServices.apiConfigTitle}
                          description={t.settings.modelServices.apiConfigDescription}
                        >
                          <LabeledField label={t.settings.modelServices.baseUrl}>
                            <Input
                              value={selectedProvider.base_url}
                              onChange={(event) =>
                                updateProvider(selectedProvider.id, (provider) => ({
                                  ...provider,
                                  base_url: event.target.value,
                                }))
                              }
                            />
                          </LabeledField>
                          <LabeledField label={t.settings.modelServices.apiKey}>
                            <div className="space-y-2">
                              <Input
                                value={selectedProvider.api_key_input ?? ""}
                                placeholder={selectedProvider.api_key_masked ?? ""}
                                onChange={(event) =>
                                  updateProvider(selectedProvider.id, (provider) => ({
                                    ...provider,
                                    api_key_input: event.target.value,
                                    api_key_mode: event.target.value ? "replace" : "preserve",
                                  }))
                                }
                              />
                              <div className="flex items-center justify-between gap-3">
                                <div className="text-muted-foreground text-xs">
                                  {t.settings.modelServices.apiKeyHint}
                                </div>
                                {selectedProvider.api_key_configured ? (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() =>
                                      updateProvider(selectedProvider.id, (provider) => ({
                                        ...provider,
                                        api_key_input: "",
                                        api_key_mode: "clear",
                                        api_key_configured: false,
                                        api_key_masked: undefined,
                                      }))
                                    }
                                  >
                                    {t.settings.modelServices.clearApiKey}
                                  </Button>
                                ) : null}
                              </div>
                            </div>
                          </LabeledField>
                          <LabeledField label={t.settings.modelServices.headersJson}>
                            <Textarea
                              value={headerDrafts[selectedProvider.id] ?? ""}
                              onChange={(event) =>
                                setHeaderDrafts((prev) => ({
                                  ...prev,
                                  [selectedProvider.id]: event.target.value,
                                }))
                              }
                            />
                          </LabeledField>
                          <div className="text-muted-foreground text-xs">
                            {t.settings.modelServices.headersHint}
                          </div>
                        </SectionBlock>
                      </div>
                      ) : null}

                      {selectedProvider ? (
                        <SectionBlock
                          title={t.settings.modelServices.modelsTitle}
                          description={t.settings.modelServices.modelsDescription}
                        >
                        <div className="mb-4 flex justify-end">
                          <Button variant="outline" onClick={addModel} disabled={isStaticDemo}>
                            <PlusIcon className="size-4" />
                            {t.settings.modelServices.addModel}
                          </Button>
                        </div>
                        <div className="space-y-4">
                          {selectedProvider.models.map((model) => (
                            <Card key={model.id} className="gap-0 py-0">
                              <CardHeader className="border-b py-4">
                                <div className="flex flex-wrap items-center justify-between gap-3">
                                  <div>
                                    <CardTitle className="text-base">
                                      {model.display_name ?? model.name ?? t.settings.modelServices.newModel}
                                    </CardTitle>
                                    <CardDescription>{model.model}</CardDescription>
                                  </div>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => deleteModel(model.id)}
                                    disabled={isStaticDemo}
                                  >
                                    <Trash2Icon className="size-4" />
                                    {t.settings.modelServices.deleteModel}
                                  </Button>
                                </div>
                              </CardHeader>
                              <CardContent className="grid gap-4 py-4 lg:grid-cols-2">
                                <LabeledField label={t.settings.modelServices.modelName}>
                                  <Input
                                    value={model.name}
                                    onChange={(event) =>
                                      updateModel(selectedProvider.id, model.id, {
                                        name: event.target.value,
                                      }, setDraft)
                                    }
                                  />
                                </LabeledField>
                                <LabeledField label={t.settings.modelServices.displayName}>
                                  <Input
                                    value={model.display_name ?? ""}
                                    onChange={(event) =>
                                      updateModel(selectedProvider.id, model.id, {
                                        display_name: event.target.value,
                                      }, setDraft)
                                    }
                                  />
                                </LabeledField>
                                <LabeledField label={t.settings.modelServices.remoteModelId}>
                                  <Input
                                    value={model.model}
                                    onChange={(event) =>
                                      updateModel(selectedProvider.id, model.id, {
                                        model: event.target.value,
                                      }, setDraft)
                                    }
                                  />
                                </LabeledField>
                                <LabeledField label={t.settings.modelServices.descriptionLabel}>
                                  <Input
                                    value={model.description ?? ""}
                                    onChange={(event) =>
                                      updateModel(selectedProvider.id, model.id, {
                                        description: event.target.value,
                                      }, setDraft)
                                    }
                                  />
                                </LabeledField>
                                <LabeledSwitch
                                  label={t.settings.modelServices.enabled}
                                  checked={model.enabled}
                                  onCheckedChange={(checked) =>
                                    updateModel(selectedProvider.id, model.id, { enabled: checked }, setDraft)
                                  }
                                />
                                <LabeledSwitch
                                  label={t.settings.modelServices.supportsThinking}
                                  checked={model.supports_thinking}
                                  onCheckedChange={(checked) =>
                                    updateModel(selectedProvider.id, model.id, { supports_thinking: checked }, setDraft)
                                  }
                                />
                                <LabeledSwitch
                                  label={t.settings.modelServices.supportsReasoningEffort}
                                  checked={model.supports_reasoning_effort}
                                  onCheckedChange={(checked) =>
                                    updateModel(selectedProvider.id, model.id, { supports_reasoning_effort: checked }, setDraft)
                                  }
                                />
                                <LabeledSwitch
                                  label={t.settings.modelServices.supportsVision}
                                  checked={model.supports_vision}
                                  onCheckedChange={(checked) =>
                                    updateModel(selectedProvider.id, model.id, { supports_vision: checked }, setDraft)
                                  }
                                />
                                <LabeledField label={t.settings.modelServices.modelModalities}>
                                  <ModalityEditor
                                    value={model.modalities}
                                    onToggle={(modality) =>
                                      updateModel(
                                        selectedProvider.id,
                                        model.id,
                                        { modalities: toggleModality(model.modalities, modality) },
                                        setDraft,
                                      )
                                    }
                                    labels={t.settings.modelServices.capabilities}
                                  />
                                </LabeledField>
                                <LabeledField label={t.settings.modelServices.maxTokens}>
                                  <Input
                                    type="number"
                                    value={model.max_tokens ?? ""}
                                    onChange={(event) =>
                                      updateModel(
                                        selectedProvider.id,
                                        model.id,
                                        { max_tokens: event.target.value ? Number(event.target.value) : null },
                                        setDraft,
                                      )
                                    }
                                  />
                                </LabeledField>
                                <LabeledField label={t.settings.modelServices.temperature}>
                                  <Input
                                    type="number"
                                    value={model.temperature ?? ""}
                                    onChange={(event) =>
                                      updateModel(
                                        selectedProvider.id,
                                        model.id,
                                        { temperature: event.target.value ? Number(event.target.value) : null },
                                        setDraft,
                                      )
                                    }
                                  />
                                </LabeledField>
                                <LabeledSwitch
                                  label={t.settings.modelServices.useResponsesApi}
                                  checked={Boolean(model.use_responses_api)}
                                  onCheckedChange={(checked) =>
                                    updateModel(
                                      selectedProvider.id,
                                      model.id,
                                      { use_responses_api: checked },
                                      setDraft,
                                    )
                                  }
                                />
                                <LabeledField label={t.settings.modelServices.outputVersion}>
                                  <Input
                                    value={model.output_version ?? ""}
                                    onChange={(event) =>
                                      updateModel(
                                        selectedProvider.id,
                                        model.id,
                                        { output_version: event.target.value || null },
                                        setDraft,
                                      )
                                    }
                                  />
                                </LabeledField>
                                <div className="lg:col-span-2">
                                  <LabeledField label={t.settings.modelServices.extraBodyJson}>
                                    <Textarea
                                      value={extraBodyDrafts[model.id] ?? ""}
                                      onChange={(event) =>
                                        setExtraBodyDrafts((prev) => ({
                                          ...prev,
                                          [model.id]: event.target.value,
                                        }))
                                      }
                                    />
                                  </LabeledField>
                                  <div className="text-muted-foreground mt-2 text-xs">
                                    {t.settings.modelServices.extraBodyHint}
                                  </div>
                                </div>
                              </CardContent>
                            </Card>
                          ))}
                          {selectedProvider.models.length === 0 ? (
                            <div className="text-muted-foreground rounded-lg border border-dashed px-4 py-6 text-sm">
                              {t.settings.modelServices.noModels}
                            </div>
                          ) : null}
                        </div>
                        </SectionBlock>
                      ) : null}

                      {selectedProvider ? (
                      <div className="grid gap-6 lg:grid-cols-2">
                        <SectionBlock
                          title={t.settings.modelServices.advancedTitle}
                          description={t.settings.modelServices.advancedDescription}
                        >
                          <div className="grid gap-3 sm:grid-cols-2">
                            {providerModalityOrder.map((modality) => {
                              const providerSupports = selectedProvider.modalities.includes(modality);
                              const modelsCover = selectedProvider.models.some(
                                (model) => model.enabled && model.modalities.includes(modality),
                              );
                              return (
                                <div
                                  key={modality}
                                  className={cn(
                                    "rounded-xl border p-3",
                                    providerSupports
                                      ? "border-primary/30 bg-primary/5"
                                      : "bg-muted/30",
                                  )}
                                >
                                  <div className="flex items-center gap-2 text-sm font-medium">
                                    {renderModalityIcon(modality)}
                                    {t.settings.modelServices.capabilities[modality]}
                                  </div>
                                  <div className="text-muted-foreground mt-2 text-xs">
                                    {modelsCover
                                      ? t.settings.modelServices.serviceEnabled
                                      : providerSupports
                                        ? t.settings.modelServices.serviceAvailable
                                        : t.settings.modelServices.serviceNotConfigured}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </SectionBlock>

                        <SectionBlock
                          title={t.settings.modelServices.connectionTitle}
                          description={t.settings.modelServices.connectionDescription}
                        >
                          {selectedProviderTestResult ? (
                            <div className="space-y-2 rounded-xl border p-4 text-sm">
                              <div className="font-medium">
                                {selectedProviderTestResult.ok
                                  ? t.settings.modelServices.connectionOk
                                  : t.settings.modelServices.connectionFailed}
                              </div>
                              <div className="text-muted-foreground text-xs">
                                {selectedProviderTestResult.message}
                              </div>
                              {selectedProviderTestResult.discovered_models.length > 0 ? (
                                <div className="flex flex-wrap gap-2 pt-2">
                                  {selectedProviderTestResult.discovered_models
                                    .slice(0, 8)
                                    .map((modelId) => (
                                      <Badge key={modelId} variant="outline">
                                        {modelId}
                                      </Badge>
                                    ))}
                                </div>
                              ) : null}
                            </div>
                          ) : (
                            <div className="text-muted-foreground rounded-lg border border-dashed px-4 py-6 text-sm">
                              {t.settings.modelServices.connectionEmpty}
                            </div>
                          )}
                        </SectionBlock>
                      </div>
                      ) : null}
                    </CardContent>
                  </Card>
                </>
              ) : (
                <Empty className="min-h-[420px]">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <BoxesIcon className="size-5" />
                    </EmptyMedia>
                    <EmptyTitle>{t.settings.modelServices.noProviderSelected}</EmptyTitle>
                    <EmptyDescription>
                      {t.settings.modelServices.emptyDescription}
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              )}
            </div>
          </div>
        </div>
      )}
      <DiscoverModelsDialog
        open={discoverDialogOpen}
        onOpenChange={setDiscoverDialogOpen}
        query={discoverQuery}
        onQueryChange={setDiscoverQuery}
        groups={groupedDiscoveredModels}
        selectedModelIds={selectedDiscoveredModelIds}
        onToggleModel={(modelId) =>
          setSelectedDiscoveredModelIds((prev) =>
            prev.includes(modelId)
              ? prev.filter((item) => item !== modelId)
              : [...prev, modelId],
          )
        }
        onImport={importDiscoveredModels}
        isImportDisabled={selectedDiscoveredModelIds.length === 0}
      />
    </SettingsSection>
  );
}

function DefaultModelField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value?: string | null;
  options: { name: string; display_name?: string | null }[];
  onChange: (value: string) => void;
}) {
  return (
    <LabeledField label={label}>
      <Select value={value ?? "__none__"} onValueChange={onChange}>
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__none__">-</SelectItem>
          {options.map((option) => (
            <SelectItem key={option.name} value={option.name}>
              {option.display_name ?? option.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </LabeledField>
  );
}

function SectionBlock({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-4 rounded-xl border p-4">
      <div>
        <div className="font-medium">{title}</div>
        <div className="text-muted-foreground mt-1 text-sm">{description}</div>
      </div>
      <Separator />
      <div className="space-y-4">{children}</div>
    </div>
  );
}

function LabeledField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="space-y-2">
      <div className="text-sm font-medium">{label}</div>
      {children}
    </label>
  );
}

function LabeledSwitch({
  label,
  checked,
  onCheckedChange,
}: {
  label: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border px-3 py-2">
      <div className="text-sm font-medium">{label}</div>
      <Switch checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  );
}

function ProviderAvatar({
  label,
  accentClass,
  size = "md",
}: {
  label: string;
  accentClass: string;
  size?: "md" | "lg";
}) {
  const classes =
    size === "lg" ? "size-14 rounded-2xl text-base" : "size-10 rounded-xl text-sm";
  return (
    <div className={cn("flex shrink-0 items-center justify-center font-semibold", accentClass, classes)}>
      {label}
    </div>
  );
}

function CapabilityBadge({
  modality,
  label,
}: {
  modality: ProviderModality;
  label: string;
}) {
  return (
    <Badge variant="outline" className="gap-1.5">
      {renderModalityIcon(modality)}
      {label}
    </Badge>
  );
}

function ModalityEditor({
  value,
  onToggle,
  labels,
}: {
  value: ProviderModality[];
  onToggle: (modality: ProviderModality) => void;
  labels: Record<ProviderModality, string>;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {providerModalityOrder.map((modality) => (
        <Button
          key={modality}
          type="button"
          variant={value.includes(modality) ? "default" : "outline"}
          size="sm"
          onClick={() => onToggle(modality)}
        >
          {renderModalityIcon(modality)}
          {labels[modality]}
        </Button>
      ))}
    </div>
  );
}

function renderModalityIcon(modality: ProviderModality) {
  const Icon = modalityMeta[modality].icon;
  return <Icon className="size-3.5" />;
}

function DiscoverModelsDialog({
  open,
  onOpenChange,
  query,
  onQueryChange,
  groups,
  selectedModelIds,
  onToggleModel,
  onImport,
  isImportDisabled,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  query: string;
  onQueryChange: (value: string) => void;
  groups: Array<{ name: string; models: DiscoveredProviderModel[] }>;
  selectedModelIds: string[];
  onToggleModel: (modelId: string) => void;
  onImport: () => void;
  isImportDisabled: boolean;
}) {
  const { t } = useI18n();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="flex max-h-[80vh] flex-col sm:max-w-4xl"
        aria-describedby={undefined}
      >
        <DialogHeader>
          <DialogTitle>{t.settings.modelServices.discoverModelsTitle}</DialogTitle>
          <DialogDescription>
            {t.settings.modelServices.discoverModelsDescription}
          </DialogDescription>
        </DialogHeader>
        <div className="relative">
          <SearchIcon className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={t.settings.modelServices.discoverModelsSearchPlaceholder}
            className="pl-9"
          />
        </div>
        <div className="text-muted-foreground flex items-center justify-between text-sm">
          <span>
            {t.settings.modelServices.selectedModelsCount(
              selectedModelIds.length,
            )}
          </span>
        </div>
        <ScrollArea className="min-h-0 flex-1 rounded-lg border">
          <div className="space-y-4 p-4">
            {groups.length === 0 ? (
              <div className="text-muted-foreground rounded-lg border border-dashed px-4 py-8 text-center text-sm">
                {t.settings.modelServices.discoverModelsEmpty}
              </div>
            ) : (
              groups.map((group) => (
                <div key={group.name} className="space-y-3">
                  <div className="text-sm font-medium">{group.name}</div>
                  <div className="space-y-2">
                    {group.models.map((model) => {
                      const selected = selectedModelIds.includes(model.id);
                      const disabled = model.already_configured;
                      return (
                        <div
                          key={model.id}
                          role="button"
                          tabIndex={disabled ? -1 : 0}
                          onClick={() => {
                            if (!disabled) {
                              onToggleModel(model.id);
                            }
                          }}
                          onKeyDown={(event) => {
                            if (
                              !disabled &&
                              (event.key === "Enter" || event.key === " ")
                            ) {
                              event.preventDefault();
                              onToggleModel(model.id);
                            }
                          }}
                          className={cn(
                            "rounded-xl border p-3 transition-colors",
                            disabled
                              ? "bg-muted/40 cursor-not-allowed opacity-70"
                              : selected
                                ? "border-primary bg-primary/5"
                                : "hover:bg-muted/60 cursor-pointer",
                          )}
                        >
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0 space-y-1">
                              <div className="font-medium">
                                {model.display_name}
                              </div>
                              <div className="text-muted-foreground text-sm">
                                {model.id}
                              </div>
                            </div>
                            <div className="flex flex-wrap gap-2">
                              {model.owned_by ? (
                                <Badge variant="outline">
                                  {t.settings.modelServices.modelSource}:{" "}
                                  {model.owned_by}
                                </Badge>
                              ) : null}
                              <Badge variant={disabled ? "secondary" : "outline"}>
                                {disabled
                                  ? t.settings.modelServices.alreadyImported
                                  : selected
                                    ? t.settings.modelServices.selectedForImport
                                    : t.settings.modelServices.addModel}
                              </Badge>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))
            )}
          </div>
        </ScrollArea>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t.common.cancel}
          </Button>
          <Button onClick={onImport} disabled={isImportDisabled}>
            {t.settings.modelServices.importSelectedModels}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function toggleModality(
  current: ProviderModality[],
  modality: ProviderModality,
): ProviderModality[] {
  if (current.includes(modality)) {
    const next = current.filter((item) => item !== modality);
    return next.length > 0 ? next : ["text"];
  }
  return [...current, modality];
}

function initializeDraft(config: ModelServicesConfig): ModelServicesConfig {
  return {
    ...config,
    providers: config.providers.map(initializeProviderDraft),
  };
}

function initializeProviderDraft(provider: ModelServiceProvider): ModelServiceProvider {
  return {
    ...provider,
    api_key_input: "",
    api_key_mode: "preserve",
    models: provider.models.map((model) => ({
      ...model,
      modalities: [...model.modalities],
    })),
    modalities: [...provider.modalities],
  };
}

function toWriteConfig(
  config: ModelServicesConfig,
  headerDrafts: Record<string, string>,
  extraBodyDrafts: Record<string, string>,
): ModelServicesConfigWrite {
  return {
    defaults: config.defaults,
    providers: config.providers.map((provider) => ({
      id: provider.id,
      name: provider.name,
      provider_type: provider.provider_type,
      enabled: provider.enabled,
      base_url: provider.base_url,
      api_key: provider.api_key_input ?? "",
      api_key_mode: provider.api_key_mode ?? "preserve",
      headers: parseObjectJson(headerDrafts[provider.id] ?? ""),
      homepage: provider.homepage,
      notes: provider.notes,
      modalities: provider.modalities,
      models: provider.models.map((model) => ({
        ...model,
        extra_body: parseUnknownJson(extraBodyDrafts[model.id] ?? ""),
      })),
    })),
  };
}

function createEmptyProvider(): ModelServiceProvider {
  const id = `provider-${crypto.randomUUID().slice(0, 8)}`;
  return {
    id,
    name: "",
    provider_type: "openai-compatible",
    enabled: true,
    base_url: "",
    api_key_masked: undefined,
    api_key_configured: false,
    api_key_input: "",
    api_key_mode: "preserve",
    headers: {},
    homepage: "",
    notes: "",
    modalities: ["text"],
    models: [],
  };
}

function createEmptyModel(providerId: string): ModelServiceModel {
  const id = `model-${crypto.randomUUID().slice(0, 8)}`;
  return {
    id,
    name: `${providerId}-model-${id.slice(-4)}`,
    display_name: "",
    model: "",
    enabled: true,
    modalities: ["text"],
    supports_thinking: false,
    supports_reasoning_effort: false,
    supports_vision: false,
    use_responses_api: false,
    output_version: "",
    extra_body: null,
    max_tokens: null,
    temperature: null,
    description: "",
  };
}

function createImportedModel(
  providerId: string,
  model: DiscoveredProviderModel,
  name: string,
): ModelServiceModel {
  return {
    id: `model-${crypto.randomUUID().slice(0, 8)}`,
    name,
    display_name: model.display_name,
    model: model.id,
    enabled: true,
    modalities: ["text"],
    supports_thinking: false,
    supports_reasoning_effort: false,
    supports_vision: false,
    use_responses_api: false,
    output_version: "",
    extra_body: null,
    max_tokens: null,
    temperature: null,
    description: model.owned_by
      ? `${providerId} / ${model.owned_by}`
      : "",
  };
}

function parseObjectJson(value: string): Record<string, string> {
  if (!value.trim()) {
    return {};
  }
  const parsed = JSON.parse(value) as Record<string, string>;
  return parsed && typeof parsed === "object" ? parsed : {};
}

function parseUnknownJson(value: string): Record<string, unknown> | null {
  if (!value.trim()) {
    return null;
  }
  const parsed = JSON.parse(value) as Record<string, unknown>;
  return parsed && typeof parsed === "object" ? parsed : null;
}

function prettyJson(value: unknown): string {
  if (!value || (typeof value === "object" && Object.keys(value as Record<string, unknown>).length === 0)) {
    return "";
  }
  return JSON.stringify(value, null, 2);
}

function emptyToUndefined(value: string) {
  return value === "__none__" ? undefined : value;
}

function clearDefaultsForProvider(
  defaults: ModelServiceDefaults,
  provider?: ModelServiceProvider,
): ModelServiceDefaults {
  if (!provider) {
    return defaults;
  }
  const modelNames = new Set(provider.models.map((model) => model.name));
  return {
    text_model_name: modelNames.has(defaults.text_model_name ?? "") ? undefined : defaults.text_model_name,
    image_model_name: modelNames.has(defaults.image_model_name ?? "") ? undefined : defaults.image_model_name,
    video_model_name: modelNames.has(defaults.video_model_name ?? "") ? undefined : defaults.video_model_name,
    audio_model_name: modelNames.has(defaults.audio_model_name ?? "") ? undefined : defaults.audio_model_name,
  };
}

function clearDefaultsForModel(
  defaults: ModelServiceDefaults,
  model?: ModelServiceModel,
): ModelServiceDefaults {
  if (!model) {
    return defaults;
  }
  return {
    text_model_name: defaults.text_model_name === model.name ? undefined : defaults.text_model_name,
    image_model_name: defaults.image_model_name === model.name ? undefined : defaults.image_model_name,
    video_model_name: defaults.video_model_name === model.name ? undefined : defaults.video_model_name,
    audio_model_name: defaults.audio_model_name === model.name ? undefined : defaults.audio_model_name,
  };
}

function getProviderMetaFromProvider(provider: ModelServiceProvider) {
  return getProviderMeta({
    id: provider.id,
    name: provider.name,
    model: provider.name,
    display_name: provider.name,
    provider: provider.id,
    provider_label: provider.name,
    provider_url: provider.homepage,
    modalities: provider.modalities,
    supports_thinking: false,
    supports_reasoning_effort: false,
  });
}

function updateModel(
  providerId: string,
  modelId: string,
  patch: Partial<ModelServiceModel>,
  setDraft: Dispatch<SetStateAction<ModelServicesConfig | null>>,
) {
  setDraft((prev) => {
    if (!prev) {
      return prev;
    }
    let renamedFrom: string | undefined;
    let renamedTo: string | undefined;
    const providers = prev.providers.map((provider) =>
      provider.id === providerId
        ? {
            ...provider,
            models: provider.models.map((model) => {
              if (model.id !== modelId) {
                return model;
              }
              if (Object.hasOwn(patch, "name") && patch.name !== model.name) {
                renamedFrom = model.name;
                renamedTo = patch.name ?? "";
              }
              return { ...model, ...patch };
            }),
          }
        : provider,
    );
    return {
      ...prev,
      defaults:
        renamedFrom && renamedTo
          ? renameDefaultModel(prev.defaults, renamedFrom, renamedTo)
          : prev.defaults,
      providers,
    };
  });
}

function buildHeaderDrafts(config: ModelServicesConfig) {
  return Object.fromEntries(
    config.providers.map((provider) => [provider.id, prettyJson(provider.headers)]),
  );
}

function buildExtraBodyDrafts(config: ModelServicesConfig) {
  return Object.fromEntries(
    config.providers.flatMap((provider) =>
      provider.models.map((model) => [model.id, prettyJson(model.extra_body)]),
    ),
  );
}

function buildRegisteredModels(
  originalConfig: ModelServicesConfig | undefined,
  draft: ModelServicesConfig | null,
) {
  if (!originalConfig || !draft) {
    return [];
  }
  const staticModels = originalConfig.registered_models.filter(
    (model) => model.source === "config",
  );
  const providerModels = draft.providers.flatMap((provider) =>
    provider.models.map((model) => ({
      id: model.id,
      name: model.name,
      display_name: model.display_name ?? model.name,
      model: model.model,
      description: model.description,
      provider: provider.id,
      provider_label: provider.name,
      provider_url: provider.homepage,
      provider_id: provider.id,
      modalities: model.modalities,
      supports_thinking: model.supports_thinking,
      supports_reasoning_effort: model.supports_reasoning_effort,
      supports_vision: model.supports_vision,
      enabled: provider.enabled && model.enabled,
      source: "provider" as const,
    })),
  );
  return [...staticModels, ...providerModels];
}

function normalizeProviderSlug(value: string) {
  return value.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-");
}

function buildProviderEntries(
  draft: ModelServicesConfig | null,
  registeredModels: RegisteredModel[],
): DisplayProviderEntry[] {
  const editableProviders = draft?.providers ?? [];
  const grouped = groupModelsByProvider(registeredModels);
  const matchedEditableProviderIds = new Set<string>();

  const entries: DisplayProviderEntry[] = grouped.map((group) => {
    const editableProvider = editableProviders.find(
      (provider) => deriveProviderKey(provider) === group.key,
    );
    if (editableProvider) {
      matchedEditableProviderIds.add(editableProvider.id);
    }
    const groupModels = group.models as RegisteredModel[];
    return {
      selectionId: editableProvider?.id ?? `group:${group.key}`,
      providerKey: group.key,
      label: editableProvider?.name ?? group.label,
      meta: group,
      editableProvider,
      registeredModels: groupModels,
      staticModels: groupModels.filter((model) => model.source === "config"),
      configuredModalities: group.configuredModalities,
      providerModalities: editableProvider?.modalities ?? group.configuredModalities,
    };
  });

  for (const provider of editableProviders) {
    if (matchedEditableProviderIds.has(provider.id)) {
      continue;
    }
    const meta = getProviderMetaFromProvider(provider);
    entries.push({
      selectionId: provider.id,
      providerKey: meta.key,
      label: provider.name || meta.label,
      meta,
      editableProvider: provider,
      registeredModels: [],
      staticModels: [],
      configuredModalities: [],
      providerModalities: provider.modalities,
    });
  }

  return entries.sort((left, right) => left.label.localeCompare(right.label));
}

function buildDraftModelName(
  providerId: string,
  remoteModelId: string,
  existingNames: Set<string>,
) {
  const base = normalizeProviderSlug(`${providerId}-${remoteModelId}`);
  let candidate = base;
  let suffix = 2;
  while (existingNames.has(candidate)) {
    candidate = `${base}-${suffix}`;
    suffix += 1;
  }
  return candidate;
}

function groupDiscoveredModels(models: DiscoveredProviderModel[]) {
  const groups = new Map<string, DiscoveredProviderModel[]>();

  for (const model of models) {
    const groupName =
      model.owned_by ??
      model.id.split("/")[0] ??
      model.display_name.charAt(0).toUpperCase() ??
      "Other";
    const group = groups.get(groupName) ?? [];
    group.push(model);
    groups.set(groupName, group);
  }

  return Array.from(groups.entries())
    .map(([name, groupModels]) => ({
      name,
      models: groupModels.sort((left, right) =>
        left.display_name.localeCompare(right.display_name),
      ),
    }))
    .sort((left, right) => left.name.localeCompare(right.name));
}

function deriveProviderKey(provider: ModelServiceProvider) {
  if (provider.id && !provider.id.startsWith("provider-")) {
    return normalizeProviderSlug(provider.id);
  }
  return normalizeProviderSlug(getProviderMetaFromProvider(provider).key);
}

function addProviderFromEntry(
  entry: DisplayProviderEntry,
  setDraft: Dispatch<SetStateAction<ModelServicesConfig | null>>,
  setQuery: Dispatch<SetStateAction<string>>,
  setSelectedProviderId: Dispatch<SetStateAction<string | undefined>>,
) {
  const provider = createEmptyProvider();
  provider.id = entry.providerKey === "unknown" ? provider.id : entry.providerKey;
  provider.name = entry.label;
  provider.homepage = entry.meta.homepage ?? "";
  provider.modalities = entry.providerModalities.length > 0
    ? [...entry.providerModalities]
    : [...entry.configuredModalities];

  setDraft((prev) => {
    const next = prev ?? {
      providers: [],
      defaults: {},
      registered_models: [],
    };
    return {
      ...next,
      providers: [...next.providers, provider],
    };
  });
  setQuery("");
  setSelectedProviderId(provider.id);
}

function renameDefaultModel(
  defaults: ModelServiceDefaults,
  fromName: string,
  toName: string,
): ModelServiceDefaults {
  const nextName = toName || undefined;
  return {
    text_model_name: defaults.text_model_name === fromName ? nextName : defaults.text_model_name,
    image_model_name: defaults.image_model_name === fromName ? nextName : defaults.image_model_name,
    video_model_name: defaults.video_model_name === fromName ? nextName : defaults.video_model_name,
    audio_model_name: defaults.audio_model_name === fromName ? nextName : defaults.audio_model_name,
  };
}
