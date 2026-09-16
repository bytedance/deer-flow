"use client";

import { CheckIcon, SendIcon } from "lucide-react";
import dynamic from "next/dynamic";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useI18n } from "@/core/i18n/hooks";
import { useLarkIntegrationStatus } from "@/core/integrations/lark";

import { CapabilityCard, CapabilityIcon } from "./capability-card";
import { MCPPluginManager } from "./mcp-plugin-manager";

const LarkPluginSettings = dynamic(() =>
  import("./lark-plugin-settings").then((module) => module.LarkPluginSettings),
);

export function PluginGallery({ query }: { query: string }) {
  const { t } = useI18n();
  const lark = useLarkIntegrationStatus();
  const [filter, setFilter] = useState("all");
  const [localOpen, setLocalOpen] = useState(false);
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const open = localOpen || params.get("plugin") === "lark";
  function setOpen(value: boolean) {
    setLocalOpen(value);
    if (!value && params.has("plugin")) {
      const next = new URLSearchParams(params);
      next.delete("plugin");
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    }
  }
  const showLark =
    (filter === "all" || lark.data?.installed) &&
    `${t.capabilities.larkName} ${t.capabilities.larkDescription} feishu lark cli`
      .toLowerCase()
      .includes(query.trim().toLowerCase());
  const connected =
    lark.data?.auth.status === "authenticated" && lark.data.auth.verified;
  const larkCard = showLark ? (
    <CapabilityCard
      name={t.capabilities.larkName}
      description={t.capabilities.larkDescription}
      label={t.capabilities.larkTag}
      icon={<CapabilityIcon name="lark" icon={SendIcon} />}
      status={
        lark.isLoading ? (
          t.common.loading
        ) : lark.error ? (
          t.common.error
        ) : (
          <>
            {lark.data?.installed && <CheckIcon className="size-3.5" />}
            {lark.data?.installed
              ? t.capabilities.installed
              : t.capabilities.notInstalled}
          </>
        )
      }
      onDetails={() => setOpen(true)}
      detailsLabel={`${t.capabilities.configure} ${t.capabilities.larkName}`}
    >
      <Button
        size="sm"
        variant="outline"
        className="h-8 rounded-lg text-xs shadow-none"
        onClick={() => setOpen(true)}
      >
        {connected
          ? t.capabilities.manage
          : lark.data?.installed
            ? t.capabilities.connect
            : t.common.install}
      </Button>
    </CapabilityCard>
  ) : null;
  const toolbar = (
    <Tabs value={filter} onValueChange={setFilter}>
      <TabsList className="bg-muted/50 h-9 rounded-lg">
        <TabsTrigger className="rounded-md px-4 text-xs" value="all">
          {t.capabilities.allPlugins}
        </TabsTrigger>
        <TabsTrigger className="rounded-md px-4 text-xs" value="installed">
          {t.capabilities.installed}
        </TabsTrigger>
      </TabsList>
    </Tabs>
  );
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-base font-semibold">
          {t.capabilities.availablePlugins}
        </h2>
        <p className="text-muted-foreground mt-1.5 text-sm">
          {t.capabilities.pluginHint}
        </p>
      </div>
      <MCPPluginManager query={query} toolbar={toolbar}>
        {larkCard}
      </MCPPluginManager>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          className="max-h-[85vh] overflow-y-auto sm:max-w-3xl"
          aria-describedby={undefined}
        >
          <DialogHeader>
            <DialogTitle>{t.capabilities.pluginSettings}</DialogTitle>
          </DialogHeader>
          <LarkPluginSettings />
        </DialogContent>
      </Dialog>
    </div>
  );
}
