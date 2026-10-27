"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { Target } from "@/core/enterprise/api";
import {
  createMailDraft,
  discardMailDraft,
  getMailDraft,
  listMailDrafts,
  parseMailRecipients,
  sendMailDraft,
  type MailDraft,
} from "@/core/enterprise/mail-outbox";
import { mailOutboxMessages } from "@/core/enterprise/mail-outbox-messages";
import { useI18n } from "@/core/i18n/hooks";

type Props = { userId?: string; accounts: Target[]; accountId: string };

export function MailOutbox(props: Props) {
  const params = useSearchParams();
  const initialId = params.get("mail_draft") ?? "";
  return (
    <OutboxEditor
      key={`${props.userId}:${initialId}`}
      {...props}
      initialId={initialId}
    />
  );
}

export function OutboxEditor({
  userId,
  accounts,
  accountId,
  initialId = "",
}: Props & { initialId?: string }) {
  const { locale } = useI18n();
  const copy = mailOutboxMessages[locale];
  const cache = useQueryClient();
  const listKey = ["enterprise-mail-outbox", userId];
  const [draftId, setDraftId] = useState(initialId);
  const draftKey = ["enterprise-mail-draft", userId, draftId];
  const [editing, setEditing] = useState(false);
  const [formAccount, setFormAccount] = useState("");
  const [to, setTo] = useState("");
  const [cc, setCc] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [uncertainId, setUncertainId] = useState("");
  const inFlight = useRef(false);
  const history = useQuery({
    queryKey: listKey,
    queryFn: listMailDrafts,
    enabled: !!userId,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.drafts?.some((item) => item.status === "sending")
        ? 3000
        : false,
  });
  const detail = useQuery({
    queryKey: draftKey,
    queryFn: () => getMailDraft(draftId),
    enabled: !!userId && !!draftId,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.status === "sending" ? 3000 : false,
  });
  const draft = detail.data;
  const errorCode =
    error ||
    (detail.error?.message ?? history.error?.message ?? draft?.result?.error);
  const errorText = errorCode
    ? (copy.errors[errorCode as keyof typeof copy.errors] ??
      copy.errors.request_failed)
    : "";
  const ready = !!history.data && !history.error;
  const selectedAccount = formAccount || accountId;

  async function perform(operation: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      await operation();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "request_failed");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  function show(item: MailDraft) {
    cache.setQueryData(["enterprise-mail-draft", userId, item.id], item);
    setDraftId(item.id);
    setEditing(false);
    setConfirmed(false);
    setError("");
  }
  async function refresh() {
    await perform(async () => {
      if (draftId) {
        const item = await getMailDraft(draftId);
        cache.setQueryData(draftKey, item);
        setUncertainId("");
      }
      await cache.invalidateQueries({ queryKey: listKey });
    });
  }
  async function submit() {
    if (
      !draft ||
      draft.status !== "draft" ||
      !confirmed ||
      uncertainId === draft.id
    )
      return;
    await perform(async () => {
      setUncertainId(draft.id);
      setConfirmed(false);
      try {
        const result = await sendMailDraft(draft.id);
        cache.setQueryData(draftKey, result);
        setUncertainId("");
      } catch {
        throw new Error("mail_request_uncertain");
      } finally {
        await cache.invalidateQueries({ queryKey: listKey });
      }
    });
  }
  return (
    <section aria-label={copy.title} className="space-y-4 border-t pt-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">{copy.title}</h3>
        <div className="flex gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => void refresh()}
          >
            {copy.refresh}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={busy || !ready || !accounts.length}
            onClick={() => {
              setDraftId("");
              setTo("");
              setCc("");
              setSubject("");
              setBody("");
              setFormAccount(accountId);
              setEditing(true);
              setError("");
            }}
          >
            {copy.compose}
          </Button>
        </div>
      </div>
      <p className="text-muted-foreground text-sm">{copy.hint}</p>
      {errorText && (
        <p role="alert" className="text-destructive text-sm">
          {errorText}
        </p>
      )}
      {editing && (
        <form
          className="space-y-3 rounded-lg border p-4"
          onSubmit={(event) => {
            event.preventDefault();
            void perform(async () => {
              const item = await createMailDraft({
                account_id: selectedAccount,
                to: parseMailRecipients(to),
                cc: parseMailRecipients(cc),
                subject,
                body,
              });
              show(item);
              await cache.invalidateQueries({ queryKey: listKey });
            });
          }}
        >
          <label className="block space-y-1 text-sm">
            <span>{copy.from}</span>
            <select
              className="bg-background w-full rounded-md border p-2"
              value={selectedAccount}
              disabled={busy}
              onChange={(event) => setFormAccount(event.target.value)}
            >
              {accounts.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1 text-sm">
            <span>{copy.to}</span>
            <Input
              required
              value={to}
              maxLength={5200}
              disabled={busy}
              onChange={(event) => setTo(event.target.value)}
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span>{copy.cc}</span>
            <Input
              value={cc}
              maxLength={5200}
              disabled={busy}
              onChange={(event) => setCc(event.target.value)}
            />
          </label>
          <p className="text-muted-foreground text-xs">{copy.recipientHint}</p>
          <label className="block space-y-1 text-sm">
            <span>{copy.subject}</span>
            <Input
              required
              value={subject}
              maxLength={200}
              disabled={busy}
              onChange={(event) => setSubject(event.target.value)}
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span>{copy.body}</span>
            <Textarea
              required
              value={body}
              maxLength={20000}
              rows={8}
              disabled={busy}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
          <p className="text-muted-foreground text-xs">{copy.plainText}</p>
          <div className="flex gap-2">
            <Button disabled={busy}>{copy.preview}</Button>
            <Button
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={() => setEditing(false)}
            >
              {copy.cancel}
            </Button>
          </div>
        </form>
      )}
      {draftId && detail.isPending && <p className="text-sm">{copy.loading}</p>}
      {draft && !editing && (
        <div
          className="space-y-4 rounded-lg border p-4"
          role="region"
          aria-label={copy.previewTitle}
        >
          <div className="flex items-center justify-between gap-3">
            <h4 className="font-medium">{copy.previewTitle}</h4>
            <span className="text-muted-foreground text-sm" role="status">
              {copy.statuses[draft.status]}
            </span>
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
            <dt>{copy.sender}</dt>
            <dd className="break-all">{draft.sender}</dd>
            <dt>{copy.to}</dt>
            <dd className="break-all">{draft.to.join(", ")}</dd>
            {!!draft.cc.length && (
              <>
                <dt>{copy.cc}</dt>
                <dd className="break-all">{draft.cc.join(", ")}</dd>
              </>
            )}
            <dt>{copy.subject}</dt>
            <dd className="break-words">{draft.subject}</dd>
          </dl>
          <p className="bg-muted/40 rounded-md p-3 text-sm break-words whitespace-pre-wrap">
            {draft.body}
          </p>
          {(draft.status === "sent" || draft.status === "partial") && (
            <p className="text-muted-foreground text-sm">{copy.sentHint}</p>
          )}
          {(draft.status === "unknown" || draft.status === "sending") && (
            <p className="text-sm">{copy.unknownHint}</p>
          )}
          {!!draft.result?.accepted.length && (
            <p className="text-sm break-all">
              {copy.accepted}: {draft.result.accepted.join(", ")}
            </p>
          )}
          {!!draft.result?.refused.length && (
            <p className="text-destructive text-sm break-all">
              {copy.refused}: {draft.result.refused.join(", ")}
            </p>
          )}
          {draft.status === "draft" && (
            <>
              <p className="text-sm">{copy.pending}</p>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={confirmed}
                  disabled={busy || uncertainId === draft.id}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                {copy.confirm}
              </label>
            </>
          )}
          <div className="flex flex-wrap gap-2">
            {draft.status === "draft" && (
              <>
                <Button
                  disabled={busy || !confirmed || uncertainId === draft.id}
                  onClick={() => void submit()}
                >
                  {busy ? copy.sending : copy.send}
                </Button>
                <Button
                  variant="outline"
                  disabled={busy || uncertainId === draft.id}
                  onClick={() =>
                    void perform(async () => {
                      const result = await discardMailDraft(draft.id);
                      cache.setQueryData(draftKey, result);
                      if (result.status === "discarded") {
                        setFormAccount(draft.account_id);
                        setTo(draft.to.join(", "));
                        setCc(draft.cc.join(", "));
                        setSubject(draft.subject);
                        setBody(draft.body);
                        setDraftId("");
                        setEditing(true);
                      }
                      await cache.invalidateQueries({ queryKey: listKey });
                    })
                  }
                >
                  {copy.edit}
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy || uncertainId === draft.id}
                  onClick={() =>
                    void perform(async () => {
                      cache.setQueryData(
                        draftKey,
                        await discardMailDraft(draft.id),
                      );
                      await cache.invalidateQueries({ queryKey: listKey });
                    })
                  }
                >
                  {copy.discard}
                </Button>
              </>
            )}
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setDraftId("");
                setConfirmed(false);
              }}
            >
              {copy.close}
            </Button>
          </div>
        </div>
      )}
      {ready && (
        <details open={!!initialId}>
          <summary className="cursor-pointer text-sm">{copy.history}</summary>
          {history.data?.drafts?.length ? (
            <ul className="mt-2 divide-y">
              {history.data.drafts.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className="flex w-full items-start justify-between gap-3 py-3 text-left text-sm hover:underline disabled:opacity-50"
                    disabled={busy}
                    onClick={() => show(item)}
                  >
                    <span className="min-w-0 break-words">
                      {item.subject}
                      <span className="text-muted-foreground block text-xs">
                        {item.sender} · {item.created_at} UTC
                      </span>
                    </span>
                    <span className="shrink-0 text-xs">
                      {copy.statuses[item.status]}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted-foreground mt-3 text-sm">{copy.empty}</p>
          )}
        </details>
      )}
    </section>
  );
}
