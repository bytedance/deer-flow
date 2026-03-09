import { useCallback, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { SidebarGroupContent } from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import {
  useAssignThreadToProject,
  useCreateProject,
  useDeleteProject,
  useProjects,
  useRenameProject,
} from "@/core/projects/hooks";
import {
  getLocalSettings,
  saveLocalSettings,
} from "@/core/settings/local";
import {
  useDeleteThread,
  useRenameThread,
  useThreads,
} from "@/core/threads/hooks";
import { titleOfThread } from "@/core/threads/utils";

import { AssignToProjectDialog } from "./assign-to-project-dialog";
import { DateGroupedThreadList } from "./date-grouped-thread-list";
import { ProjectGroupedThreadList } from "./project-grouped-thread-list";
import { SidebarViewToggle } from "./sidebar-view-toggle";

export function SidebarThreadList() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const { threadId: threadIdFromPath } = useParams<{ threadId: string }>();

  // Data
  const { data: threads = [] } = useThreads();
  const { data: projects = [] } = useProjects();

  // Mutations
  const { mutate: deleteThread } = useDeleteThread();
  const { mutate: renameThread } = useRenameThread();
  const { mutate: createProject } = useCreateProject();
  const { mutate: renameProject } = useRenameProject();
  const { mutate: deleteProject } = useDeleteProject();
  const { mutate: assignThreadToProject } = useAssignThreadToProject();

  // View mode state
  const [viewMode, setViewMode] = useState<"date" | "project">(() => {
    return getLocalSettings().layout.sidebar_view_mode;
  });

  const handleViewModeChange = useCallback((mode: "date" | "project") => {
    setViewMode(mode);
    const settings = getLocalSettings();
    settings.layout.sidebar_view_mode = mode;
    saveLocalSettings(settings);
  }, []);

  // Search state
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [debounceTimer, setDebounceTimer] = useState<ReturnType<typeof setTimeout> | null>(null);

  const handleSearchChange = useCallback(
    (query: string) => {
      setSearchQuery(query);
      if (debounceTimer) clearTimeout(debounceTimer);
      const timer = setTimeout(() => setDebouncedSearch(query), 300);
      setDebounceTimer(timer);
    },
    [debounceTimer],
  );

  // Filter threads by search
  const filteredThreads = useMemo(() => {
    if (!debouncedSearch) return threads;
    const lower = debouncedSearch.toLowerCase();
    return threads.filter((thread) =>
      titleOfThread(thread).toLowerCase().includes(lower),
    );
  }, [threads, debouncedSearch]);

  // Rename dialog state
  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameThreadId, setRenameThreadId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  // Assign to project dialog state
  const [assignDialog, setAssignDialog] = useState<{
    open: boolean;
    threadId: string;
  }>({ open: false, threadId: "" });

  // Handlers
  const handleDelete = useCallback(
    (threadId: string) => {
      deleteThread({ threadId });
      if (threadId === threadIdFromPath) {
        const threadIndex = threads.findIndex((t) => t.thread_id === threadId);
        let nextThreadId = "new";
        if (threadIndex > -1) {
          if (threads[threadIndex + 1]) {
            nextThreadId = threads[threadIndex + 1]!.thread_id;
          } else if (threads[threadIndex - 1]) {
            nextThreadId = threads[threadIndex - 1]!.thread_id;
          }
        }
        void navigate(`/workspace/chats/${nextThreadId}`);
      }
    },
    [deleteThread, navigate, threadIdFromPath, threads],
  );

  const handleRenameClick = useCallback(
    (threadId: string, currentTitle: string) => {
      setRenameThreadId(threadId);
      setRenameValue(currentTitle);
      setRenameDialogOpen(true);
    },
    [],
  );

  const handleRenameSubmit = useCallback(() => {
    if (renameThreadId && renameValue.trim()) {
      renameThread({ threadId: renameThreadId, title: renameValue.trim() });
      setRenameDialogOpen(false);
      setRenameThreadId(null);
      setRenameValue("");
    }
  }, [renameThread, renameThreadId, renameValue]);

  const handleShare = useCallback(
    async (threadId: string) => {
      const VERCEL_URL = "https://thinktank-ai.vercel.app";
      const isLocalhost =
        window.location.hostname === "localhost" ||
        window.location.hostname === "127.0.0.1";
      const baseUrl = isLocalhost ? VERCEL_URL : window.location.origin;
      const shareUrl = `${baseUrl}/workspace/chats/${threadId}`;
      try {
        await navigator.clipboard.writeText(shareUrl);
        toast.success(t.clipboard.linkCopied);
      } catch {
        toast.error(t.clipboard.failedToCopyToClipboard);
      }
    },
    [t],
  );

  const handleAssignToProject = useCallback((threadId: string) => {
    setAssignDialog({ open: true, threadId });
  }, []);

  const handleAssignConfirm = useCallback(
    (projectId: string | null) => {
      assignThreadToProject({
        threadId: assignDialog.threadId,
        projectId,
      });
    },
    [assignThreadToProject, assignDialog.threadId],
  );

  const handleCreateProject = useCallback(
    (name: string) => {
      createProject({ name });
    },
    [createProject],
  );

  const handleRenameProject = useCallback(
    (projectId: string, name: string) => {
      renameProject({ projectId, name });
    },
    [renameProject],
  );

  const handleDeleteProject = useCallback(
    (projectId: string, deleteSessions: boolean) => {
      if (deleteSessions) {
        const projectThreads = threads.filter(
          (th) => th.project_id === projectId,
        );
        for (const thread of projectThreads) {
          deleteThread({ threadId: thread.thread_id });
        }
      }
      deleteProject({ projectId });
    },
    [deleteProject, deleteThread, threads],
  );

  if (threads.length === 0) {
    return null;
  }

  // Get current thread's project_id for the assign dialog
  const assignThread = threads.find(
    (t) => t.thread_id === assignDialog.threadId,
  );

  return (
    <>
      <SidebarGroupContent className="group-data-[collapsible=icon]:pointer-events-none group-data-[collapsible=icon]:-mt-8 group-data-[collapsible=icon]:opacity-0">
        <SidebarViewToggle
          viewMode={viewMode}
          onViewModeChange={handleViewModeChange}
          searchQuery={searchQuery}
          onSearchChange={handleSearchChange}
        />

        {viewMode === "date" ? (
          <DateGroupedThreadList
            threads={filteredThreads}
            onRename={handleRenameClick}
            onDelete={handleDelete}
            onShare={handleShare}
            onAssignToProject={handleAssignToProject}
          />
        ) : (
          <ProjectGroupedThreadList
            threads={filteredThreads}
            projects={projects}
            onRename={handleRenameClick}
            onDelete={handleDelete}
            onShare={handleShare}
            onAssignToProject={handleAssignToProject}
            onCreateProject={handleCreateProject}
            onRenameProject={handleRenameProject}
            onDeleteProject={handleDeleteProject}
          />
        )}
      </SidebarGroupContent>

      {/* Rename Thread Dialog */}
      <Dialog open={renameDialogOpen} onOpenChange={setRenameDialogOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.common.rename}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Input
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              placeholder={t.common.rename}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleRenameSubmit();
              }}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRenameDialogOpen(false)}
            >
              {t.common.cancel}
            </Button>
            <Button onClick={handleRenameSubmit}>{t.common.save}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Assign to Project Dialog */}
      <AssignToProjectDialog
        open={assignDialog.open}
        onOpenChange={(open) =>
          setAssignDialog((prev) => ({ ...prev, open }))
        }
        currentProjectId={assignThread?.project_id ?? null}
        projects={projects}
        onAssign={handleAssignConfirm}
        onCreateProject={handleCreateProject}
      />
    </>
  );
}
