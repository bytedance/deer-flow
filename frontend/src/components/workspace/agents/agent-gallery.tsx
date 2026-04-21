"use client";

import { BotIcon, InfoIcon, PlusIcon } from "lucide-react";
import { useRouter } from "next/navigation";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useAgents, useAgentsApiStatus } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";

import { AgentCard } from "./agent-card";

const AGENTS_API_CONFIG_SNIPPET = "agents_api:\n  enabled: true";

export function AgentGallery() {
  const { t } = useI18n();
  const {
    status: agentsApiStatus,
    isLoading: isStatusLoading,
    error: statusError,
  } = useAgentsApiStatus();
  const isAgentsApiEnabled = agentsApiStatus?.enabled ?? false;
  const {
    agents,
    isLoading: isAgentsLoading,
    error: agentsError,
  } = useAgents({
    enabled: isAgentsApiEnabled,
  });
  const router = useRouter();

  const handleNewAgent = () => {
    router.push("/workspace/agents/new");
  };

  const isLoading = isStatusLoading || (isAgentsApiEnabled && isAgentsLoading);
  const loadError = statusError ?? agentsError;

  return (
    <div className="flex size-full flex-col">
      {/* Page header */}
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold">{t.agents.title}</h1>
          <p className="text-muted-foreground mt-0.5 text-sm">
            {t.agents.description}
          </p>
        </div>
        <Button onClick={handleNewAgent} disabled={!isAgentsApiEnabled}>
          <PlusIcon className="mr-1.5 h-4 w-4" />
          {t.agents.newAgent}
        </Button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="text-muted-foreground flex h-40 items-center justify-center text-sm">
            {t.common.loading}
          </div>
        ) : loadError ? (
          <Alert className="max-w-2xl">
            <InfoIcon />
            <AlertTitle>{t.agents.apiStatusErrorTitle}</AlertTitle>
            <AlertDescription>
              {t.agents.apiStatusErrorDescription}
            </AlertDescription>
          </Alert>
        ) : !isAgentsApiEnabled ? (
          <Alert className="max-w-2xl">
            <InfoIcon />
            <AlertTitle>{t.agents.apiDisabledTitle}</AlertTitle>
            <AlertDescription>
              <p>{t.agents.apiDisabledDescription}</p>
              <p>{t.agents.apiDisabledConfigHint}</p>
              <pre className="bg-muted text-foreground w-full overflow-x-auto rounded-md border px-3 py-2 font-mono text-xs whitespace-pre">
                <code>{AGENTS_API_CONFIG_SNIPPET}</code>
              </pre>
            </AlertDescription>
          </Alert>
        ) : agents.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
            <div className="bg-muted flex h-14 w-14 items-center justify-center rounded-full">
              <BotIcon className="text-muted-foreground h-7 w-7" />
            </div>
            <div>
              <p className="font-medium">{t.agents.emptyTitle}</p>
              <p className="text-muted-foreground mt-1 text-sm">
                {t.agents.emptyDescription}
              </p>
            </div>
            <Button variant="outline" className="mt-2" onClick={handleNewAgent}>
              <PlusIcon className="mr-1.5 h-4 w-4" />
              {t.agents.newAgent}
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {agents.map((agent) => (
              <AgentCard key={agent.name} agent={agent} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
