"use client";

import { KeyRoundIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";

import { SettingsSection } from "./settings-section";

type SecretStatuses = Record<string, boolean>;

type DesktopProviderSetting = {
  id: string;
  providerType: string;
  label: string;
  apiKeyEnv: string;
  baseUrl: string;
  defaultModel: string;
};

type ProviderPreset = {
  label: string;
  apiKeyEnv: string;
  baseUrl: string;
  defaultModel: string;
};

const PROVIDER_PRESETS: Record<string, ProviderPreset> = {
  openai: { label: "OpenAI", apiKeyEnv: "OPENAI_API_KEY", baseUrl: "", defaultModel: "gpt-4o" },
  anthropic: { label: "Anthropic", apiKeyEnv: "ANTHROPIC_API_KEY", baseUrl: "", defaultModel: "claude-sonnet-4-20250514" },
  google: { label: "Google Gemini", apiKeyEnv: "GEMINI_API_KEY", baseUrl: "", defaultModel: "gemini-2.5-pro" },
  deepseek: { label: "DeepSeek", apiKeyEnv: "DEEPSEEK_API_KEY", baseUrl: "https://api.deepseek.com/v1", defaultModel: "deepseek-chat" },
  volcengine: { label: "Volcengine (Doubao)", apiKeyEnv: "VOLCENGINE_API_KEY", baseUrl: "https://ark.cn-beijing.volces.com/api/v3", defaultModel: "doubao-seed-1-8-251228" },
  moonshot: { label: "Moonshot (Kimi)", apiKeyEnv: "MOONSHOT_API_KEY", baseUrl: "https://api.moonshot.cn/v1", defaultModel: "kimi-k2.5" },
  minimax: { label: "MiniMax", apiKeyEnv: "MINIMAX_API_KEY", baseUrl: "https://api.minimax.io/v1", defaultModel: "MiniMax-M2.5" },
  openrouter: { label: "OpenRouter", apiKeyEnv: "OPENROUTER_API_KEY", baseUrl: "https://openrouter.ai/api/v1", defaultModel: "" },
  novita: { label: "Novita AI", apiKeyEnv: "NOVITA_API_KEY", baseUrl: "https://api.novita.ai/openai", defaultModel: "" },
  "openai-compatible": { label: "OpenAI-Compatible", apiKeyEnv: "", baseUrl: "", defaultModel: "" },
};

const PROVIDER_TYPE_OPTIONS = Object.entries(PROVIDER_PRESETS).map(([key, preset]) => ({
  value: key,
  label: preset.label,
}));

type DesktopSettings = {
  defaultModel: string | null;
  providers: DesktopProviderSetting[];
};

type DesktopBridge = {
  getDesktopSettings?: () => Promise<DesktopSettings>;
  updateDesktopSettings?: (settings: Partial<DesktopSettings>) => Promise<void>;
  getSecretStatuses?: () => Promise<SecretStatuses>;
  saveSecret?: (provider: string, value: string) => Promise<void>;
  deleteSecret?: (provider: string) => Promise<void>;
};

declare global {
  interface Window {
    deerDesktop?: DesktopBridge;
  }
}

export function ModelSettingsPage() {
  const { t } = useI18n();
  const [secretStatuses, setSecretStatuses] = useState<SecretStatuses>({});
  const [providers, setProviders] = useState<DesktopProviderSetting[]>([]);
  const [providerToDelete, setProviderToDelete] = useState<DesktopProviderSetting | null>(null);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [newProviderType, setNewProviderType] = useState("");
  const [newApiKey, setNewApiKey] = useState("");
  const [newProviderName, setNewProviderName] = useState("");
  const [newBaseUrl, setNewBaseUrl] = useState("");
  const [newModelName, setNewModelName] = useState("");
  const bridge = typeof window === "undefined" ? undefined : window.deerDesktop;

  const isOpenAICompatible = newProviderType === "openai-compatible";
  const selectedPreset = newProviderType ? PROVIDER_PRESETS[newProviderType] : null;
  const existingProviderTypes = new Set(providers.map((p) => p.providerType));

  useEffect(() => {
    void bridge?.getDesktopSettings?.().then((value) => {
      if (!value) return;
      setProviders((value.providers ?? []).filter((p) => p.providerType));
    });
    void bridge?.getSecretStatuses?.().then((value) => setSecretStatuses(value ?? {}));
  }, [bridge]);

  async function refreshSecretStatuses(nextProviders: DesktopProviderSetting[]) {
    const statuses = await bridge?.getSecretStatuses?.();
    setSecretStatuses(
      statuses ??
        Object.fromEntries(nextProviders.map((provider) => [provider.apiKeyEnv, false])),
    );
  }

  async function persistProviders(nextProviders: DesktopProviderSetting[]) {
    setProviders(nextProviders);
    await bridge?.updateDesktopSettings?.({ providers: nextProviders });
    await refreshSecretStatuses(nextProviders);
  }

  async function deleteSecret(provider: DesktopProviderSetting) {
    await bridge?.deleteSecret?.(provider.apiKeyEnv);
    setSecretStatuses((current) => ({ ...current, [provider.apiKeyEnv]: false }));
  }

  async function removeProvider(providerId: string) {
    const targetProvider = providers.find((provider) => provider.id === providerId);
    if (!targetProvider) return;
    await deleteSecret(targetProvider);
    await persistProviders(providers.filter((provider) => provider.id !== providerId));
    setProviderToDelete(null);
  }

  function resetAddDialog() {
    setNewProviderType("");
    setNewApiKey("");
    setNewProviderName("");
    setNewBaseUrl("");
    setNewModelName("");
    setAddDialogOpen(false);
  }

  function handleProviderTypeChange(value: string) {
    setNewProviderType(value);
    const preset = PROVIDER_PRESETS[value];
    if (preset && value !== "openai-compatible") {
      setNewProviderName(preset.label);
      setNewModelName(preset.defaultModel);
      setNewBaseUrl(preset.baseUrl);
    } else {
      setNewProviderName("");
      setNewModelName("");
      setNewBaseUrl("");
    }
  }

  async function handleAddProvider() {
    const preset = PROVIDER_PRESETS[newProviderType];
    if (!preset) return;

    const id = isOpenAICompatible ? `openai-compatible-${Date.now()}` : newProviderType;

    const apiKeyEnv = isOpenAICompatible
      ? `CUSTOM_${id.toUpperCase().replace(/-/g, "_")}_API_KEY`
      : preset.apiKeyEnv;

    const newProvider: DesktopProviderSetting = {
      id,
      providerType: newProviderType,
      label: newProviderName || preset.label,
      apiKeyEnv,
      baseUrl: isOpenAICompatible ? newBaseUrl : preset.baseUrl,
      defaultModel: newModelName || preset.defaultModel,
    };

    const nextProviders = [...providers, newProvider];
    await persistProviders(nextProviders);

    if (newApiKey.trim()) {
      await bridge?.saveSecret?.(apiKeyEnv, newApiKey.trim());
      setSecretStatuses((current) => ({ ...current, [apiKeyEnv]: true }));
    }

    resetAddDialog();
  }

  return (
    <>
      <SettingsSection title={t.settings.models.title} description={t.settings.models.description}>
        <div className="flex flex-col gap-4">
          <div className="flex justify-end absolute top-10 right-6">
            <Button size="sm" onClick={() => setAddDialogOpen(true)}>
              <PlusIcon className="size-4" />
              {t.settings.models.addProvider}
            </Button>
          </div>

          {providers.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <KeyRoundIcon className="text-muted-foreground mb-4 size-10" />
              <div className="text-muted-foreground text-sm">{t.settings.models.emptyProviders}</div>
              <div className="text-muted-foreground mt-1 text-xs">{t.settings.models.emptyProvidersDescription}</div>
            </div>
          )}

          {providers.map((provider) => {
            const configured = secretStatuses[provider.apiKeyEnv] ?? false;
            return (
              <Item className="w-full" variant="outline" key={provider.id}>
                <ItemContent>
                  <ItemTitle>
                    <div className="flex items-center gap-2">
                      <KeyRoundIcon className="size-4" />
                      <div>{provider.label || provider.apiKeyEnv}</div>
                    </div>
                  </ItemTitle>
                  <ItemDescription>
                    {configured ? t.settings.models.configured : t.settings.models.notConfigured}
                  </ItemDescription>
                </ItemContent>
                <ItemActions>
                  <Switch
                    checked={configured}
                    onCheckedChange={(checked) => {
                      if (!checked) {
                        void deleteSecret(provider);
                      }
                    }}
                  />
                  <Button
                    size="icon"
                    variant="ghost"
                    className="text-muted-foreground hover:text-destructive"
                    onClick={() => setProviderToDelete(provider)}
                    aria-label={t.common.delete}
                  >
                    <Trash2Icon className="size-4" />
                  </Button>
                </ItemActions>
              </Item>
            );
          })}
        </div>
      </SettingsSection>

      <Dialog open={addDialogOpen} onOpenChange={(open) => { if (!open) resetAddDialog(); }}>
        <DialogContent className="rounded-2xl">
          <DialogHeader className="text-left">
            <DialogTitle>{t.settings.models.addProviderDialogTitle}</DialogTitle>
            <DialogDescription>{t.settings.models.addProviderDialogDescription}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t.settings.models.providerType}</label>
              <Select value={newProviderType} onValueChange={handleProviderTypeChange}>
                <SelectTrigger>
                  <SelectValue placeholder={t.settings.models.providerTypePlaceholder} />
                </SelectTrigger>
                <SelectContent>
                  {PROVIDER_TYPE_OPTIONS.map((option) => (
                    <SelectItem
                      key={option.value}
                      value={option.value}
                      disabled={option.value !== "openai-compatible" && existingProviderTypes.has(option.value)}
                    >
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {isOpenAICompatible && (
              <div className="space-y-2">
                <label className="text-sm font-medium">{t.settings.models.providerName}</label>
                <Input
                  value={newProviderName}
                  placeholder={t.settings.models.providerNamePlaceholder}
                  onChange={(e) => setNewProviderName(e.target.value)}
                />
              </div>
            )}

            {isOpenAICompatible && (
              <div className="space-y-2">
                <label className="text-sm font-medium">{t.settings.models.baseUrl}</label>
                <Input
                  value={newBaseUrl}
                  placeholder={t.settings.models.baseUrlPlaceholder}
                  onChange={(e) => setNewBaseUrl(e.target.value)}
                />
              </div>
            )}

            {newProviderType && (
              <div className="space-y-2">
                <label className="text-sm font-medium">{t.settings.models.apiKeyPlaceholder}</label>
                <Input
                  type="password"
                  value={newApiKey}
                  placeholder={t.settings.models.apiKeyPlaceholder}
                  onChange={(e) => setNewApiKey(e.target.value)}
                />
              </div>
            )}

            {newProviderType && (
              <div className="space-y-2">
                <label className="text-sm font-medium">{t.settings.models.modelName}</label>
                <Input
                  value={newModelName}
                  placeholder={selectedPreset?.defaultModel || t.settings.models.modelNamePlaceholder}
                  onChange={(e) => setNewModelName(e.target.value)}
                />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" className="rounded-full px-5" onClick={resetAddDialog}>
              {t.common.cancel}
            </Button>
            <Button
              className="rounded-full px-5"
              disabled={!newProviderType || (isOpenAICompatible && (!newBaseUrl.trim() || !newModelName.trim()))}
              onClick={() => void handleAddProvider()}
            >
              {t.settings.models.addProvider}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={providerToDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setProviderToDelete(null);
          }
        }}
      >
        <DialogContent className="rounded-2xl" showCloseButton={false}>
          <DialogHeader className="text-left">
            <DialogTitle>{t.settings.models.deleteProviderConfirmTitle}</DialogTitle>
            <DialogDescription>
              {t.settings.models.deleteProviderConfirmDescription}
            </DialogDescription>
          </DialogHeader>
          {providerToDelete ? (
            <div className="bg-muted/60 rounded-xl border px-4 py-3 text-sm">
              <div className="font-medium text-foreground">{providerToDelete.label}</div>
              <div className="text-muted-foreground mt-1">{providerToDelete.apiKeyEnv}</div>
            </div>
          ) : null}
          <DialogFooter>
            <Button variant="outline" className="rounded-full px-5" onClick={() => setProviderToDelete(null)}>
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              className="rounded-full px-5"
              onClick={() => providerToDelete && void removeProvider(providerToDelete.id)}
            >
              {t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
