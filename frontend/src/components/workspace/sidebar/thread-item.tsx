import {
  FolderPlus,
  MoreHorizontal,
  Pencil,
  Share2,
  Trash2,
} from "lucide-react";
import { Link, useLocation } from "react-router";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import type { AgentThread } from "@/core/threads/types";
import { pathOfThread, titleOfThread } from "@/core/threads/utils";
import { env } from "@/env";

interface ThreadItemProps {
  thread: AgentThread;
  onRename: (threadId: string, currentTitle: string) => void;
  onDelete: (threadId: string) => void;
  onShare: (threadId: string) => void;
  onAssignToProject: (threadId: string) => void;
}

export function ThreadItem({
  thread,
  onRename,
  onDelete,
  onShare,
  onAssignToProject,
}: ThreadItemProps) {
  const { t } = useI18n();
  const location = useLocation();
  const isActive = pathOfThread(thread.thread_id) === location.pathname;

  return (
    <SidebarMenuItem className="group/side-menu-item">
      <SidebarMenuButton isActive={isActive} asChild>
        <div>
          <Link
            className="text-muted-foreground block w-full whitespace-nowrap group-hover/side-menu-item:overflow-hidden"
            to={pathOfThread(thread.thread_id)}
          >
            {titleOfThread(thread)}
          </Link>
          {env.VITE_STATIC_WEBSITE_ONLY !== "true" && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuAction
                  showOnHover
                  className="bg-background/50 hover:bg-background"
                >
                  <MoreHorizontal />
                  <span className="sr-only">{t.common.more}</span>
                </SidebarMenuAction>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                className="w-48 rounded-lg"
                side="right"
                align="start"
              >
                <DropdownMenuItem
                  onSelect={() =>
                    onRename(thread.thread_id, titleOfThread(thread))
                  }
                >
                  <Pencil className="text-muted-foreground" />
                  <span>{t.common.rename}</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => onShare(thread.thread_id)}
                >
                  <Share2 className="text-muted-foreground" />
                  <span>{t.common.share}</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => onAssignToProject(thread.thread_id)}
                >
                  <FolderPlus className="text-muted-foreground" />
                  <span>{t.sidebar.addToProject}</span>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onSelect={() => onDelete(thread.thread_id)}
                >
                  <Trash2 className="text-muted-foreground" />
                  <span>{t.common.delete}</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}
