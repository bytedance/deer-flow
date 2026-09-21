"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useFrontendExtensions } from "@/core/extensions/hooks";
import { pluginPages, pluginPageTitle } from "@/core/extensions/pages";
import { useI18n } from "@/core/i18n/hooks";

import { PluginSurfaces } from "./plugin-surfaces";

export function PluginPage({
  namespace,
  surfaceId,
}: {
  namespace: string;
  surfaceId: string;
}) {
  const query = useFrontendExtensions();
  const { locale, t } = useI18n();
  const zh = locale.startsWith("zh");
  const page = pluginPages(query.data ?? []).find(
    ({ contribution, surface }) =>
      contribution.namespace === namespace && surface.id === surfaceId,
  );
  const title = page
    ? pluginPageTitle(page.surface, locale)
    : zh
      ? "扩展页面不可用"
      : "Extension page unavailable";
  return (
    <div className="bg-background flex h-full min-h-0 flex-col">
      <div className="text-muted-foreground flex h-14 shrink-0 items-center gap-3 border-b px-4 text-xs md:px-8">
        <SidebarTrigger className="md:hidden" />
        <span>{t.breadcrumb.workspace}</span>
        <span>/</span>
        <span>{title}</span>
      </div>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl space-y-6 px-5 py-8 md:px-10">
          {query.isPending ? (
            <p role="status">{zh ? "正在加载扩展…" : "Loading extension…"}</p>
          ) : (
            <>
              <h1 className="text-2xl font-semibold">{title}</h1>
              {page ? (
                <PluginSurfaces
                  slot="page"
                  namespace={namespace}
                  surfaceId={surfaceId}
                />
              ) : (
                <div className="space-y-4">
                  <p>
                    {zh
                      ? "此页面未注册，或插件已停用、未能加载。"
                      : "This page is not registered, or its plugin is disabled or unavailable."}
                  </p>
                  <Button
                    variant="outline"
                    onClick={() => window.location.reload()}
                  >
                    {zh ? "重新加载" : "Reload"}
                  </Button>
                  <Button variant="ghost" asChild>
                    <Link href="/workspace/capabilities?tab=extensions">
                      {zh ? "查看扩展" : "View extensions"}
                    </Link>
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
