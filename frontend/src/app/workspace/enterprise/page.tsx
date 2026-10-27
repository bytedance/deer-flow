"use client";

import { useQuery } from "@tanstack/react-query";
import { Building2, MessageSquare, Plus, RefreshCw } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useAuth } from "@/core/auth/AuthProvider";
import { enterpriseRequest, type Overview } from "@/core/enterprise/api";
import { enterpriseMessages } from "@/core/enterprise/messages";
import { useI18n } from "@/core/i18n/hooks";

import { MailPanel } from "./mail-panel";

export default function EnterprisePage() {
  const { user } = useAuth();
  return <EnterprisePanel key={user?.id ?? "anonymous"} userId={user?.id} />;
}

function EnterprisePanel({ userId }: { userId?: string }) {
  const { locale } = useI18n();
  const copy = enterpriseMessages[locale];
  const query = useQuery({
    queryKey: ["enterprise", userId],
    queryFn: () => enterpriseRequest<Overview>(""),
    enabled: !!userId,
    retry: false,
  });
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [webhook, setWebhook] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const targets = query.data?.targets ?? [];
  const errorCode = error || query.error?.message;
  const errorText = errorCode
    ? (copy.errors[errorCode as keyof typeof copy.errors] ??
      copy.errors.request_failed)
    : "";

  async function perform(operation: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await operation();
      await query.refetch();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "request_failed");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    await perform(async () => {
      await enterpriseRequest("/targets", {
        name,
        webhook,
        provider: "wecom_webhook",
      });
      setWebhook("");
      setName("");
      setAdding(false);
    });
  }

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="w-full max-w-5xl space-y-6 overflow-y-auto p-4 md:p-8">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="flex items-center gap-2 text-2xl font-semibold">
                <Building2 className="size-6" />
                {copy.title}
              </h1>
              <p className="text-muted-foreground mt-2 text-sm">
                {copy.subtitle}
              </p>
            </div>
            <Button
              variant="outline"
              disabled={busy || query.isFetching}
              onClick={() => void query.refetch()}
            >
              <RefreshCw className="size-4" />
              {copy.refresh}
            </Button>
          </div>
          {errorText && (
            <p
              role="alert"
              className="border-destructive/30 text-destructive rounded-lg border p-3 text-sm"
            >
              {errorText}
            </p>
          )}
          {query.isLoading ? (
            <p>{copy.loading}</p>
          ) : (
            query.data && (
              <section className="space-y-4 rounded-xl border p-5">
                <div className="flex items-center justify-between gap-4">
                  <h2 className="flex items-center gap-2 font-semibold">
                    <MessageSquare className="size-5" />
                    {copy.wecom}
                  </h2>
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => setAdding(true)}
                  >
                    <Plus className="size-4" />
                    {copy.add}
                  </Button>
                </div>
                <p className="text-muted-foreground text-sm">
                  {copy.wecomHint}
                </p>
                {adding && (
                  <form
                    className="bg-muted/30 grid gap-3 rounded-lg p-4"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void save();
                    }}
                  >
                    <label className="space-y-1 text-sm" htmlFor="group-name">
                      <span>{copy.name}</span>
                      <Input
                        id="group-name"
                        value={name}
                        maxLength={80}
                        disabled={busy}
                        onChange={(event) => setName(event.target.value)}
                        required
                      />
                    </label>
                    <label
                      className="space-y-1 text-sm"
                      htmlFor="group-webhook"
                    >
                      <span>{copy.webhook}</span>
                      <Input
                        id="group-webhook"
                        type="password"
                        autoComplete="off"
                        value={webhook}
                        disabled={busy}
                        onChange={(event) => setWebhook(event.target.value)}
                        required
                      />
                    </label>
                    <div className="flex gap-2">
                      <Button
                        disabled={busy || !name.trim() || !webhook.trim()}
                      >
                        {copy.save}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        disabled={busy}
                        onClick={() => {
                          setAdding(false);
                          setWebhook("");
                        }}
                      >
                        {copy.cancel}
                      </Button>
                    </div>
                  </form>
                )}
                {targets.length ? (
                  <ul className="divide-y">
                    {targets.map((target) => (
                      <li
                        key={target.id}
                        className="flex items-center justify-between py-2"
                      >
                        <span className="text-sm break-all">{target.name}</span>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy}
                          onClick={() => {
                            if (window.confirm(copy.removeHint))
                              void perform(async () => {
                                await enterpriseRequest(
                                  `/targets/${encodeURIComponent(target.id)}`,
                                  undefined,
                                  "DELETE",
                                );
                              });
                          }}
                        >
                          {copy.remove}
                        </Button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-muted-foreground py-3 text-sm">
                    {copy.empty}
                  </p>
                )}
                <p className="bg-muted/40 rounded-lg p-3 text-sm">
                  {copy.example}
                </p>
              </section>
            )
          )}
          <MailPanel userId={userId} />
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
