"use client";

import { BotIcon, Trash2Icon } from "@/components/ui/icons";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
import { Switch } from "@/components/ui/switch";
import {
  isAgentAvailable,
  useDeleteAgent,
  useGroupedAgents,
  useSetAgentEnabled,
} from "@/core/agents";
import type { Agent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";

import { SettingsSection } from "./settings-section";

export function AgentSettingsPage({ onClose }: { onClose?: () => void } = {}) {
  const { t } = useI18n();
  const { groups, isLoading, error } = useGroupedAgents();
  return (
    <SettingsSection
      title={t.agents.title}
      description={t.agents.description}
    >
      {isLoading ? (
        <div className="text-muted-foreground text-sm">{t.common.loading}</div>
      ) : error ? (
        <div>Error: {error.message}</div>
      ) : (
        <AgentSettingsList groups={groups} onClose={onClose} />
      )}
    </SettingsSection>
  );
}

function AgentSettingsList({
  groups,
  onClose,
}: {
  groups: { label: string; source: string; agents: Agent[] }[];
  onClose?: () => void;
}) {
  const { t } = useI18n();
  const router = useRouter();
  const allAgents = groups.flatMap((g) => g.agents);

  const handleCreateAgent = () => {
    onClose?.();
    router.push("/workspace/agents/new");
  };

  return (
    <div className="flex w-full flex-col gap-6">
      <header className="flex justify-end">
        <Button size="sm" onClick={handleCreateAgent}>
          <BotIcon className="size-4" />
          {t.agents.newAgent}
        </Button>
      </header>
      {groups.length === 0 && (
        <div className="text-muted-foreground py-8 text-center text-sm">
          {t.agents.emptyTitle}
        </div>
      )}
      {groups.map((group) => {
        const sorted = sortWithChildren(group.agents);
        return (
          <div key={group.source} className="flex flex-col gap-2">
            <h3 className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
              {group.label}
            </h3>
            {sorted.map((agent) => (
              <AgentSettingsItem
                key={agent.name}
                agent={agent}
                allAgents={allAgents}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
}

function sortWithChildren(agents: Agent[]): Agent[] {
  const parents = agents.filter((a) => !a.parent);
  const childMap = new Map<string, Agent[]>();
  for (const agent of agents) {
    if (agent.parent) {
      const list = childMap.get(agent.parent) ?? [];
      list.push(agent);
      childMap.set(agent.parent, list);
    }
  }
  const result: Agent[] = [];
  for (const parent of parents) {
    result.push(parent);
    const children = childMap.get(parent.name);
    if (children) result.push(...children);
  }
  return result;
}

function AgentSettingsItem({
  agent,
  allAgents,
}: {
  agent: Agent;
  allAgents: Agent[];
}) {
  const { t } = useI18n();
  const { mutate: setEnabled } = useSetAgentEnabled();
  const deleteAgent = useDeleteAgent();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const available = isAgentAvailable(agent, allAgents);
  const isChild = !!agent.parent;

  async function handleDelete() {
    try {
      await deleteAgent.mutateAsync(agent.name);
      toast.success(t.agents.deleteSuccess);
      setDeleteOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <Item className={`w-full ${isChild ? "ml-6" : ""}`} variant="outline">
        <ItemContent>
          <ItemTitle>
            <div className="flex items-center gap-2">
              <span className="text-lg">
                {agent.icon ?? <BotIcon className="h-4 w-4" />}
              </span>
              <span>{agent.display_name ?? agent.name}</span>
            </div>
          </ItemTitle>
          {agent.description && (
            <ItemDescription className="line-clamp-2">
              {agent.description}
            </ItemDescription>
          )}
        </ItemContent>
        <ItemActions>
          <Switch
            checked={agent.enabled}
            disabled={
              env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
              (isChild && !available && agent.enabled)
            }
            onCheckedChange={(checked) =>
              setEnabled({ name: agent.name, enabled: checked })
            }
          />
          {agent.source === "user" && (
            <Button
              size="icon"
              variant="ghost"
              className="text-destructive hover:text-destructive h-8 w-8"
              onClick={() => setDeleteOpen(true)}
            >
              <Trash2Icon className="h-3.5 w-3.5" />
            </Button>
          )}
        </ItemActions>
      </Item>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.agents.delete}</DialogTitle>
            <DialogDescription>{t.agents.deleteConfirm}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteAgent.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteAgent.isPending}
            >
              {deleteAgent.isPending ? t.common.loading : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
