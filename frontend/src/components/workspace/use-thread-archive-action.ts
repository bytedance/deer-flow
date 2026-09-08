import { toast } from "sonner";

import { useI18n } from "@/core/i18n/hooks";
import { useArchiveThread } from "@/core/threads/archive";

export function useThreadArchiveAction() {
  const { t } = useI18n();
  const mutation = useArchiveThread({
    onSuccess(_data, { threadId, archived }) {
      if (archived) {
        toast.success(t.chats.archiveSuccess, {
          description: t.chats.archiveDescription,
          action: {
            label: t.chats.undoArchive,
            onClick: () => setArchived(threadId, false),
          },
        });
      } else {
        toast.success(t.chats.restoreSuccess);
      }
    },
    onError() {
      toast.error(t.chats.archiveFailed);
    },
  });

  function setArchived(threadId: string, archived: boolean) {
    mutation.mutate({ threadId, archived });
  }

  return { setArchived, isPending: mutation.isPending };
}
