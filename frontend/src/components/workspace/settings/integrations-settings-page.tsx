"use client";

import {
  CheckCircle2Icon,
  CopyIcon,
  ExternalLinkIcon,
  PlugZapIcon,
  RefreshCwIcon,
  XCircleIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import {
  LarkIntegrationRequestError,
  type LarkAuthStartRequest,
  type LarkAuthStartResponse,
  type LarkConfigStartResponse,
  type LarkIntegrationStatus,
  useCompleteLarkAuthorization,
  useCompleteLarkConfiguration,
  useInstallLarkIntegration,
  useLarkIntegrationStatus,
  useStartLarkAuthorization,
  useStartLarkConfiguration,
} from "@/core/integrations/lark";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

type PendingLarkFlow =
  | ({ kind: "config" } & LarkConfigStartResponse)
  | ({ kind: "auth" } & LarkAuthStartResponse);

type LarkAuthDomain =
  | "approval"
  | "apps"
  | "attendance"
  | "base"
  | "calendar"
  | "contact"
  | "docs"
  | "drive"
  | "event"
  | "im"
  | "mail"
  | "markdown"
  | "mindnotes"
  | "minutes"
  | "note"
  | "okr"
  | "sheets"
  | "slides"
  | "task"
  | "vc"
  | "wiki"
  | "all";

// Mirrors `lark-cli auth login --domain` (available business domains + all).
const LARK_AUTH_DOMAINS: LarkAuthDomain[] = [
  "calendar",
  "im",
  "docs",
  "drive",
  "sheets",
  "base",
  "wiki",
  "task",
  "mail",
  "vc",
  "minutes",
  "note",
  "slides",
  "markdown",
  "mindnotes",
  "contact",
  "approval",
  "attendance",
  "okr",
  "event",
  "apps",
  "all",
];

const AUTOMATIC_LARK_AUTH_WAIT_SECONDS = 8;

function splitScopes(value: string) {
  return value
    .split(/[\s,]+/)
    .map((scope) => scope.trim())
    .filter(Boolean);
}

function uniqueScopes(scopes: string[]) {
  return Array.from(new Set(scopes));
}

export function IntegrationsSettingsPage() {
  const { t } = useI18n();
  return (
    <SettingsSection
      title={t.settings.integrations.title}
      description={t.settings.integrations.description}
    >
      <LarkIntegrationCard />
    </SettingsSection>
  );
}

function LarkIntegrationCard() {
  const { t } = useI18n();
  const { user } = useAuth();
  const isAdmin = user?.system_role === "admin";
  const { data, isLoading, error, refetch, isFetching } =
    useLarkIntegrationStatus();
  const install = useInstallLarkIntegration();
  const startConfig = useStartLarkConfiguration();
  const completeConfig = useCompleteLarkConfiguration();
  const startAuth = useStartLarkAuthorization();
  const completeAuth = useCompleteLarkAuthorization();
  const [pendingFlow, setPendingFlow] = useState<PendingLarkFlow | null>(null);
  const [isCheckingConnection, setIsCheckingConnection] = useState(false);
  const [selectedAuthDomains, setSelectedAuthDomains] = useState<
    LarkAuthDomain[]
  >([]);
  const [customAuthScope, setCustomAuthScope] = useState("");
  const browserWindowRef = useRef<Window | null>(null);
  const authRequestRef = useRef<LarkAuthStartRequest>({ recommend: false });
  const authToastIdRef = useRef<string | number | null>(null);
  const authRetryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const authAttemptIdRef = useRef(0);
  const authDeadlineRef = useRef(0);
  const isMountedRef = useRef(true);
  const connectBusy =
    startConfig.isPending || completeConfig.isPending || startAuth.isPending;
  const connectActionBusy = connectBusy || isCheckingConnection;
  const credentialsConfigured = data?.auth.status === "authenticated";
  const isConnected = credentialsConfigured && data?.auth.verified === true;
  // The sandbox-runtime readiness row only applies when the sandbox actually
  // runs lark-cli (AIO / provisioner modes report a non-"none" mode).
  const showSandboxRuntime = !!data && data.sandbox_runtime_mode !== "none";
  const trimmedCustomAuthScope = customAuthScope.trim();
  const hasAdditionalPermissionRequest =
    selectedAuthDomains.length > 0 || trimmedCustomAuthScope.length > 0;

  const handleInstall = () => {
    install.mutate(undefined, {
      onSuccess: (result) => toast.success(result.message),
      onError: (err) => {
        if (err instanceof LarkIntegrationRequestError && err.isAdminRequired) {
          toast.error(t.settings.integrations.adminRequired);
          return;
        }
        toast.error(err instanceof Error ? err.message : String(err));
      },
    });
  };

  const clearAuthRetryTimer = () => {
    if (authRetryTimeoutRef.current != null) {
      clearTimeout(authRetryTimeoutRef.current);
      authRetryTimeoutRef.current = null;
    }
  };

  useEffect(
    () => () => {
      isMountedRef.current = false;
      if (authRetryTimeoutRef.current != null) {
        clearTimeout(authRetryTimeoutRef.current);
      }
    },
    [],
  );

  const openPendingBrowserWindow = () => {
    const browserWindow = window.open("about:blank", "_blank");
    if (browserWindow) {
      browserWindow.opener = null;
      browserWindowRef.current = browserWindow;
    }
    return browserWindow;
  };

  const closePendingBrowserWindow = (browserWindow: Window | null) => {
    if (!browserWindow) return;
    browserWindow.close();
    if (browserWindowRef.current === browserWindow) {
      browserWindowRef.current = null;
    }
  };

  const openAuthorizationUrl = (
    url: string,
    browserWindow = browserWindowRef.current,
  ) => {
    if (browserWindow && !browserWindow.closed) {
      browserWindow.location.href = url;
      browserWindowRef.current = browserWindow;
      return;
    }
    browserWindowRef.current = window.open(
      url,
      "_blank",
      "noopener,noreferrer",
    );
  };

  const startUserAuth = (
    browserWindow = browserWindowRef.current,
    request = authRequestRef.current,
  ) => {
    startAuth.mutate(request, {
      onSuccess: (result) => {
        setPendingFlow({ kind: "auth", ...result });
        openAuthorizationUrl(result.verification_url, browserWindow);
        authToastIdRef.current = toast.info(
          t.settings.integrations.lark.authStarted,
        );
        startAutomaticAuthorizationCheck(result);
      },
      onError: (err) => {
        closePendingBrowserWindow(browserWindow);
        toast.error(err instanceof Error ? err.message : String(err));
      },
    });
  };

  const handleContinueConnection = () => {
    if (!pendingFlow || pendingFlow.kind !== "config") return;
    completeConfig.mutate(
      {
        device_code: pendingFlow.device_code,
        brand: pendingFlow.brand,
        interval: pendingFlow.interval,
        expires_in: pendingFlow.expires_in,
      },
      {
        onSuccess: () => {
          toast.success(t.settings.integrations.lark.connectionReady);
          setPendingFlow(null);
          startUserAuth(browserWindowRef.current);
        },
        onError: (err) => {
          setPendingFlow(null);
          toast.error(err instanceof Error ? err.message : String(err));
        },
      },
    );
  };

  const startConnectionFlow = (
    status: LarkIntegrationStatus,
    browserWindow: Window | null,
  ) => {
    if (!status.app_configured) {
      startConfig.mutate(
        { brand: "feishu" },
        {
          onSuccess: (result) => {
            setPendingFlow({ kind: "config", ...result });
            openAuthorizationUrl(result.verification_url, browserWindow);
            toast.success(t.settings.integrations.lark.connectionStarted);
          },
          onError: (err) => {
            closePendingBrowserWindow(browserWindow);
            toast.error(err instanceof Error ? err.message : String(err));
          },
        },
      );
      return;
    }
    startUserAuth(browserWindow);
  };

  const buildAuthRequest = (): LarkAuthStartRequest => {
    const domains = selectedAuthDomains.includes("all")
      ? ["all"]
      : uniqueScopes(selectedAuthDomains);
    const scopes = uniqueScopes(splitScopes(trimmedCustomAuthScope));
    return {
      recommend: false,
      domains,
      scope: scopes.length > 0 ? scopes.join(" ") : null,
    };
  };

  const toggleAuthDomain = (domain: LarkAuthDomain) => {
    setSelectedAuthDomains((current) => {
      if (domain === "all") {
        return current.includes("all") ? [] : ["all"];
      }
      const withoutAll = current.filter((item) => item !== "all");
      if (withoutAll.includes(domain)) {
        return withoutAll.filter((item) => item !== domain);
      }
      return [...withoutAll, domain];
    });
  };

  const handleConnect = async () => {
    if (!data) return;
    authRequestRef.current = buildAuthRequest();
    // Pre-open the blank tab synchronously inside the click gesture. We cannot
    // trust the cached auth status here: an `authenticated` cache can be stale
    // (session expired server-side), and if we skipped the pre-open and then
    // discovered that only after `await refetch()`, the later `window.open`
    // would run outside the user gesture and be blocked by the browser. Opening
    // now and closing below when it turns out unneeded keeps the popup reliable.
    const browserWindow = openPendingBrowserWindow();
    setIsCheckingConnection(true);
    try {
      const refreshed = await refetch();
      const latestStatus = refreshed.data ?? data;
      startConnectionFlow(latestStatus, browserWindow);
    } catch (err) {
      closePendingBrowserWindow(browserWindow);
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setIsCheckingConnection(false);
    }
  };

  const completeAuthorization = (
    deviceCode: string,
    { automatic, attemptId }: { automatic: boolean; attemptId?: number },
  ) => {
    const toastOptions =
      authToastIdRef.current == null
        ? undefined
        : { id: authToastIdRef.current };
    completeAuth.mutate(
      {
        device_code: deviceCode,
        ...(automatic
          ? { wait_timeout_seconds: AUTOMATIC_LARK_AUTH_WAIT_SECONDS }
          : {}),
      },
      {
        onSuccess: (result) => {
          // react-query still fires this after the dialog unmounts; bail so we
          // don't toast, setState, refetch, or reschedule a retry timer on a
          // component that is gone.
          if (!isMountedRef.current) {
            return;
          }
          if (automatic && attemptId !== authAttemptIdRef.current) {
            return;
          }
          if (result.success) {
            clearAuthRetryTimer();
            toast.success(result.message, toastOptions);
            authToastIdRef.current = null;
            setPendingFlow(null);
            browserWindowRef.current = null;
            return;
          }
          toast.info(
            result.message ||
              t.settings.integrations.lark.authorizationStillPending,
            toastOptions,
          );
          if (automatic && attemptId != null) {
            scheduleAuthorizationRetry(deviceCode, attemptId);
          }
        },
        onError: (err) => {
          if (!isMountedRef.current) {
            return;
          }
          if (automatic && attemptId !== authAttemptIdRef.current) {
            return;
          }
          if (
            automatic &&
            err instanceof LarkIntegrationRequestError &&
            err.status === 504
          ) {
            toast.info(
              t.settings.integrations.lark.authorizationStillPending,
              toastOptions,
            );
            if (attemptId != null) {
              scheduleAuthorizationRetry(deviceCode, attemptId);
            }
            return;
          }
          toast.error(
            err instanceof Error ? err.message : String(err),
            toastOptions,
          );
          authToastIdRef.current = null;
        },
      },
    );
  };

  const scheduleAuthorizationRetry = (
    deviceCode: string,
    attemptId: number,
  ) => {
    clearAuthRetryTimer();
    if (!isMountedRef.current) {
      return;
    }
    if (Date.now() >= authDeadlineRef.current) {
      toast.info(t.settings.integrations.lark.authorizationStillPending);
      return;
    }
    authRetryTimeoutRef.current = setTimeout(() => {
      completeAuthorization(deviceCode, { automatic: true, attemptId });
    }, 1500);
  };

  const startAutomaticAuthorizationCheck = (result: LarkAuthStartResponse) => {
    clearAuthRetryTimer();
    const attemptId = authAttemptIdRef.current + 1;
    authAttemptIdRef.current = attemptId;
    authDeadlineRef.current =
      Date.now() + Math.max(result.expires_in ?? 300, 30) * 1000;
    completeAuthorization(result.device_code, { automatic: true, attemptId });
  };

  const handleCompleteAuth = () => {
    if (!pendingFlow) return;
    if (pendingFlow.kind !== "auth") {
      return;
    }
    clearAuthRetryTimer();
    authAttemptIdRef.current += 1;
    completeAuthorization(pendingFlow.device_code, { automatic: false });
  };

  const handleCopyAuthLink = async () => {
    if (!pendingFlow) return;
    try {
      await navigator.clipboard.writeText(pendingFlow.verification_url);
      toast.success(t.clipboard.copiedToClipboard);
    } catch {
      toast.error(t.clipboard.failedToCopyToClipboard);
    }
  };

  const installDisabled =
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
    !isAdmin ||
    install.isPending;
  const authDisabled =
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
    !data?.installed ||
    !data?.cli.available ||
    connectActionBusy;

  const connectButtonLabel = isCheckingConnection
    ? t.settings.integrations.lark.checkingConnection
    : connectBusy
      ? t.settings.integrations.lark.authStarting
      : credentialsConfigured && hasAdditionalPermissionRequest
        ? t.settings.integrations.lark.requestPermissions
        : credentialsConfigured
          ? t.settings.integrations.lark.connectedAction
          : t.settings.integrations.lark.connect;

  const permissionDomains = LARK_AUTH_DOMAINS.map((id) => ({
    id,
    label: t.settings.integrations.lark.authDomains[id].label,
    description: t.settings.integrations.lark.authDomains[id].description,
  }));

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="bg-primary/10 text-primary rounded-lg p-2">
            <PlugZapIcon className="size-5" />
          </div>
          <div>
            <CardTitle>{t.settings.integrations.lark.title}</CardTitle>
            <CardDescription>
              {t.settings.integrations.lark.description}
            </CardDescription>
          </div>
        </div>
        <CardAction>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
          >
            <RefreshCwIcon
              className={cn("size-4", isFetching && "animate-spin")}
            />
            {t.settings.integrations.refresh}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <div className="text-muted-foreground text-sm">
            {t.common.loading}
          </div>
        ) : error ? (
          <Alert variant="destructive">
            <XCircleIcon />
            <AlertTitle>{t.settings.integrations.loadFailed}</AlertTitle>
            <AlertDescription>
              {error instanceof Error ? error.message : String(error)}
            </AlertDescription>
          </Alert>
        ) : data ? (
          <>
            <div
              className={cn(
                "grid gap-3",
                showSandboxRuntime ? "md:grid-cols-4" : "md:grid-cols-3",
              )}
            >
              <StatusItem
                label={t.settings.integrations.lark.skillPack}
                ok={data.installed}
                value={
                  data.installed
                    ? t.settings.integrations.lark.skillsInstalled(
                        data.skills_installed,
                        data.skills_expected,
                      )
                    : t.settings.integrations.lark.notInstalled
                }
              />
              <StatusItem
                label={t.settings.integrations.lark.gatewayCli}
                ok={data.cli.available}
                value={
                  data.cli.available
                    ? (data.cli.version ?? t.settings.integrations.available)
                    : (data.cli.error ?? t.settings.integrations.unavailable)
                }
              />
              <StatusItem
                label={t.settings.integrations.lark.auth}
                ok={isConnected}
                value={
                  data.auth.status === "authenticated"
                    ? data.auth.verified
                      ? (data.auth.user ?? t.settings.integrations.connected)
                      : data.auth.user
                        ? t.settings.integrations.lark.authConfiguredFor(
                            data.auth.user,
                          )
                        : t.settings.integrations.lark.authConfigured
                    : t.settings.integrations.lark.authNotConfigured
                }
              />
              {showSandboxRuntime && (
                <StatusItem
                  label={t.settings.integrations.lark.sandboxRuntime}
                  ok={data.sandbox_runtime_ready}
                  value={
                    data.sandbox_runtime_ready
                      ? data.sandbox_runtime_mode === "init-container"
                        ? t.settings.integrations.lark
                            .sandboxRuntimeInitContainer
                        : t.settings.integrations.lark
                            .sandboxRuntimeGatewayDownload
                      : (data.sandbox_runtime_detail ??
                        t.settings.integrations.lark.sandboxRuntimeNotReady)
                  }
                />
              )}
            </div>
            {data.installed && (
              <div className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                <span>
                  {t.settings.integrations.lark.installedVersion(
                    data.manifest_version ?? data.version,
                  )}
                </span>
                {data.latest_available_version &&
                  data.latest_available_version !==
                    (data.manifest_version ?? data.version) && (
                    <span className="text-amber-600 dark:text-amber-500">
                      {t.settings.integrations.lark.updateAvailable(
                        data.latest_available_version,
                      )}
                    </span>
                  )}
                {data.runtime_version_mismatch && (
                  <span className="text-amber-600 dark:text-amber-500">
                    {t.settings.integrations.lark.runtimeVersionMismatch}
                  </span>
                )}
              </div>
            )}
            <IntegrationNextStep
              installed={data.installed}
              cliReady={data.cli.available}
              connected={isConnected}
              credentialsConfigured={credentialsConfigured}
            />
            {data.installed && data.cli.available && (
              <div className="rounded-lg border p-3">
                <div className="space-y-1">
                  <div className="text-sm font-medium">
                    {t.settings.integrations.lark.permissionTitle}
                  </div>
                  <p className="text-muted-foreground text-sm">
                    {t.settings.integrations.lark.permissionDescription}
                  </p>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {permissionDomains.map((domain) => {
                    const selected = selectedAuthDomains.includes(domain.id);
                    return (
                      <Button
                        key={domain.id}
                        type="button"
                        size="sm"
                        variant={selected ? "default" : "outline"}
                        onClick={() => toggleAuthDomain(domain.id)}
                        disabled={connectActionBusy}
                        title={domain.description}
                      >
                        {domain.label}
                      </Button>
                    );
                  })}
                </div>
                <div className="mt-3 space-y-1">
                  <Input
                    value={customAuthScope}
                    onChange={(event) =>
                      setCustomAuthScope(event.currentTarget.value)
                    }
                    disabled={connectActionBusy}
                    placeholder={
                      t.settings.integrations.lark.customScopePlaceholder
                    }
                    aria-label={t.settings.integrations.lark.customScopeLabel}
                  />
                  <p className="text-muted-foreground text-xs">
                    {t.settings.integrations.lark.customScopeDescription}
                  </p>
                </div>
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={handleInstall} disabled={installDisabled}>
                {install.isPending ? (
                  <RefreshCwIcon className="size-4 animate-spin" />
                ) : null}
                {install.isPending
                  ? t.settings.integrations.installing
                  : data.installed
                    ? t.settings.integrations.reinstall
                    : t.settings.integrations.install}
              </Button>
              <Button
                variant="outline"
                onClick={() => void handleConnect()}
                disabled={authDisabled}
              >
                {connectActionBusy ? (
                  <RefreshCwIcon className="size-4 animate-spin" />
                ) : null}
                {connectButtonLabel}
              </Button>
              {!isAdmin && (
                <span className="text-muted-foreground text-sm">
                  {t.settings.integrations.adminRequired}
                </span>
              )}
            </div>
            {install.isPending && (
              <Alert>
                <RefreshCwIcon className="size-4 animate-spin" />
                <AlertTitle>
                  {t.settings.integrations.lark.installingTitle}
                </AlertTitle>
                <AlertDescription>
                  {t.settings.integrations.lark.installingDescription}
                </AlertDescription>
              </Alert>
            )}
            {pendingFlow && (
              <Alert>
                <ExternalLinkIcon />
                <AlertTitle>
                  {pendingFlow.kind === "config"
                    ? t.settings.integrations.lark.openConnectionLinkTitle
                    : completeAuth.isPending
                      ? t.settings.integrations.lark.waitingAuthTitle
                      : t.settings.integrations.lark.openAuthLinkTitle}
                </AlertTitle>
                <AlertDescription>
                  <div className="space-y-3">
                    <p>
                      {pendingFlow.kind === "config"
                        ? t.settings.integrations.lark
                            .openConnectionLinkDescription
                        : completeAuth.isPending
                          ? t.settings.integrations.lark.waitingAuthDescription
                          : t.settings.integrations.lark
                              .openAuthLinkDescription}
                    </p>
                    <div className="bg-muted text-foreground rounded-md px-3 py-2 text-xs break-all">
                      {pendingFlow.verification_url}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" asChild>
                        <a
                          href={pendingFlow.verification_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <ExternalLinkIcon className="size-4" />
                          {t.settings.integrations.lark.openAuthLink}
                        </a>
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void handleCopyAuthLink()}
                      >
                        <CopyIcon className="size-4" />
                        {t.settings.integrations.lark.copyAuthLink}
                      </Button>
                      {pendingFlow.kind === "config" ? (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={handleContinueConnection}
                          disabled={completeConfig.isPending}
                        >
                          {completeConfig.isPending ? (
                            <RefreshCwIcon className="size-4 animate-spin" />
                          ) : null}
                          {completeConfig.isPending
                            ? t.settings.integrations.lark
                                .preparingAuthorization
                            : t.settings.integrations.lark.continueAuth}
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="default"
                          onClick={handleCompleteAuth}
                          disabled={completeAuth.isPending}
                        >
                          {completeAuth.isPending
                            ? t.settings.integrations.lark.completingAuth
                            : t.settings.integrations.lark.completeAuth}
                        </Button>
                      )}
                    </div>
                    {pendingFlow.expires_in != null && (
                      <p className="text-muted-foreground text-xs">
                        {t.settings.integrations.lark.authExpiresIn(
                          pendingFlow.expires_in,
                        )}
                      </p>
                    )}
                  </div>
                </AlertDescription>
              </Alert>
            )}
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

function StatusItem({
  label,
  ok,
  value,
}: {
  label: string;
  ok: boolean;
  value: string;
}) {
  const { t } = useI18n();
  return (
    <div className="rounded-lg border p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-sm font-medium">{label}</div>
        <Badge variant={ok ? "secondary" : "outline"}>
          {ok ? (
            <CheckCircle2Icon className="size-3" />
          ) : (
            <XCircleIcon className="size-3" />
          )}
          {ok ? t.settings.integrations.ready : t.settings.integrations.pending}
        </Badge>
      </div>
      <div className="text-muted-foreground text-sm break-words">{value}</div>
    </div>
  );
}

function IntegrationNextStep({
  installed,
  cliReady,
  connected,
  credentialsConfigured,
}: {
  installed: boolean;
  cliReady: boolean;
  connected: boolean;
  credentialsConfigured: boolean;
}) {
  const { t } = useI18n();
  if (!installed) {
    return (
      <Alert>
        <AlertTitle>{t.settings.integrations.lark.installNextTitle}</AlertTitle>
        <AlertDescription>
          {t.settings.integrations.lark.installNextDescription}
        </AlertDescription>
      </Alert>
    );
  }
  if (!cliReady) {
    return (
      <Alert>
        <AlertTitle>{t.settings.integrations.lark.cliNextTitle}</AlertTitle>
        <AlertDescription>
          {t.settings.integrations.lark.cliNextDescription}
        </AlertDescription>
      </Alert>
    );
  }
  if (connected) {
    return (
      <Alert>
        <CheckCircle2Icon />
        <AlertTitle>{t.settings.integrations.lark.connectedTitle}</AlertTitle>
        <AlertDescription>
          {t.settings.integrations.lark.connectedDescription}
        </AlertDescription>
      </Alert>
    );
  }
  if (credentialsConfigured) {
    return (
      <Alert>
        <CheckCircle2Icon />
        <AlertTitle>{t.settings.integrations.lark.configuredTitle}</AlertTitle>
        <AlertDescription>
          {t.settings.integrations.lark.configuredDescription}
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <Alert>
      <ExternalLinkIcon />
      <AlertTitle>{t.settings.integrations.lark.authNextTitle}</AlertTitle>
      <AlertDescription>
        {t.settings.integrations.lark.authNextDescription}
      </AlertDescription>
    </Alert>
  );
}
