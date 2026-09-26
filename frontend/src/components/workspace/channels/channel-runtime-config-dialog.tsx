"use client";

import {
  KeyRoundIcon,
  LoaderCircleIcon,
  QrCodeIcon,
  ShieldCheckIcon,
} from "lucide-react";
import {
  type CSSProperties,
  type FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type {
  ChannelProvider,
  ChannelRuntimeConfigValues,
} from "@/core/channels/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { ChannelProviderIcon } from "./channel-provider-icon";
import {
  WechatQRCompletion,
  type PendingWechatBinding,
} from "./wechat-qr-completion";
import { WechatQRLogin } from "./wechat-qr-login";

type ChannelRuntimeConfigDialogProps = {
  onConfigured?: (provider: ChannelProvider) => void;
  provider: ChannelProvider | null;
  open: boolean;
  submitting: boolean;
  initialStep?: "setup" | "binding";
  onOpenChange: (open: boolean) => void;
  onSubmit: (
    provider: ChannelProvider,
    values: ChannelRuntimeConfigValues,
  ) => void | Promise<ChannelProvider | void>;
};

type SecretInputStyle = CSSProperties & { WebkitTextSecurity?: "disc" };
const SECRET_INPUT_STYLE: SecretInputStyle = { WebkitTextSecurity: "disc" };

export function ChannelRuntimeConfigDialog({
  provider,
  open,
  submitting,
  onOpenChange,
  onSubmit,
  onConfigured,
  initialStep = "setup",
}: ChannelRuntimeConfigDialogProps) {
  const { t } = useI18n();
  const submissionGeneration = useRef(0);
  const [step, setStep] = useState<"setup" | null>(null);
  const [configuredProvider, setConfiguredProvider] =
    useState<ChannelProvider | null>(null);
  const [pendingBinding, setPendingBinding] =
    useState<PendingWechatBinding | null>(null);
  const [method, setMethod] = useState<"qr" | "token" | null>(null);
  useEffect(() => {
    submissionGeneration.current += 1;
    setStep(null);
    setMethod(null);
    setConfiguredProvider(null);
    setPendingBinding(null);
    return () => {
      submissionGeneration.current += 1;
    };
  }, [open, provider?.provider, initialStep]);
  const [values, setValues] = useState<ChannelRuntimeConfigValues>({});
  const fields = useMemo(
    () => provider?.credential_fields ?? [],
    [provider?.credential_fields],
  );
  const credentialValues = useMemo<ChannelRuntimeConfigValues>(
    () => provider?.credential_values ?? {},
    [provider?.credential_values],
  );

  useEffect(() => {
    if (!open || !provider) {
      setValues({});
      return;
    }
    setValues(
      Object.fromEntries(
        fields.map((field) => [field.name, credentialValues[field.name] ?? ""]),
      ) as ChannelRuntimeConfigValues,
    );
  }, [credentialValues, fields, open, provider]);

  if (!provider) return null;
  const isEditing = provider.configured;
  const hasWechatQR = provider.provider === "wechat" && !!onConfigured;
  const selectedMethod = method ?? (isEditing ? "token" : "qr");
  const completionProvider =
    configuredProvider ??
    (step === null && initialStep === "binding" && provider.configured
      ? provider
      : null);
  const showQR = hasWechatQR && !completionProvider && selectedMethod === "qr";
  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) submissionGeneration.current += 1;
    onOpenChange(nextOpen);
  };
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (showQR || completionProvider) return;
    const generation = submissionGeneration.current;
    const submission = onSubmit(provider, values);
    if (hasWechatQR && submission) {
      void submission.then((updated) => {
        if (updated && submissionGeneration.current === generation)
          setConfiguredProvider(updated);
      });
    }
  };

  const credentialInputs = (
    <div className="space-y-4">
      {fields.map((field) => {
        const inputId = `channel-${provider.provider}-${field.name}`;
        const isSecretField = field.type === "password";
        return (
          <div key={field.name} className="space-y-2">
            <label
              htmlFor={inputId}
              className="text-sm leading-none font-medium"
            >
              {field.label}
            </label>
            <Input
              id={inputId}
              type="text"
              value={values[field.name] ?? ""}
              required={field.required}
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              className={cn(hasWechatQR && "h-11 rounded-lg")}
              placeholder={
                hasWechatQR ? t.channels.wechatQr.tokenPlaceholder : undefined
              }
              data-1p-ignore={isSecretField ? "true" : undefined}
              data-bwignore={isSecretField ? "true" : undefined}
              data-form-type={isSecretField ? "other" : undefined}
              data-lpignore={isSecretField ? "true" : undefined}
              style={isSecretField ? SECRET_INPUT_STYLE : undefined}
              onChange={(event) => {
                setValues((current) => ({
                  ...current,
                  [field.name]: event.target.value,
                }));
              }}
            />
          </div>
        );
      })}
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className={cn(
          hasWechatQR &&
            "max-h-[calc(100dvh-2rem)] overflow-y-auto rounded-2xl sm:max-w-[440px]",
        )}
      >
        <form
          onSubmit={handleSubmit}
          className={cn("space-y-4", hasWechatQR && "space-y-5")}
        >
          <div className={cn(hasWechatQR && "flex items-center gap-3 pr-4")}>
            {hasWechatQR ? (
              <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10">
                <ChannelProviderIcon provider="wechat" className="size-7" />
              </div>
            ) : null}
            <DialogHeader className={cn(hasWechatQR && "gap-1 text-left")}>
              <DialogTitle>
                {isEditing && !completionProvider
                  ? t.channels.setupEditTitle(provider.display_name)
                  : t.channels.setupTitle(provider.display_name)}
              </DialogTitle>
              <DialogDescription
                className={cn(hasWechatQR && "text-xs leading-relaxed")}
              >
                {hasWechatQR
                  ? t.channels.wechatQr.description
                  : t.channels.setupDescription}
              </DialogDescription>
            </DialogHeader>
          </div>

          {hasWechatQR && completionProvider ? (
            <WechatQRCompletion
              provider={completionProvider}
              onDone={() => onConfigured?.(completionProvider)}
              bindingToResume={pendingBinding}
              onRestart={(binding) => {
                setPendingBinding(binding);
                setStep("setup");
                setMethod("qr");
                setConfiguredProvider(null);
              }}
            />
          ) : hasWechatQR ? (
            <Tabs
              value={selectedMethod}
              onValueChange={(value) => {
                if (value === "qr" || value === "token") setMethod(value);
              }}
              className="gap-0"
            >
              <TabsList
                aria-label={t.channels.wechatQr.methodLabel}
                className="grid w-full grid-cols-2"
              >
                <TabsTrigger value="qr" disabled={submitting}>
                  <QrCodeIcon />
                  {t.channels.wechatQr.login}
                </TabsTrigger>
                <TabsTrigger value="token" disabled={submitting}>
                  <KeyRoundIcon />
                  {t.channels.wechatQr.manual}
                </TabsTrigger>
              </TabsList>
              <TabsContent value="qr" className="pt-5">
                {showQR && open ? (
                  <WechatQRLogin onConfigured={setConfiguredProvider} />
                ) : null}
              </TabsContent>
              <TabsContent value="token" className="pt-5">
                <div className="flex min-h-[328px] flex-col justify-center gap-6 pb-5">
                  <div className="space-y-2">
                    <h3 className="text-sm font-medium">
                      {t.channels.wechatQr.tokenTitle}
                    </h3>
                    <p className="text-muted-foreground text-sm leading-relaxed">
                      {t.channels.wechatQr.tokenDescription}
                    </p>
                  </div>
                  {credentialInputs}
                  <p className="text-muted-foreground text-xs leading-relaxed">
                    {t.channels.wechatQr.tokenHint}
                  </p>
                </div>
              </TabsContent>
            </Tabs>
          ) : (
            credentialInputs
          )}

          {hasWechatQR ? (
            <p className="text-muted-foreground flex items-center justify-center gap-1.5 text-xs">
              <ShieldCheckIcon className="size-3.5" />
              {t.channels.wechatQr.privacy}
            </p>
          ) : null}
          {!completionProvider && (
            <DialogFooter className={cn(hasWechatQR && "border-t pt-4")}>
              <Button
                type="button"
                variant="outline"
                disabled={submitting}
                onClick={() => handleOpenChange(false)}
              >
                {t.common.cancel}
              </Button>
              {!showQR ? (
                <Button type="submit" disabled={submitting}>
                  {submitting ? (
                    <LoaderCircleIcon className="animate-spin" />
                  ) : null}
                  {isEditing
                    ? t.channels.saveChanges
                    : t.channels.saveAndConnect}
                </Button>
              ) : null}
            </DialogFooter>
          )}
        </form>
      </DialogContent>
    </Dialog>
  );
}
