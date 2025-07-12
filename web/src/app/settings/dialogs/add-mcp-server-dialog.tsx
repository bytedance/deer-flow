// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useRef, useState } from "react";

import { Button } from "~/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "~/components/ui/dialog";
import { Textarea } from "~/components/ui/textarea";
import { queryMCPServerMetadata } from "~/core/api";
import {
  MCPConfigSchema,
  type MCPServerMetadata,
  type SimpleMCPServerMetadata,
  type SimpleSSEMCPServerMetadata,
  type SimpleStdioMCPServerMetadata,
} from "~/core/mcp";

export function AddMCPServerDialog({
  onAdd,
}: {
  onAdd?: (servers: MCPServerMetadata[]) => void;
}) {
  const t = useTranslations("settings");
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [validationError, setValidationError] = useState<string | null>("");
  const [error, setError] = useState<string | null>(null);
  const [processing, setProcessing] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  const handleChange = useCallback((value: string) => {
    setInput(value);
    if (!value.trim()) {
      setValidationError(null);
      return;
    }
    setValidationError(null);
    try {
      const parsed = JSON.parse(value);
      if (!("mcpServers" in parsed)) {
        setValidationError("Missing `mcpServers` in JSON");
        return;
      }
    } catch {
      setValidationError(t("invalidJson"));
      return;
    }
    const result = MCPConfigSchema.safeParse(JSON.parse(value));
    if (!result.success) {
      if (result.error.errors[0]) {
        const error = result.error.errors[0];
        if (error.code === "invalid_union") {
          if (error.unionErrors[0]?.errors[0]) {
            setValidationError(error.unionErrors[0].errors[0].message);
            return;
          }
        }
      }
      const errorMessage =
        result.error.errors[0]?.message ?? t("validationFailed");
      setValidationError(errorMessage);
      return;
    }

    const keys = Object.keys(result.data.mcpServers);
    if (keys.length === 0) {
      setValidationError(t("missingServerName"));
      return;
    }
  }, [t]);

  const handleAdd = useCallback(async () => {
    abortControllerRef.current = new AbortController();
    const config = MCPConfigSchema.parse(JSON.parse(input));
    setInput(JSON.stringify(config, null, 2));
    const addingServers: SimpleMCPServerMetadata[] = [];
    for (const [key, server] of Object.entries(config.mcpServers)) {
      if ("command" in server) {
        const metadata: SimpleStdioMCPServerMetadata = {
          transport: "stdio",
          name: key,
          command: server.command,
          args: server.args,
          env: server.env,
        };
        addingServers.push(metadata);
      } else if ("url" in server) {
        const metadata: SimpleSSEMCPServerMetadata = {
          transport: "sse",
          name: key,
          url: server.url,
        };
        addingServers.push(metadata);
      }
    }
    setProcessing(true);

    const results: MCPServerMetadata[] = [];
    let processingServer: string | null = null;
    try {
      setError(null);
      for (const server of addingServers) {
        processingServer = server.name;
        const metadata = await queryMCPServerMetadata(server, abortControllerRef.current.signal);
        results.push({ ...metadata, name: server.name, enabled: true });
      }
      if (results.length > 0) {
        onAdd?.(results);
      }
      setInput("");
      setOpen(false);
    } catch (e) {
      console.error(e);
      if (e instanceof Error && e.name === 'AbortError') {
        setError(`Request was cancelled`);
      } else {
        setError(`Failed to add server: ${processingServer}`);
      }
    } finally {
      setProcessing(false);
      abortControllerRef.current = null;
    }
  }, [input, onAdd]);

  const handleAbort = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">{t("addServers")}</Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>{t("addNewMCPServers")}</DialogTitle>
        </DialogHeader>
        <DialogDescription>
          {t("mcpConfigDescription")}
          <br />
          {t("pasteConfigBelow")}
        </DialogDescription>

        <main>
          <Textarea
            className="h-[360px] break-all sm:max-w-[510px]"
            placeholder={
              'Example:\n\n{\n  "mcpServers": {\n    "My Server": {\n      "command": "python",\n      "args": [\n        "-m", "mcp_server"\n      ],\n      "env": {\n        "API_KEY": "YOUR_API_KEY"\n      }\n    }\n  }\n}'
            }
            value={input}
            onChange={(e) => handleChange(e.target.value)}
          />
        </main>

        <DialogFooter>
          <div className="flex h-10 w-full items-center justify-between gap-2">
            <div className="text-destructive flex-grow overflow-hidden text-sm">
              {validationError ?? error}
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={() => setOpen(false)}>
                {t("cancel", { defaultValue: "Cancel" })}
              </Button>
              <Button
                className="w-24"
                type="submit"
                disabled={!input.trim() || !!validationError || processing}
                onClick={handleAdd}
              >
                {processing && <Loader2 className="animate-spin" />}
                {t("add")}
              </Button>
              {
                processing && (
                  <Button variant="destructive" onClick={handleAbort}>Abort</Button>
                )
              }
            </div>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
