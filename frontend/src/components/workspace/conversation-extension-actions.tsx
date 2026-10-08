"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/core/auth/AuthProvider";
import { resolveConversationActions } from "@/core/extensions/actions";
import type {
  ConversationAction,
  ConversationActionContext,
  FrontendContribution,
  FrontendExtension,
} from "@/core/extensions/contracts";
import {
  useFrontendServices,
  useFrontendExtensions,
} from "@/core/extensions/hooks";
import {
  extensionIcon,
  activeFrontendExtensions,
} from "@/core/extensions/registry";
import { bindFrontendServices } from "@/core/extensions/services";
import { useI18n } from "@/core/i18n/hooks";

import { Tooltip } from "./tooltip";

/** Shared host slot used by the chat toolbar AND every sidebar conversation. */
export function ConversationExtensionActions(props: {
  context: ConversationActionContext;
  placement?: "toolbar" | "menu";
}) {
  const { user } = useAuth();
  return (
    <ScopedConversationActions
      key={JSON.stringify([user?.id, props.context.thread.thread_id])}
      {...props}
    />
  );
}

function ScopedConversationActions({
  context,
  placement = "toolbar",
}: {
  context: ConversationActionContext;
  placement?: "toolbar" | "menu";
}) {
  const { t, locale } = useI18n();
  const query = useFrontendExtensions();
  const services = useFrontendServices();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const pending = useRef(new Set<AbortController>());
  useEffect(() => {
    const tasks = pending.current;
    return () => {
      for (const task of tasks) task.abort();
      tasks.clear();
    };
  }, []);
  const entries = query.isError ? [] : (query.data ?? []);

  async function execute(
    action: ConversationAction,
    contribution: FrontendContribution,
    extension: FrontendExtension,
  ) {
    const controller = new AbortController();
    pending.current.add(controller);
    setBusy(true);
    try {
      await action.execute(
        context,
        bindFrontendServices(services, contribution, controller.signal, {
          pageIds: (extension.surfaces ?? [])
            .filter((surface) => surface.slot === "page")
            .map((surface) => surface.id),
          navigate: (path) => router.push(path),
        }),
      );
    } catch {
      if (!controller.signal.aborted) toast.error(t.extensions.actionFailed);
    } finally {
      pending.current.delete(controller);
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return activeFrontendExtensions(entries).map(
    ({ contribution, extension }) => {
      if (context.messages?.length === 0) return null;
      const group = resolveConversationActions(
        extension,
        contribution,
        t,
        locale,
      );
      if (!group) return null;
      const actions = group.actions;
      const GroupIcon = extensionIcon(group.icon);
      const items = actions.map((action) => {
        const Icon = extensionIcon(action.icon);
        return (
          <DropdownMenuItem
            key={action.id}
            disabled={busy}
            onSelect={() => void execute(action, contribution, extension)}
          >
            <Icon className="text-muted-foreground" />
            <span>{action.label}</span>
          </DropdownMenuItem>
        );
      });
      if (placement === "menu")
        return (
          <DropdownMenuSub key={contribution.namespace}>
            <DropdownMenuSubTrigger>
              <GroupIcon className="text-muted-foreground" />
              <span>{group.label}</span>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>{items}</DropdownMenuSubContent>
          </DropdownMenuSub>
        );
      return (
        <DropdownMenu key={contribution.namespace}>
          <Tooltip content={group.label}>
            <DropdownMenuTrigger asChild>
              <Button
                aria-label={group.label}
                className="text-muted-foreground hover:text-foreground"
                variant="ghost"
                disabled={busy}
              >
                <GroupIcon />
                <span className="hidden sm:inline">{group.label}</span>
              </Button>
            </DropdownMenuTrigger>
          </Tooltip>
          <DropdownMenuContent align="end">{items}</DropdownMenuContent>
        </DropdownMenu>
      );
    },
  );
}
