"use client";

import { useQueryClient } from "@tanstack/react-query";
import { KeyRoundIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemTitle,
} from "@/components/ui/item";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { UnauthorizedError } from "@/core/api/errors";
import { useAuth } from "@/core/auth/AuthProvider";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import {
  PatStoreUnavailableError,
  patQueryKey,
  useCreatePat,
  usePats,
  useRevokePat,
} from "@/core/pats";
import {
  PAT_SCOPES,
  type PatCreated,
  type PatScope,
  type PatSummary,
} from "@/core/pats";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { formatDate, formatTimeAgo } from "@/core/utils/datetime";

import { SettingsSection } from "./settings-section";

const EXPIRY_CHOICES = [
  { value: "30", days: 30 },
  { value: "90", days: 90 },
  { value: "180", days: 180 },
  { value: "365", days: 365 },
  { value: "never", days: null },
] as const;

// Start with no implicit grant. The form already requires at least one scope,
// so every created token reflects an explicit permission choice.
const DEFAULT_SCOPES = new Set<PatScope>();

// The repository lists every row regardless of expiry (only credential
// validation drops expired tokens), so the UI must flag them itself.
function isExpired(pat: PatSummary): boolean {
  if (pat.expires_at === null) return false;
  const parsed = new Date(pat.expires_at);
  return !Number.isNaN(parsed.getTime()) && parsed.getTime() <= Date.now();
}

function formatExpiry(pat: PatSummary): string {
  if (pat.expires_at === null) return "";
  return formatDate(pat.expires_at);
}

export function PatSettingsPage() {
  if (isStaticWebsiteOnly()) {
    return <StaticPatSettingsPage />;
  }
  return <InteractivePatSettingsPage />;
}

function StaticPatSettingsPage() {
  const { t } = useI18n();
  return (
    <SettingsSection
      title={t.settings.tokens.title}
      description={t.settings.tokens.description}
    >
      <div className="text-muted-foreground rounded-md border border-dashed p-4 text-sm">
        {t.common.notAvailableInDemoMode}
      </div>
    </SettingsSection>
  );
}

function InteractivePatSettingsPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const { pats, isLoading, error } = usePats();
  const create = useCreatePat();
  const revoke = useRevokePat();

  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<Set<PatScope>>(new Set(DEFAULT_SCOPES));
  const [expiry, setExpiry] = useState<string>("90");
  const [created, setCreated] = useState<PatCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [revoking, setRevoking] = useState<PatSummary | null>(null);

  const storeUnavailable = error instanceof PatStoreUnavailableError;
  const nameValid = name.trim().length > 0;
  const scopesValid = scopes.size > 0;

  // While the only copy of a token is on screen (or is about to arrive),
  // navigating away or closing the tab must at least warn: the credential is
  // unrecoverable afterwards.
  useEffect(() => {
    if (created === null && !create.isPending) return;
    const warnUnrecoverable = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Safari/WebKit still relies on the legacy returnValue signal, while
      // preventDefault covers modern Chromium and Firefox.
      event.returnValue = true;
    };
    window.addEventListener("beforeunload", warnUnrecoverable);
    return () => window.removeEventListener("beforeunload", warnUnrecoverable);
  }, [created, create.isPending]);

  function resetCreateForm() {
    setName("");
    setScopes(new Set(DEFAULT_SCOPES));
    setExpiry("90");
    setCopied(false);
  }

  function closeCreateDialog() {
    setCreateOpen(false);
    setCreated(null);
    resetCreateForm();
    // Detach the mutation observer; combined with gcTime: 0 on the mutation
    // this drops the show-once token from the in-memory cache as soon as the
    // user closes the result view.
    create.reset();
  }

  function toggleScope(scope: PatScope, enabled: boolean) {
    setScopes((previous) => {
      const next = new Set(previous);
      if (enabled) {
        next.add(scope);
      } else {
        next.delete(scope);
      }
      return next;
    });
  }

  async function handleCreate() {
    // Belt-and-braces next to the disabled submit button: a second minted
    // token is unrecoverable for the user who never saw the first one.
    if (create.isPending) return;
    const days = EXPIRY_CHOICES.find((choice) => choice.value === expiry)?.days;
    try {
      const result = await create.mutateAsync({
        name: name.trim(),
        scopes: [...scopes].sort(),
        expires_in_days: days ?? null,
      });
      setCreated(result);
    } catch (err) {
      if (err instanceof UnauthorizedError) return;
      if (err instanceof PatStoreUnavailableError) {
        // The backend switched to (or restarted on) the memory store: close
        // the create dialog and refetch so the unavailable banner takes over
        // instead of a stale list plus a still-open form.
        closeCreateDialog();
        showUnavailableStoreState();
        return;
      }
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleCopyToken() {
    if (created === null) return;
    // Use the shared helper: plain-HTTP LAN deployments have no
    // navigator.clipboard, and this dialog is the one place copying matters.
    const copied = await writeTextToClipboard(created.token);
    if (copied) {
      setCopied(true);
      toast.success(t.settings.tokens.copied);
    } else {
      setCopied(false);
      toast.error(t.settings.tokens.copyFailed);
    }
  }

  async function handleRevoke() {
    if (revoking === null) return;
    try {
      await revoke.mutateAsync(revoking.id);
      toast.success(t.settings.tokens.revoked);
      setRevoking(null);
    } catch (err) {
      if (err instanceof UnauthorizedError) return;
      if (err instanceof PatStoreUnavailableError) {
        // A deployment that no longer has a PAT store cannot service any of
        // the cached management UI. Close the confirmation and refresh so
        // the deployment-level unavailable state replaces the stale list.
        setRevoking(null);
        showUnavailableStoreState();
        return;
      }
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  function showUnavailableStoreState() {
    toast.error(t.settings.tokens.unavailableTitle);
    void queryClient.invalidateQueries({
      queryKey: patQueryKey(user?.id ?? null),
    });
  }

  return (
    <SettingsSection
      title={t.settings.tokens.title}
      description={t.settings.tokens.description}
    >
      {storeUnavailable ? (
        <div className="text-muted-foreground rounded-md border border-dashed p-4 text-sm">
          <div className="font-medium">
            {t.settings.tokens.unavailableTitle}
          </div>
          <div className="mt-1">{t.settings.tokens.unavailableDescription}</div>
        </div>
      ) : error ? (
        <div className="text-destructive text-sm">
          {error instanceof Error && error.message
            ? error.message
            : t.settings.tokens.loadError}
        </div>
      ) : isLoading ? (
        <div className="text-muted-foreground text-sm">{t.common.loading}</div>
      ) : pats.length === 0 ? (
        <div className="text-muted-foreground rounded-md border border-dashed p-4 text-sm">
          <div className="font-medium">{t.settings.tokens.emptyTitle}</div>
          <div className="mt-1">{t.settings.tokens.emptyDescription}</div>
        </div>
      ) : (
        <div className="space-y-2">
          {pats.map((pat) => (
            <Item key={pat.id}>
              <ItemContent>
                <ItemTitle className="flex items-center gap-2">
                  <span>{pat.name}</span>
                  {pat.revoked_at !== null ? (
                    <Badge variant="secondary">
                      {t.settings.tokens.revokedBadge}
                    </Badge>
                  ) : isExpired(pat) ? (
                    <Badge variant="outline">
                      {t.settings.tokens.expiredBadge}
                    </Badge>
                  ) : null}
                </ItemTitle>
                {/* Metadata and scopes as siblings (not inside
                    ItemDescription) so the line-clamp on that slot cannot
                    clip security-relevant data. */}
                <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                  <span>
                    {t.settings.tokens.created}: {formatTimeAgo(pat.created_at)}
                  </span>
                  <span>
                    {pat.revoked_at !== null
                      ? `${t.settings.tokens.revokedBadge}: ${formatTimeAgo(pat.revoked_at)}`
                      : pat.expires_at === null
                        ? t.settings.tokens.neverExpires
                        : `${t.settings.tokens.expires}: ${formatExpiry(pat)}`}
                  </span>
                  <span>
                    {t.settings.tokens.lastUsed}:{" "}
                    {pat.last_used_at === null
                      ? t.settings.tokens.neverUsed
                      : formatTimeAgo(pat.last_used_at)}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {pat.scopes.map((scope) => (
                    <Badge key={scope} variant="outline">
                      {scope}
                    </Badge>
                  ))}
                </div>
              </ItemContent>
              <ItemActions>
                {pat.revoked_at === null ? (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-destructive hover:text-destructive shrink-0"
                    onClick={() => setRevoking(pat)}
                    disabled={revoke.isPending}
                    title={t.settings.tokens.revoke}
                    aria-label={t.settings.tokens.revoke}
                  >
                    <Trash2Icon className="h-4 w-4" />
                  </Button>
                ) : null}
              </ItemActions>
            </Item>
          ))}
        </div>
      )}

      {/* A transient list error (retries exhausted, 5xx, network) hides the
          list, not the create affordance — creation hits the same store and
          may well succeed; only the memory-backend 503 means it cannot. */}
      {!storeUnavailable ? (
        <div className="mt-4">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              resetCreateForm();
              setCreated(null);
              setCreateOpen(true);
            }}
          >
            <PlusIcon className="h-4 w-4" />
            {t.settings.tokens.createButton}
          </Button>
        </div>
      ) : null}

      <Dialog
        open={createOpen}
        onOpenChange={(open) => {
          // In the show-once result state -- and while the create request is
          // in flight (the response carries the only copy of the token) --
          // the dialog must not be dismissed by an accidental overlay click
          // or Escape; only the explicit button closes it.
          if (!open && (created !== null || create.isPending)) return;
          if (!open) {
            closeCreateDialog();
          } else {
            setCreateOpen(true);
          }
        }}
      >
        <DialogContent
          showCloseButton={created === null && !create.isPending}
          className="max-h-[85vh] overflow-y-auto"
        >
          {created === null ? (
            <>
              <DialogHeader>
                <DialogTitle>{t.settings.tokens.createTitle}</DialogTitle>
                <DialogDescription>
                  {t.settings.tokens.createDescription}
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <div className="space-y-2">
                  <label
                    className="text-sm font-medium"
                    htmlFor="pat-create-name"
                  >
                    {t.settings.tokens.nameLabel}
                  </label>
                  <Input
                    id="pat-create-name"
                    value={name}
                    placeholder={t.settings.tokens.namePlaceholder}
                    onChange={(event) => setName(event.target.value)}
                    maxLength={128}
                  />
                </div>
                <div className="space-y-2">
                  <div className="text-sm font-medium">
                    {t.settings.tokens.scopesLabel}
                  </div>
                  <div className="space-y-2">
                    {PAT_SCOPES.map((scope) => (
                      <label
                        key={scope}
                        className="hover:bg-accent/50 flex cursor-pointer items-start justify-between gap-3 rounded-md border p-2"
                        // Safari/WebKit never implemented label->button click
                        // forwarding, so the text would be a dead click target
                        // there. Toggle explicitly and preventDefault so
                        // engines that DO forward don't fire it twice; clicks
                        // on the switch itself pass through untouched.
                        onClick={(event) => {
                          if (
                            (event.target as HTMLElement).closest(
                              "[role=switch]",
                            )
                          ) {
                            return;
                          }
                          event.preventDefault();
                          toggleScope(scope, !scopes.has(scope));
                        }}
                      >
                        <span className="space-y-0.5">
                          <span className="text-sm font-medium">
                            {t.settings.tokens.scopes[scope].name}
                          </span>
                          <span className="text-muted-foreground block text-xs">
                            {t.settings.tokens.scopes[scope].description}
                          </span>
                        </span>
                        <Switch
                          checked={scopes.has(scope)}
                          onCheckedChange={(enabled) =>
                            toggleScope(scope, enabled)
                          }
                          aria-label={t.settings.tokens.scopes[scope].name}
                        />
                      </label>
                    ))}
                  </div>
                </div>
                <div className="space-y-2">
                  <label
                    className="text-sm font-medium"
                    htmlFor="pat-create-expiry"
                  >
                    {t.settings.tokens.expiryLabel}
                  </label>
                  <Select value={expiry} onValueChange={setExpiry}>
                    <SelectTrigger id="pat-create-expiry" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {EXPIRY_CHOICES.map((choice) => (
                        <SelectItem key={choice.value} value={choice.value}>
                          {choice.value === "never"
                            ? t.settings.tokens.expiryNever
                            : t.settings.tokens.expiryDays.replace(
                                "{days}",
                                String(choice.days),
                              )}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={closeCreateDialog}
                  disabled={create.isPending}
                >
                  {t.common.cancel}
                </Button>
                <Button
                  onClick={() => void handleCreate()}
                  disabled={create.isPending || !nameValid || !scopesValid}
                >
                  {create.isPending
                    ? t.common.loading
                    : t.settings.tokens.createSubmit}
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <KeyRoundIcon className="h-4 w-4" />
                  {t.settings.tokens.resultTitle}
                </DialogTitle>
                <DialogDescription>
                  {t.settings.tokens.resultDescription}
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-3">
                <div className="bg-muted rounded-md p-3 font-mono text-sm break-all">
                  {created.token}
                </div>
                <div className="text-destructive text-sm">
                  {t.settings.tokens.warning}
                </div>
              </div>
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => void handleCopyToken()}
                >
                  {copied ? t.settings.tokens.copied : t.settings.tokens.copy}
                </Button>
                <Button onClick={closeCreateDialog}>
                  {t.settings.tokens.done}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={revoking !== null}
        onOpenChange={(open) => {
          // Same pending-guard discipline as the create dialog, so Escape
          // cannot silently swallow an in-flight revocation.
          if (!open && revoke.isPending) return;
          if (!open) setRevoking(null);
        }}
      >
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {t.settings.tokens.revokeTitle.replace(
                "{name}",
                () => revoking?.name ?? "",
              )}
            </DialogTitle>
            <DialogDescription>
              {t.settings.tokens.revokeDescription}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRevoking(null)}
              disabled={revoke.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleRevoke()}
              disabled={revoke.isPending}
            >
              {revoke.isPending
                ? t.common.loading
                : t.settings.tokens.revokeConfirm}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SettingsSection>
  );
}
