"use client";

import { LoaderCircleIcon } from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";

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
import type {
  ChannelProvider,
  ChannelRuntimeConfigValues,
} from "@/core/channels/types";
import { useI18n } from "@/core/i18n/hooks";

type ChannelRuntimeConfigDialogProps = {
  provider: ChannelProvider | null;
  open: boolean;
  submitting: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (
    provider: ChannelProvider,
    values: ChannelRuntimeConfigValues,
  ) => void;
};

export function ChannelRuntimeConfigDialog({
  provider,
  open,
  submitting,
  onOpenChange,
  onSubmit,
}: ChannelRuntimeConfigDialogProps) {
  const { t } = useI18n();
  const [values, setValues] = useState<ChannelRuntimeConfigValues>({});
  const fields = useMemo(
    () => provider?.credential_fields ?? [],
    [provider?.credential_fields],
  );

  useEffect(() => {
    if (!open || !provider) {
      setValues({});
      return;
    }
    setValues(
      Object.fromEntries(fields.map((field) => [field.name, ""])) as
        | ChannelRuntimeConfigValues
        | {},
    );
  }, [fields, open, provider]);

  if (!provider) {
    return null;
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit(provider, values);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>
              {t.channels.setupTitle(provider.display_name)}
            </DialogTitle>
            <DialogDescription>{t.channels.setupDescription}</DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            {fields.map((field) => {
              const inputId = `channel-${provider.provider}-${field.name}`;
              return (
                <div key={field.name} className="space-y-1.5">
                  <label
                    htmlFor={inputId}
                    className="text-sm leading-none font-medium"
                  >
                    {field.label}
                  </label>
                  <Input
                    id={inputId}
                    type={field.type === "password" ? "password" : "text"}
                    value={values[field.name] ?? ""}
                    required={field.required}
                    autoComplete="off"
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

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={submitting}
              onClick={() => onOpenChange(false)}
            >
              {t.common.cancel}
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : null}
              {t.channels.saveAndConnect}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
