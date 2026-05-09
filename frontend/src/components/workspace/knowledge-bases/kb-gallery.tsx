"use client";

import { BookOpenIcon, PlusIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { useKnowledgeBases } from "@/core/knowledge-base";

import { KBCard } from "./kb-card";
import { KBFormDialog } from "./kb-form-dialog";

export function KBGallery() {
  const { t } = useI18n();
  const { knowledgeBases, isLoading } = useKnowledgeBases();
  const [createOpen, setCreateOpen] = useState(false);

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
        {isLoading ? (
          <div className="text-muted-foreground flex h-40 items-center justify-center text-sm">
            {t.common.loading}
          </div>
        ) : knowledgeBases.length === 0 ? (
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
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {knowledgeBases.map((kb) => (
              <KBCard key={kb.id} knowledgeBase={kb} />
            ))}
          </div>
        )}
      </div>

      <KBFormDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
