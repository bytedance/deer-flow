"use client";

import { BlocksIcon, PuzzleIcon, SearchIcon, SparklesIcon } from "lucide-react";
import dynamic from "next/dynamic";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WorkspaceSidebarTrigger } from "@/components/workspace/workspace-sidebar-trigger";
import { useI18n } from "@/core/i18n/hooks";

const PluginGallery = dynamic(() =>
  import("./plugin-gallery").then((module) => module.PluginGallery),
);
const ExtensionGallery = dynamic(() =>
  import("./extension-gallery").then((module) => module.ExtensionGallery),
);
const SkillGallery = dynamic(() =>
  import("./skill-gallery").then((module) => module.SkillGallery),
);

// Do not accept search input before React can update the directory. A replayed
// change on blur can move the install button between pointerdown and click.
const subscribeHydration = () => () => undefined;
const clientHydrated = () => true;
const serverHydrated = () => false;

// Scrolls only the strip. scrollIntoView would also move the page, pulling it
// back up if the strip resizes after the user has scrolled past it.
function revealActiveTab(strip: HTMLElement) {
  const tab = strip.querySelector('[role="tab"][data-state="active"]');
  if (!tab) return;
  const tabBox = tab.getBoundingClientRect();
  const stripBox = strip.getBoundingClientRect();
  if (tabBox.left < stripBox.left) {
    strip.scrollLeft -= Math.ceil(stripBox.left - tabBox.left);
  } else if (tabBox.right > stripBox.right) {
    strip.scrollLeft += Math.ceil(tabBox.right - stripBox.right);
  }
}

export function CapabilityCenter() {
  const hydrated = useSyncExternalStore(
    subscribeHydration,
    clientHydrated,
    serverHydrated,
  );
  const { t } = useI18n();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const requestedTab = params.get("tab");
  const tab =
    requestedTab === "skills"
      ? "skills"
      : requestedTab === "extensions"
        ? "extensions"
        : "plugins";
  // The detail view shows one extension, so there is no directory to filter.
  const showSearch = !(tab === "extensions" && params.get("extension"));
  const [query, setQuery] = useState("");
  // The tab strip scrolls on narrow screens. Keep the active tab visible when
  // the tab changes or the strip resizes, and leave manual swipes alone.
  const tabsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const strip = tabsRef.current;
    if (!strip) return;
    // A new observation reports the current size at once, covering tab changes.
    const observer = new ResizeObserver(() => revealActiveTab(strip));
    observer.observe(strip);
    return () => observer.disconnect();
  }, [tab]);
  function changeTab(value: string) {
    setQuery("");
    router.replace(`${pathname}?tab=${value}`, { scroll: false });
  }
  return (
    <div className="bg-background flex h-full min-h-0 flex-col">
      <div className="text-muted-foreground flex h-14 shrink-0 items-center gap-3 border-b px-4 text-xs md:px-8">
        <WorkspaceSidebarTrigger className="md:hidden" />
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
            {showSearch && (
              <div className="relative w-full md:w-80">
                <SearchIcon className="text-muted-foreground pointer-events-none absolute top-3 left-3 size-4" />
                <Input
                  disabled={!hydrated}
                  className="bg-muted/30 h-10 rounded-xl pl-9 shadow-none"
                  aria-label={
                    tab === "extensions"
                      ? t.extensions.search
                      : tab === "skills"
                        ? t.capabilities.searchSkills
                        : t.capabilities.searchPlugins
                  }
                  placeholder={
                    tab === "extensions"
                      ? t.extensions.search
                      : tab === "skills"
                        ? t.capabilities.searchSkills
                        : t.capabilities.searchPlugins
                  }
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </div>
            )}
          </header>
          <Tabs
            ref={tabsRef}
            value={tab}
            onValueChange={changeTab}
            className="mb-7 overflow-x-auto border-b pb-px [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          >
            <TabsList variant="line" className="h-12 gap-7">
              <TabsTrigger value="plugins" className="gap-2 px-1 pb-4 text-sm">
                <BlocksIcon className="size-4" />
                {t.capabilities.toolsAndIntegrations}
              </TabsTrigger>
              <TabsTrigger value="skills" className="gap-2 px-1 pb-4 text-sm">
                <SparklesIcon className="size-4" />
                {t.capabilities.skills}
              </TabsTrigger>
              <TabsTrigger
                value="extensions"
                className="gap-2 px-1 pb-4 text-sm"
              >
                <PuzzleIcon className="size-4" />
                {t.extensions.title}
              </TabsTrigger>
            </TabsList>
          </Tabs>
          {tab === "extensions" ? (
            <ExtensionGallery query={query} />
          ) : tab !== "skills" ? (
            <PluginGallery query={query} />
          ) : (
            <SkillGallery query={query} />
          )}
        </div>
      </div>
    </div>
  );
}
