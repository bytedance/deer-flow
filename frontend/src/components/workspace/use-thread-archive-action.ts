import { toast } from "sonner";

import { useI18n } from "@/core/i18n/hooks";
import { useArchiveThread } from "@/core/threads/archive";

export function useThreadArchiveAction() {
  const { t } = useI18n();
  const mutation = useArchiveThread();

  function setArchived(threadId: string, archived: boolean) {
    mutation.mutate(
      { threadId, archived },
      {
        onSuccess() {
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
      },
    );
  }

  return { setArchived, isPending: mutation.isPending };
}
