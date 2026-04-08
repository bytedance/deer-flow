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
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";

import { SettingsSection } from "./settings-section";

type SecretStatuses = Record<string, boolean>;

type DesktopProviderSetting = {
  id: string;
  label: string;
  apiKeyEnv: string;
  baseUrl: string;
};

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

const EMPTY_PROVIDER: DesktopProviderSetting = {
  id: "",
  label: "",
  apiKeyEnv: "",
  baseUrl: "",
};

export function ModelSettingsPage() {
  const { t } = useI18n();
  const [secretStatuses, setSecretStatuses] = useState<SecretStatuses>({});
  const [providers, setProviders] = useState<DesktopProviderSetting[]>([]);
  const [providerToDelete, setProviderToDelete] = useState<DesktopProviderSetting | null>(null);
  const bridge = typeof window === "undefined" ? undefined : window.deerDesktop;

  useEffect(() => {
    void bridge?.getDesktopSettings?.().then((value) => {
      if (!value) return;
      setProviders(value.providers ?? []);
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

  async function addProvider() {
    const nextProviders = [
      ...providers,
      {
        ...EMPTY_PROVIDER,
        id: `provider-${Date.now()}`,
      },
    ];
    await persistProviders(nextProviders);
  }

  async function removeProvider(providerId: string) {
    const targetProvider = providers.find((provider) => provider.id === providerId);
    if (!targetProvider) return;

    await deleteSecret(targetProvider);
    await persistProviders(providers.filter((provider) => provider.id !== providerId));
    setProviderToDelete(null);
  }

  return (
    <>
      <SettingsSection title={t.settings.models.title} description={t.settings.models.description}>
        <div className="flex flex-col gap-4">
          <div className="flex justify-end absolute top-10 right-6">
            <Button size="sm" onClick={() => void addProvider()}>
              <PlusIcon className="size-4" />
              {t.settings.models.addProvider}
            </Button>
          </div>

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
                  <ItemDescription>{configured ? t.settings.models.configured : t.settings.models.notConfigured}</ItemDescription>
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
