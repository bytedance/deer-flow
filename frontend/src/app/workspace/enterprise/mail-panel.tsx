"use client";

import { useQuery } from "@tanstack/react-query";
import { Mail } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { enterpriseRequest } from "@/core/enterprise/api";
import {
  createMailAnalysisThread,
  listMailAccounts,
  readMail,
  runMailAnalysis,
  type MailMessage,
  type MailPage,
} from "@/core/enterprise/mail";
import { mailMessages } from "@/core/enterprise/mail-messages";
import { useI18n } from "@/core/i18n/hooks";
import { pathOfThread } from "@/core/threads/utils";

import { MailOutbox } from "./mail-outbox";

export function MailPanel({ userId }: { userId?: string }) {
  const { locale } = useI18n();
  const copy = mailMessages[locale];
  const router = useRouter();
  const accounts = useQuery({
    queryKey: ["enterprise-mail", userId],
    queryFn: listMailAccounts,
    enabled: !!userId,
    retry: false,
  });
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [host, setHost] = useState("imap.qiye.aliyun.com");
  const [accountId, setAccountId] = useState("");
  const [days, setDays] = useState(7);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState("");
  const [page, setPage] = useState<MailPage>();
  const [messages, setMessages] = useState<MailMessage[]>([]);
  const [analysisThread, setAnalysisThread] = useState("");
  const selected =
    accounts.data?.accounts.find((item) => item.id === accountId)?.id ??
    accounts.data?.accounts[0]?.id ??
    "";
  const errorCode = error || accounts.error?.message;
  const errorText =
    errorCode === "analysis_failed"
      ? copy.runFailed
      : errorCode
        ? (copy.errors[errorCode as keyof typeof copy.errors] ??
          copy.errors.request_failed)
        : "";

  function clearPreview() {
    setPage(undefined);
    setMessages([]);
    setError("");
  }
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
  async function preview(older = false) {
    await perform(async () => {
      if (!older) clearPreview();
      const result = await readMail(
        selected,
        { days, unreadOnly },
        older ? page : undefined,
      );
      setPage(result);
      setMessages((previous) =>
        older
          ? [
              ...previous,
              ...result.messages.filter(
                (item) => !previous.some((old) => old.uid === item.uid),
              ),
            ]
          : result.messages,
      );
    });
  }
  async function analyze() {
    await perform(async () => {
      const thread = await createMailAnalysisThread();
      setAnalysisThread(thread.thread_id);
      try {
        await runMailAnalysis(
          thread.thread_id,
          selected,
          { days, unreadOnly },
          locale,
        );
      } catch {
        throw new Error("analysis_failed");
      }
      router.push(pathOfThread(thread.thread_id));
    });
  }

  return (
    <section
      className="space-y-4 rounded-xl border p-5"
      aria-label={copy.title}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 font-semibold">
          <Mail className="size-5" />
          {copy.title}
        </h2>
        <Button
          variant="outline"
          disabled={busy || accounts.isPending || !!accounts.error}
          onClick={() => setAdding(true)}
        >
          {copy.connect}
        </Button>
      </div>
      <p className="text-muted-foreground text-sm">{copy.hint}</p>
      {errorText && (
        <p role="alert" className="text-destructive text-sm">
          {errorText}
        </p>
      )}
      {accounts.isPending && <p className="text-sm">{copy.loading}</p>}
      {adding && (
        <form
          className="space-y-3 rounded-lg border p-4"
          onSubmit={(event) => {
            event.preventDefault();
            void perform(async () => {
              const target = await enterpriseRequest<{ id: string }>(
                "/mail/accounts",
                { name, email, password, host },
              );
              setPassword("");
              setEmail("");
              setName("");
              setAdding(false);
              setAccountId(target.id);
              clearPreview();
              await accounts.refetch();
            });
          }}
        >
          <p className="text-muted-foreground text-sm">
            {copy.setup}{" "}
            <a
              className="underline"
              href="https://help.aliyun.com/zh/document_detail/36576.html"
              target="_blank"
              rel="noreferrer"
            >
              {copy.help}
            </a>
          </p>
          <label className="block space-y-1 text-sm">
            <span>{copy.name}</span>
            <Input
              required
              maxLength={80}
              value={name}
              disabled={busy}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span>{copy.email}</span>
            <Input
              type="email"
              required
              autoComplete="off"
              value={email}
              disabled={busy}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span>{copy.password}</span>
            <Input
              type="password"
              required
              autoComplete="new-password"
              value={password}
              disabled={busy}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span>{copy.host}</span>
            <select
              className="bg-background w-full rounded-md border p-2"
              value={host}
              disabled={busy}
              onChange={(event) => setHost(event.target.value)}
            >
              <option value="imap.qiye.aliyun.com">{copy.mainland}</option>
              <option value="imaphk.qiye.aliyun.com">{copy.hongkong}</option>
            </select>
          </label>
          <div className="flex gap-2">
            <Button disabled={busy}>{busy ? copy.loading : copy.save}</Button>
            <Button
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setAdding(false);
                setPassword("");
                setEmail("");
                setName("");
              }}
            >
              {copy.cancel}
            </Button>
          </div>
        </form>
      )}
      {!accounts.isPending && !accounts.error && !selected && (
        <p className="text-muted-foreground text-sm">{copy.empty}</p>
      )}
      {selected && !accounts.error && (
        <>
          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-0 flex-1 space-y-1 text-sm">
              <span>{copy.account}</span>
              <select
                className="bg-background w-full rounded-md border p-2"
                value={selected}
                disabled={busy}
                onChange={(event) => {
                  setAccountId(event.target.value);
                  clearPreview();
                  setAnalysisThread("");
                }}
              >
                {accounts.data?.accounts.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span>{copy.days}</span>
              <select
                className="bg-background block rounded-md border p-2"
                value={days}
                disabled={busy}
                onChange={(event) => {
                  setDays(Number(event.target.value));
                  clearPreview();
                }}
              >
                {[1, 7, 30, 90].map((value) => (
                  <option key={value} value={value}>
                    {value} {copy.day}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 pb-2 text-sm">
              <input
                type="checkbox"
                checked={unreadOnly}
                disabled={busy}
                onChange={(event) => {
                  setUnreadOnly(event.target.checked);
                  clearPreview();
                }}
              />
              {copy.unread}
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => void preview()}
            >
              {copy.preview}
            </Button>
            <Button
              disabled={busy || !!analysisThread}
              onClick={() => void analyze()}
            >
              {copy.analyze}
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => {
                if (window.confirm(copy.disconnectConfirm))
                  void perform(async () => {
                    await enterpriseRequest(
                      `/mail/accounts/${encodeURIComponent(selected)}`,
                      undefined,
                      "DELETE",
                    );
                    clearPreview();
                    setAnalysisThread("");
                    await accounts.refetch();
                  });
              }}
            >
              {copy.disconnect}
            </Button>
          </div>
          <p className="text-muted-foreground text-xs">{copy.analysisHint}</p>
          {analysisThread && (
            <Link
              className="text-sm underline"
              href={pathOfThread(analysisThread)}
            >
              {copy.open}
            </Link>
          )}
        </>
      )}
      {busy && (
        <p role="status" className="text-sm">
          {copy.loading}
        </p>
      )}
      {page && !accounts.error && (
        <div className="space-y-3">
          <p className="text-muted-foreground text-sm">
            {copy.previewHint} {copy.loaded} {messages.length} {copy.messages}。
          </p>
          {!messages.length && <p className="text-sm">{copy.noMessages}</p>}
          {Object.entries(copy.categories).map(([category, label]) => {
            const grouped = messages.filter(
              (item) => item.category === category,
            );
            return grouped.length ? (
              <div key={category} className="space-y-2">
                <h3 className="text-sm font-semibold">
                  {label} · {grouped.length}
                </h3>
                {grouped.map((item) => (
                  <details
                    key={item.uid}
                    className="rounded-lg border p-3 text-sm"
                  >
                    <summary className="cursor-pointer break-words">
                      <span className={item.unread ? "font-semibold" : ""}>
                        {item.subject || copy.noSubject}
                      </span>
                      <span className="text-muted-foreground mt-1 block break-all">
                        {item.sender} · {item.date} · UID {item.uid}
                      </span>
                    </summary>
                    <p className="mt-3 break-words whitespace-pre-wrap">
                      {item.text}
                    </p>
                    {item.attachments.length > 0 && (
                      <p className="text-muted-foreground mt-2 break-words">
                        {copy.attachments}: {item.attachments.join(", ")}
                      </p>
                    )}
                    {item.truncated && (
                      <p className="text-muted-foreground mt-2">
                        {copy.truncated}
                      </p>
                    )}
                  </details>
                ))}
              </div>
            ) : null;
          })}
          {page.has_more && (
            <div className="space-y-2">
              <p className="text-muted-foreground text-sm">{copy.partial}</p>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => void preview(true)}
              >
                {copy.more}
              </Button>
            </div>
          )}
        </div>
      )}
      <MailOutbox
        userId={userId}
        accounts={accounts.data?.accounts ?? []}
        accountId={selected}
      />
    </section>
  );
}
