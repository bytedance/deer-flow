"use client";

import { ArrowLeftIcon, BotIcon, Loader2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AgentNameCheckError,
  AgentsApiDisabledError,
  checkAgentName,
  createAgent,
} from "@/core/agents/api";
import { useI18n } from "@/core/i18n/hooks";
import { isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";

const NAME_RE = /^[A-Za-z0-9-]+$/;

export default function NewAgentPage() {
  const { t } = useI18n();
  const router = useRouter();

  const [nameInput, setNameInput] = useState("");
  const [nameError, setNameError] = useState("");
  const [isCheckingName, setIsCheckingName] = useState(false);

  const handleConfirmName = useCallback(async () => {
    const trimmed = nameInput.trim();
    if (!trimmed) return;
    if (!NAME_RE.test(trimmed)) {
      setNameError(t.agents.nameStepInvalidError);
      return;
    }

    setNameError("");
    setIsCheckingName(true);
    let normalizedName = trimmed;
    try {
      const result = await checkAgentName(trimmed);
      if (!result.available) {
        setNameError(t.agents.nameStepAlreadyExistsError);
        return;
      }
      normalizedName = result.name;
      const created = await createAgent({
        name: normalizedName,
        soul: "",
      });
      router.push(`/workspace/agents/${created.name}/edit`);
    } catch (err) {
      if (err instanceof AgentsApiDisabledError) {
        setNameError(t.agents.nameStepApiDisabledError);
      } else if (
        err instanceof AgentNameCheckError &&
        err.reason === "backend_unreachable"
      ) {
        setNameError(t.agents.nameStepNetworkError);
      } else if (
        err instanceof AgentNameCheckError &&
        err.reason === "request_failed"
      ) {
        // Surface the backend-provided detail (e.g. validation error) when
        // one is present, wrapped in a localised prefix so zh-CN users
        // don't see a bare English string next to the surrounding Chinese
        // UI. Falls back to the generic localised fallback when the backend
        // sent no detail — `err.message` is unreliable for this branch
        // because `checkAgentName` substitutes a generated fallback string
        // ("Failed to check agent name: ${statusText}") when `detail` is
        // missing, so testing `err.message` would always be truthy and the
        // generated fallback would leak through.
        setNameError(
          err.detail
            ? t.agents.nameStepCheckErrorWithDetail.replace(
                "{detail}",
                err.detail,
              )
            : t.agents.nameStepCheckError,
        );
      } else {
        const message =
          err instanceof Error ? err.message : t.agents.nameStepCheckError;
        setNameError(message);
        toast.error(message);
      }
      return;
    } finally {
      setIsCheckingName(false);
    }
  }, [
    nameInput,
    router,
    t.agents.nameStepAlreadyExistsError,
    t.agents.nameStepApiDisabledError,
    t.agents.nameStepNetworkError,
    t.agents.nameStepCheckError,
    t.agents.nameStepCheckErrorWithDetail,
    t.agents.nameStepInvalidError,
  ]);

  const handleNameKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !isIMEComposing(e)) {
      e.preventDefault();
      void handleConfirmName();
    }
  };

  const header = (
    <header className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => router.push("/workspace/agents")}
        >
          <ArrowLeftIcon className="h-4 w-4" />
        </Button>
        <h1 className="text-sm font-semibold">{t.agents.createPageTitle}</h1>
      </div>
    </header>
  );

  return (
    <div className="flex size-full flex-col">
      {header}
      <main className="flex flex-1 flex-col items-center justify-center px-4">
        <div className="w-full max-w-sm space-y-8">
          <div className="space-y-3 text-center">
            <div className="bg-primary/10 mx-auto flex h-14 w-14 items-center justify-center rounded-full">
              <BotIcon className="text-primary h-7 w-7" />
            </div>
            <div className="space-y-1">
              <h2 className="text-xl font-semibold">
                {t.agents.nameStepTitle}
              </h2>
              <p className="text-muted-foreground text-sm">
                {t.agents.nameStepHint}
              </p>
            </div>
          </div>

          <div className="space-y-3">
            <Input
              autoFocus
              placeholder={t.agents.nameStepPlaceholder}
              value={nameInput}
              onChange={(e) => {
                setNameInput(e.target.value);
                setNameError("");
              }}
              onKeyDown={handleNameKeyDown}
              className={cn(nameError && "border-destructive")}
            />
            {nameError ? (
              <p className="text-destructive text-sm">{nameError}</p>
            ) : null}
            <Button
              className="w-full"
              onClick={() => void handleConfirmName()}
              disabled={!nameInput.trim() || isCheckingName}
            >
              {isCheckingName ? (
                <Loader2Icon className="mr-1.5 h-4 w-4 animate-spin" />
              ) : null}
              {t.agents.nameStepContinue}
            </Button>
          </div>
        </div>
      </main>
    </div>
  );
}
