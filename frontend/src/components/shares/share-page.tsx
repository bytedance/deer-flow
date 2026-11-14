"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useI18n } from "@/core/i18n/hooks";
import {
  forkShare,
  readShare,
  ShareError,
  shareArtifactURL,
  type SharedArtifact,
  type SharedConversation,
} from "@/core/shares/api";

import { ShareArtifact } from "./share-artifact";
import { ShareMarkdown } from "./share-markdown";

export function SharePage({ token }: { token: string }) {
  const { t, locale } = useI18n();
  const labels = t.sharing;
  const router = useRouter();
  const [snapshot, setSnapshot] = useState<SharedConversation | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<SharedArtifact | null>(null);
  const [forking, setForking] = useState(false);
  const [forkError, setForkError] = useState("");
  const forkController = useRef<AbortController | null>(null);
  const forkRequest = useRef<string | null>(null);
  useEffect(() => () => forkController.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    let pending = false;
    async function load() {
      if (pending) return;
      pending = true;
      try {
        const data = await readShare(token, controller.signal);
        if (!controller.signal.aborted) {
          setSnapshot(data);
          setError("");
        }
      } catch (cause) {
        if (!controller.signal.aborted) {
          setSnapshot(null);
          setSelected(null);
          setError(
            cause instanceof ShareError && cause.status === 404
              ? labels.missing
              : labels.failed,
          );
        }
      } finally {
        pending = false;
      }
    }
    void load();
    const refresh = () => {
      if (document.visibilityState === "visible") void load();
    };
    const timer = setInterval(refresh, 30_000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      controller.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [token, retry, labels.failed, labels.missing]);
  useEffect(() => {
    if (!snapshot) return;
    const delay = Math.max(0, Date.parse(snapshot.expires_at) - Date.now());
    // Polling will install a timer once a long-lived share enters this window.
    if (delay > 2_147_483_647) return;
    const timer = setTimeout(() => {
      setSnapshot(null);
      setSelected(null);
      setError(labels.missing);
    }, delay);
    return () => clearTimeout(timer);
  }, [snapshot, labels.missing]);

  async function fork() {
    if (forking) return;
    const controller = new AbortController();
    forkController.current = controller;
    forkRequest.current ??= crypto.randomUUID();
    setForking(true);
    setForkError("");
    try {
      const result = await forkShare(
        token,
        forkRequest.current,
        controller.signal,
      );
      if (!controller.signal.aborted)
        router.push(`/workspace/chats/${encodeURIComponent(result.thread_id)}`);
    } catch (cause) {
      if (!controller.signal.aborted)
        setForkError(
          cause instanceof ShareError && cause.status === 404
            ? labels.missing
            : labels.failed,
        );
    } finally {
      if (!controller.signal.aborted) setForking(false);
    }
  }

  return (
    <main className="mx-auto min-h-screen max-w-5xl space-y-6 px-4 py-8">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b pb-5">
        <div>
          <Link href="/" className="font-serif text-2xl">
            DeerFlow
          </Link>
          <p className="text-muted-foreground mt-1 text-sm">
            {labels.readOnly}
          </p>
        </div>
        {snapshot && (
          <Button disabled={forking} onClick={() => void fork()}>
            {forking ? labels.forking : labels.fork}
          </Button>
        )}
      </header>
      {forkError && (
        <p role="alert" className="text-destructive">
          {forkError}
        </p>
      )}
      {error ? (
        <div role="alert" className="space-y-4 rounded-lg border p-6">
          <p>{error}</p>
          <Button
            variant="outline"
            onClick={() => {
              setError("");
              setRetry((value) => value + 1);
            }}
          >
            {labels.retry}
          </Button>
        </div>
      ) : !snapshot ? (
        <p role="status">{labels.loading}</p>
      ) : (
        <>
          <div>
            <h1 className="text-2xl font-semibold break-words">
              {snapshot.title}
            </h1>
            <p className="text-muted-foreground mt-2 text-sm">
              {new Date(snapshot.created_at).toLocaleString(locale)} ·{" "}
              {labels.expires}{" "}
              {new Date(snapshot.expires_at).toLocaleString(locale)}
            </p>
          </div>
          {snapshot.artifacts.length > 0 && (
            <section
              aria-label={labels.artifacts}
              className="space-y-3 rounded-lg border p-4"
            >
              <h2 className="font-medium">{labels.artifacts}</h2>
              <div className="grid gap-2 sm:grid-cols-2">
                {snapshot.artifacts.map((artifact) => (
                  <div
                    key={artifact.path}
                    className="bg-secondary/60 flex min-w-0 items-center justify-between gap-2 rounded-md p-3"
                  >
                    <button
                      className="min-w-0 text-left text-sm break-all underline"
                      onClick={() => setSelected(artifact)}
                    >
                      {artifact.path}
                    </button>
                    <a
                      className="shrink-0 text-sm underline"
                      href={`${shareArtifactURL(token, artifact.path)}?download=true`}
                      referrerPolicy="no-referrer"
                    >
                      {labels.download}
                    </a>
                  </div>
                ))}
              </div>
            </section>
          )}
          <section aria-label={labels.title} className="space-y-5">
            {snapshot.messages.map((message) =>
              message.type === "tool" ? (
                <details key={message.id} className="rounded-lg border p-4">
                  <summary className="cursor-pointer text-sm">
                    {labels.tool}: {message.name}
                  </summary>
                  <pre className="mt-3 max-h-96 overflow-auto text-sm whitespace-pre-wrap">
                    {message.content}
                  </pre>
                </details>
              ) : (
                <article
                  key={message.id}
                  className={`space-y-3 rounded-lg p-5 ${message.type === "human" ? "bg-secondary/60" : "border"}`}
                >
                  <h2 className="text-muted-foreground text-sm font-medium">
                    {message.type === "human" ? labels.you : labels.assistant}
                  </h2>
                  <ShareMarkdown
                    content={message.content}
                    token={token}
                    artifacts={snapshot.artifacts}
                  />
                </article>
              ),
            )}
          </section>
          <Dialog
            open={selected !== null}
            onOpenChange={(open) => {
              if (!open) setSelected(null);
            }}
          >
            <DialogContent className="max-h-[90vh] overflow-auto sm:max-w-4xl">
              <DialogHeader>
                <DialogTitle className="break-all">
                  {selected?.path}
                </DialogTitle>
                <DialogDescription>{labels.preview}</DialogDescription>
              </DialogHeader>
              {selected && (
                <ShareArtifact
                  key={selected.path}
                  token={token}
                  artifact={selected}
                  artifacts={snapshot.artifacts}
                />
              )}
            </DialogContent>
          </Dialog>
        </>
      )}
    </main>
  );
}
