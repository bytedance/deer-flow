"use client";

import { ArrowLeftIcon, ChevronRightIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useFrontendExtensions } from "@/core/extensions/hooks";
import { extensionIcon } from "@/core/extensions/registry";
import { useI18n } from "@/core/i18n/hooks";

import { PluginRow } from "./plugin-directory";

export function ExtensionGallery({ query = "" }: { query?: string }) {
  const { locale } = useI18n();
  const zh = locale.startsWith("zh");
  const publicQuery = useFrontendExtensions();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const selected = params.get("extension");
  const entries = publicQuery.data ?? [];
  const source = publicQuery;
  function select(namespace?: string) {
    const next = new URLSearchParams(params);
    next.set("tab", "extensions");
    if (namespace) next.set("extension", namespace);
    else next.delete("extension");
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }
  if (source.isPending)
    return <p role="status">{zh ? "正在加载扩展…" : "Loading extensions…"}</p>;
  if (source.isError)
    return (
      <div role="alert">
        <p>{zh ? "扩展暂不可用。" : "Extensions unavailable."}</p>
        <Button variant="outline" onClick={() => void source.refetch()}>
          {zh ? "重试" : "Retry"}
        </Button>
      </div>
    );
  const reload = (
    <Button variant="outline" onClick={() => window.location.reload()}>
      {zh ? "重新加载扩展（刷新页面）" : "Reload extensions (refresh page)"}
    </Button>
  );
  if (selected) {
    const entry = entries.find((item) => item.namespace === selected);
    return (
      <div className="space-y-6">
        {reload}
        <Button variant="ghost" onClick={() => select()}>
          <ArrowLeftIcon />
          {zh ? "全部扩展" : "All extensions"}
        </Button>
        {!entry ? (
          <p>
            {zh ? "此扩展未安装或已移除。" : "This extension is not installed."}
          </p>
        ) : (
          <div className="max-w-3xl space-y-4">
            <h2 className="text-2xl font-semibold">{entry.title}</h2>
            <p className="text-muted-foreground">{entry.description}</p>
            <p>
              {entry.settings.enabled === true
                ? zh
                  ? "已启用 · 由管理员管理"
                  : "Enabled · Managed by your administrator"
                : zh
                  ? "已停用 · 由管理员管理"
                  : "Disabled · Managed by your administrator"}
            </p>
          </div>
        )}
      </div>
    );
  }
  const visible = entries.filter((entry) =>
    `${entry.title} ${entry.description}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );
  return (
    <div className="space-y-5">
      {reload}
      <p className="text-muted-foreground text-sm">
        {zh
          ? "界面和浏览器功能在手动刷新后更新；安装、启停和配置由部署管理员通过配置文件或 CLI 管理。"
          : "Interface and browser features update on manual reload. Installation, activation and configuration are managed through deployment configuration or the CLI."}
      </p>
      <div className="grid gap-x-10 md:grid-cols-2">
        {visible.map((entry) => {
          const loaded = publicQuery.data?.find(
            (item) => item.namespace === entry.namespace,
          );
          const Icon = extensionIcon(loaded?.extension?.icon);
          return (
            <PluginRow
              key={entry.namespace}
              name={entry.title}
              description={entry.description}
              icon={
                <div className="bg-muted flex size-12 shrink-0 items-center justify-center rounded-xl">
                  <Icon className="size-6" />
                </div>
              }
              label={
                loaded?.error
                  ? zh
                    ? "当前页面加载失败"
                    : "Page module unavailable"
                  : entry.settings.enabled === true
                    ? zh
                      ? "已启用"
                      : "Enabled"
                    : zh
                      ? "已停用"
                      : "Disabled"
              }
              onDetails={() => select(entry.namespace)}
              detailsLabel={zh ? `查看 ${entry.title}` : `View ${entry.title}`}
            >
              <Button
                variant="ghost"
                size="icon"
                aria-label={zh ? `打开 ${entry.title}` : `Open ${entry.title}`}
                onClick={() => select(entry.namespace)}
              >
                <ChevronRightIcon />
              </Button>
            </PluginRow>
          );
        })}
      </div>
      {!visible.length && (
        <p role="status" className="text-muted-foreground py-8">
          {zh ? "没有匹配的已安装扩展。" : "No matching installed extensions."}
        </p>
      )}
    </div>
  );
}
