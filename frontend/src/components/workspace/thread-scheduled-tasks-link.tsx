import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";

export function ThreadScheduledTasksLink({ threadId }: { threadId: string }) {
  const { t } = useI18n();
  return (
    <Button variant="outline" size="sm" asChild>
      <Link
        href={`/workspace/scheduled-tasks?thread_id=${encodeURIComponent(threadId)}`}
      >
        {t.sidebar.scheduledTasks}
      </Link>
    </Button>
  );
}
