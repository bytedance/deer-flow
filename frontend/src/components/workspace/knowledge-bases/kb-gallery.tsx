"use client";

import { BookOpenIcon, HeartPulseIcon, PlusIcon } from "@/components/ui/icons";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useI18n } from "@/core/i18n/hooks";
import {
  useAdminKnowledgeBases,
  useKnowledgeBases,
} from "@/core/knowledge-base";
import type { KnowledgeBase } from "@/core/knowledge-base";

import { KBCard } from "./kb-card";
import { KBFormDialog } from "./kb-form-dialog";
import { KbHealthSummary } from "./kb-health-summary";

type TabValue = "all" | "mine" | "tenant" | "public" | "admin" | "health";

export function KBGallery() {
  const { t } = useI18n();
  const { knowledgeBases, isLoading } = useKnowledgeBases();
  const [createOpen, setCreateOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<TabValue>("all");

  const { knowledgeBases: adminKBs, isLoading: adminLoading } =
    useAdminKnowledgeBases({ enabled: activeTab === "admin" });

  const filteredKBs = useMemo(() => {
    if (activeTab === "admin") return adminKBs;
    if (activeTab === "all") return knowledgeBases;
    const visibilityMap: Record<string, string> = {
      mine: "private",
      tenant: "tenant",
      public: "public",
    };
    const target = visibilityMap[activeTab];
    return knowledgeBases.filter((kb) => kb.visibility === target);
  }, [activeTab, knowledgeBases, adminKBs]);

  const loading = activeTab === "admin" ? adminLoading : isLoading;

  function renderGrid(items: KnowledgeBase[]) {
    if (loading) {
      return (
        <div className="text-muted-foreground flex h-40 items-center justify-center text-sm">
          {t.common.loading}
        </div>
      );
    }
    if (items.length === 0) {
      return (
        <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
          <div className="bg-muted flex h-14 w-14 items-center justify-center rounded-full">
            <BookOpenIcon className="text-muted-foreground h-7 w-7" />
          </div>
          <div>
            <p className="font-medium">{t.knowledgeBase.emptyTitle}</p>
            <p className="text-muted-foreground mt-1 text-sm">
              {t.knowledgeBase.emptyDescription}
            </p>
          </div>
          <Button
            variant="outline"
            className="mt-2"
            onClick={() => setCreateOpen(true)}
          >
            <PlusIcon className="mr-1.5 h-4 w-4" />
            {t.knowledgeBase.newKnowledgeBase}
          </Button>
        </div>
      );
    }
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {items.map((kb) => (
          <KBCard key={kb.id} knowledgeBase={kb} />
        ))}
      </div>
    );
  }

  function renderHealth() {
    return <KbHealthSummary />;
  }

  return (
    <div className="flex size-full flex-col">
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold">{t.knowledgeBase.title}</h1>
          <p className="text-muted-foreground mt-0.5 text-sm">
            {t.knowledgeBase.description}
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <PlusIcon className="mr-1.5 h-4 w-4" />
          {t.knowledgeBase.newKnowledgeBase}
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <Tabs
          value={activeTab}
          onValueChange={(v) => setActiveTab(v as TabValue)}
        >
          <TabsList className="mb-4">
            <TabsTrigger value="all">{t.knowledgeBase.tabAll}</TabsTrigger>
            <TabsTrigger value="mine">{t.knowledgeBase.tabMine}</TabsTrigger>
            <TabsTrigger value="tenant">
              {t.knowledgeBase.tabTenant}
            </TabsTrigger>
            <TabsTrigger value="public">
              {t.knowledgeBase.tabPublic}
            </TabsTrigger>
            <TabsTrigger value="admin">{t.knowledgeBase.tabAdmin}</TabsTrigger>
            <TabsTrigger value="health">
              <HeartPulseIcon className="mr-1 h-3.5 w-3.5" />
              {t.knowledgeBase.tabHealth}
            </TabsTrigger>
          </TabsList>

          <TabsContent value={activeTab}>
            {activeTab === "health" ? renderHealth() : renderGrid(filteredKBs)}
          </TabsContent>
        </Tabs>
      </div>

      <KBFormDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
