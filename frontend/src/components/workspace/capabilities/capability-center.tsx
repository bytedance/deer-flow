"use client";

import { BlocksIcon, SearchIcon, SparklesIcon } from "lucide-react";
import dynamic from "next/dynamic";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Input } from "@/components/ui/input";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useI18n } from "@/core/i18n/hooks";

const PluginGallery = dynamic(() =>
  import("./plugin-gallery").then((module) => module.PluginGallery),
);
const SkillGallery = dynamic(() =>
  import("./skill-gallery").then((module) => module.SkillGallery),
);

export function CapabilityCenter() {
  const { t } = useI18n();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tab = params.get("tab") === "skills" ? "skills" : "plugins";
  const [query, setQuery] = useState("");
  function changeTab(value: string) {
    setQuery("");
    router.replace(`${pathname}?tab=${value}`, { scroll: false });
  }
  return (
    <div className="bg-background flex h-full min-h-0 flex-col">
      <div className="text-muted-foreground flex h-14 shrink-0 items-center gap-3 border-b px-4 text-xs md:px-8">
        <SidebarTrigger className="md:hidden" />
        <span>{t.breadcrumb.workspace}</span>
        <span className="opacity-40">/</span>
        <span className="text-foreground">{t.capabilities.title}</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl px-5 py-8 md:px-10 md:py-10">
          <header className="mb-8 flex flex-wrap items-end justify-between gap-5">
            <div>
              <h1 className="text-[28px] font-semibold tracking-tight">
                {t.capabilities.title}
              </h1>
              <p className="text-muted-foreground mt-2 text-sm leading-6">
                {t.capabilities.description}
              </p>
            </div>
            <div className="relative w-full md:w-72">
              <SearchIcon className="text-muted-foreground pointer-events-none absolute top-3 left-3 size-4" />
              <Input
                className="bg-muted/30 h-10 rounded-xl pl-9 shadow-none"
                aria-label={
                  tab === "plugins"
                    ? t.capabilities.searchPlugins
                    : t.capabilities.searchSkills
                }
                placeholder={
                  tab === "plugins"
                    ? t.capabilities.searchPlugins
                    : t.capabilities.searchSkills
                }
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
          </header>
          <Tabs value={tab} onValueChange={changeTab} className="mb-7 border-b">
            <TabsList variant="line" className="h-12 gap-7">
              <TabsTrigger value="plugins" className="gap-2 px-1 pb-4 text-sm">
                <BlocksIcon className="size-4" />
                {t.capabilities.plugins}
              </TabsTrigger>
              <TabsTrigger value="skills" className="gap-2 px-1 pb-4 text-sm">
                <SparklesIcon className="size-4" />
                {t.capabilities.skills}
              </TabsTrigger>
            </TabsList>
          </Tabs>
          {tab === "plugins" ? (
            <PluginGallery query={query} />
          ) : (
            <SkillGallery query={query} />
          )}
        </div>
      </div>
    </div>
  );
}
