"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/core/auth/AuthProvider";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import {
  createShare,
  listShares,
  revokeShare,
  ShareError,
  type ShareLink,
} from "@/core/shares/api";

export function ThreadShareDialog({
  threadId,
  open,
  onOpenChange,
}: {
  threadId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { user } = useAuth();
  const { t } = useI18n();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t.sharing.title}</DialogTitle>
          <DialogDescription>{t.sharing.description}</DialogDescription>
        </DialogHeader>
        {open && (
          <ShareControls key={`${user?.id}:${threadId}`} threadId={threadId} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ShareControls({ threadId }: { threadId: string }) {
  const { t, locale } = useI18n();
  const labels = t.sharing;
  const [links, setLinks] = useState<ShareLink[]>([]);
  const [duration, setDuration] = useState(7 * 86400);
  const [link, setLink] = useState("");
  const [linkId, setLinkId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    const request = new AbortController();
    controller.current = request;
    void listShares(threadId, request.signal)
      .then((rows) => {
        if (!request.signal.aborted) setLinks(rows);
      })
      .catch((cause: unknown) => {
        if (!request.signal.aborted)
          setError(
            cause instanceof ShareError && cause.status === 503
              ? labels.unavailable
              : labels.failed,
          );
      })
      .finally(() => {
        if (!request.signal.aborted) setLoading(false);
      });
    return () => request.abort();
  }, [threadId, labels.failed, labels.unavailable]);

  async function mutate(operation: (signal: AbortSignal) => Promise<void>) {
    const request = controller.current;
    if (!request || request.signal.aborted || busy) return;
    setBusy(true);
    setError("");
    try {
      await operation(request.signal);
    } catch (cause) {
      if (!request.signal.aborted)
        setError(
          cause instanceof ShareError && cause.status === 409
            ? labels.conflict
            : cause instanceof ShareError && cause.status === 413
              ? labels.tooLarge
              : labels.failed,
        );
    } finally {
      if (!request.signal.aborted) setBusy(false);
    }
  }

  async function copy() {
    const success = await writeTextToClipboard(link);
    if (!controller.current?.signal.aborted) {
      setCopied(success);
      if (!success) setError(t.clipboard.failedToCopyToClipboard);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-sm">{labels.scope}</p>
      <label className="flex items-center justify-between gap-4 text-sm">
        {labels.expiry}
        <select
          className="border-input bg-background rounded-md border px-3 py-2"
          value={duration}
          onChange={(event) => setDuration(Number(event.target.value))}
          disabled={busy}
        >
          <option value={3600}>{labels.hour}</option>
          <option value={86400}>{labels.day}</option>
          <option value={7 * 86400}>{labels.week}</option>
          <option value={30 * 86400}>{labels.month}</option>
        </select>
      </label>
      <Button
        className="w-full"
        disabled={busy || loading}
        onClick={() =>
          void mutate(async (signal) => {
            const created = await createShare(threadId, duration, signal);
            if (signal.aborted) return;
            setLink(
              `${window.location.origin}/share/${encodeURIComponent(created.token)}`,
            );
            setLinkId(created.share_id);
            setCopied(false);
            setLinks((rows) => [created, ...rows]);
          })
        }
      >
        {busy ? labels.working : labels.create}
      </Button>
      {link && (
        <div className="flex gap-2">
          <Input aria-label={labels.link} readOnly value={link} />
          <Button variant="outline" onClick={() => void copy()}>
            {copied ? labels.copied : labels.copy}
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      <div className="max-h-56 space-y-2 overflow-y-auto">
        <h3 className="text-sm font-medium">{labels.links}</h3>
        {loading ? (
          <p role="status">{labels.loading}</p>
        ) : links.length === 0 ? (
          <p className="text-muted-foreground text-sm">{labels.noLinks}</p>
        ) : (
          links.map((item) => {
            const expired = Date.parse(item.expires_at) <= Date.now();
            return (
              <div
                key={item.share_id}
                className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm"
              >
                <div>
                  <time>
                    {new Date(item.created_at).toLocaleString(locale)}
                  </time>
                  <p className="text-muted-foreground">
                    {item.revoked_at
                      ? labels.revoked
                      : expired
                        ? labels.expired
                        : `${labels.expires} ${new Date(item.expires_at).toLocaleString(locale)}`}
                  </p>
                </div>
                {!item.revoked_at && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      void mutate(async (signal) => {
                        await revokeShare(threadId, item.share_id, signal);
                        if (signal.aborted) return;
                        setLinks((rows) =>
                          rows.map((row) =>
                            row.share_id === item.share_id
                              ? { ...row, revoked_at: new Date().toISOString() }
                              : row,
                          ),
                        );
                        if (linkId === item.share_id) setLink("");
                      })
                    }
                  >
                    {labels.revoke}
                  </Button>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
