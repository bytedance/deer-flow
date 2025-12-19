// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useState } from "react";

import { Button } from "~/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/dialog";
import { Textarea } from "~/components/ui/textarea";
import type { MCPServerMetadata } from "~/core/mcp";
import { MCPConfigSchema } from "~/core/mcp";

export function EditMCPServerDialog({
  server,
  onSave,
  open,
  onOpenChange,
}: {
  server: MCPServerMetadata;
  onSave: (config: string) => Promise<boolean>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("settings.mcp");
  const commonT = useTranslations("common");
  const [config, setConfig] = useState(
    JSON.stringify(
      {
        mcpServers: {
          [server.name]: server.transport === 'stdio'
            ? {
              command: server.command,
              args: server.args,
              env: server.env,
            }
            : {
              transport: server.transport,
              url: server.url,
              headers: server.headers,
            },
        },
      },
      null,
      2
    )
  );
  const [processing, setProcessing] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  const handleChange = useCallback((value: string) => {
    setConfig(value);
    setValidationError(null);

    if (!value.trim()) {
      return;
    }

    try {
      const parsed = JSON.parse(value);
      if (!("mcpServers" in parsed)) {
        setValidationError("Missing `mcpServers` in JSON");
        return;
      }

      const result = MCPConfigSchema.safeParse(parsed);
      if (!result.success) {
        if (result.error.errors[0]) {
          const error = result.error.errors[0];
          if (error.code === "invalid_union") {
            if (error.unionErrors[0]?.errors[0]) {
              setValidationError(error.unionErrors[0].errors[0].message);
              return;
            }
          }
          setValidationError(error.message || t("validationFailed"));
          return;
        }
      }

      const keys = Object.keys(parsed.mcpServers);
      if (keys.length === 0) {
        setValidationError(t("missingServerName"));
      }
    } catch {
      setValidationError(t("invalidJson"));
    }
  }, [t]);

  const handleSave = useCallback(async () => {
    setProcessing(true);
    try {
      const success = await onSave(config);
      if (success) {
        onOpenChange(false);
      }
    } catch (error) {
      console.error('Failed to save server configuration:', error);
    } finally {
      setProcessing(false);
    }
  }, [config, onSave, onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>{t("editServer")}</DialogTitle>
          <DialogDescription>
            {t("editServerDescription")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <Textarea
            className="h-[360px] font-mono text-sm"
            value={config}
            onChange={(e) => handleChange(e.target.value)}
          />
          {validationError && (
            <div className="text-sm text-red-500 mt-2">
              {validationError}
            </div>
          )}
        </div>

        <DialogFooter>
          <div className="flex w-full justify-between items-center">
            <div className="text-sm text-muted-foreground">
              {t("editServerNote")}
            </div>
            <div className="space-x-2">
              <Button
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={processing}
              >
                {commonT("cancel")}
              </Button>
              <Button
                onClick={handleSave}
                disabled={processing || !!validationError}
              >
                {processing && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {commonT("save")}
              </Button>
            </div>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
