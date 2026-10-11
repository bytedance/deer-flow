"use client";

import { CopyIcon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";

export function SkillUsageCopyAction({ content }: { content: string }) {
  const { t } = useI18n();
  return (
    <Button
      size="icon-sm"
      variant="ghost"
      aria-label={t.skillUsage.copy}
      title={t.skillUsage.copy}
      onClick={() => {
        void writeTextToClipboard(content).then((copied) => {
          if (copied) toast.success(t.clipboard.copiedToClipboard);
          else toast.error(t.clipboard.failedToCopyToClipboard);
        });
      }}
    >
      <CopyIcon className="size-4" />
    </Button>
  );
}
