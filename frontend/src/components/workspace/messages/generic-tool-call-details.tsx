"use client";

import { ChevronDownIcon } from "lucide-react";
import { useMemo, useState } from "react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { CopyButton } from "../copy-button";

export const TOOL_CALL_PAYLOAD_LIMIT = 4_000;

const MAX_COLLECTION_ITEMS = 100;
const MAX_NESTING_DEPTH = 12;

export interface FormattedToolCallPayload {
  text: string;
  truncated: boolean;
}

class BoundedPayloadWriter {
  readonly parts: string[] = [];
  remaining: number;
  truncated = false;
  exhausted = false;

  constructor(limit: number) {
    this.remaining = Math.max(0, limit);
  }

  write(value: string): boolean {
    if (this.exhausted) {
      return false;
    }
    if (value.length > this.remaining) {
      this.truncated = true;
      this.exhausted = true;
      return false;
    }

    this.parts.push(value);
    this.remaining -= value.length;
    return true;
  }

  close(value: string) {
    if (value.length <= this.remaining) {
      this.parts.push(value);
      this.remaining -= value.length;
    }
  }

  markTruncated() {
    this.truncated = true;
  }

  stop() {
    this.truncated = true;
    this.exhausted = true;
  }
}

/**
 * Formats diagnostic payloads without first serializing the complete value.
 * Traversal stops once the character, collection, or depth budget is reached.
 */
export function formatToolCallPayload(
  value: unknown,
  limit = TOOL_CALL_PAYLOAD_LIMIT,
): FormattedToolCallPayload {
  const writer = new BoundedPayloadWriter(limit);
  writePayloadValue(value, writer, 0, new WeakSet<object>());
  return {
    text: writer.parts.join(""),
    truncated: writer.truncated,
  };
}

function writePayloadValue(
  value: unknown,
  writer: BoundedPayloadWriter,
  depth: number,
  ancestors: WeakSet<object>,
) {
  if (writer.exhausted) {
    return;
  }
  if (value === null) {
    writer.write("null");
    return;
  }
  if (typeof value === "string") {
    writeString(value, writer);
    return;
  }
  if (typeof value === "number") {
    writer.write(Number.isFinite(value) ? String(value) : "null");
    return;
  }
  if (typeof value === "boolean") {
    writer.write(String(value));
    return;
  }
  if (typeof value === "undefined") {
    writer.write("undefined");
    return;
  }
  if (typeof value === "bigint") {
    writeString(`${value}n`, writer);
    return;
  }
  if (typeof value === "symbol" || typeof value === "function") {
    writeString(String(value), writer);
    return;
  }

  if (ancestors.has(value)) {
    writeString("[Circular]", writer);
    return;
  }
  if (depth >= MAX_NESTING_DEPTH) {
    writer.markTruncated();
    writeString("[Max depth reached]", writer);
    return;
  }

  ancestors.add(value);
  if (Array.isArray(value)) {
    writeArray(value, writer, depth, ancestors);
  } else {
    writeObject(value, writer, depth, ancestors);
  }
  ancestors.delete(value);
}

function writeArray(
  value: unknown[],
  writer: BoundedPayloadWriter,
  depth: number,
  ancestors: WeakSet<object>,
) {
  if (!writer.write("[")) {
    return;
  }

  const count = Math.min(value.length, MAX_COLLECTION_ITEMS);
  for (let index = 0; index < count && !writer.exhausted; index += 1) {
    if (!writer.write(`${index === 0 ? "" : ","}\n${indent(depth + 1)}`)) {
      break;
    }
    writePayloadValue(value[index], writer, depth + 1, ancestors);
  }
  if (value.length > count) {
    writer.markTruncated();
  }
  if (count > 0) {
    writer.write(`\n${indent(depth)}`);
  }
  writer.close("]");
}

function writeObject(
  value: object,
  writer: BoundedPayloadWriter,
  depth: number,
  ancestors: WeakSet<object>,
) {
  if (!writer.write("{")) {
    return;
  }

  let index = 0;
  let hasMoreItems = false;
  for (const key in value) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) {
      continue;
    }
    if (index >= MAX_COLLECTION_ITEMS) {
      hasMoreItems = true;
      break;
    }
    if (!writer.write(`${index === 0 ? "" : ","}\n${indent(depth + 1)}`)) {
      break;
    }
    writeString(key, writer);
    if (!writer.write(": ")) {
      break;
    }
    writePayloadValue(Reflect.get(value, key), writer, depth + 1, ancestors);
    index += 1;
  }
  if (hasMoreItems) {
    writer.markTruncated();
  }
  if (index > 0) {
    writer.write(`\n${indent(depth)}`);
  }
  writer.close("}");
}

function writeString(value: string, writer: BoundedPayloadWriter) {
  if (!writer.write('"')) {
    return;
  }
  for (const character of value) {
    const encoded = JSON.stringify(character).slice(1, -1);
    if (encoded.length + 1 > writer.remaining) {
      writer.stop();
      break;
    }
    writer.write(encoded);
  }
  writer.close('"');
}

function indent(depth: number): string {
  return "  ".repeat(depth);
}

export function GenericToolCallDetails({
  toolName,
  toolCallId,
  args,
  result,
  isError = false,
}: {
  toolName: string;
  toolCallId?: string;
  args: Record<string, unknown>;
  result?: unknown;
  isError?: boolean;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-xs transition-colors">
        {t.toolCalls.details}
        <ChevronDownIcon
          className={cn("size-3.5 transition-transform", open && "rotate-180")}
        />
      </CollapsibleTrigger>
      {open && (
        <CollapsibleContent className="border-border/70 bg-muted/20 mt-2 space-y-3 rounded-md border p-3">
          <dl className="grid gap-2 text-xs sm:grid-cols-2">
            <ToolMetadata label={t.toolCalls.toolName} value={toolName} />
            <ToolMetadata
              label={t.toolCalls.toolCallId}
              value={toolCallId ?? "-"}
            />
          </dl>
          <ToolPayload
            label={t.toolCalls.input}
            value={args}
            truncationLabel={t.toolCalls.payloadTruncated(
              TOOL_CALL_PAYLOAD_LIMIT,
            )}
          />
          {result !== undefined && (
            <ToolPayload
              label={isError ? t.toolCalls.error : t.toolCalls.result}
              value={result}
              truncationLabel={t.toolCalls.payloadTruncated(
                TOOL_CALL_PAYLOAD_LIMIT,
              )}
            />
          )}
        </CollapsibleContent>
      )}
    </Collapsible>
  );
}

function ToolMetadata({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-foreground truncate font-mono">{value}</dd>
    </div>
  );
}

function ToolPayload({
  label,
  value,
  truncationLabel,
}: {
  label: string;
  value: unknown;
  truncationLabel: string;
}) {
  const { t } = useI18n();
  const payload = useMemo(() => formatToolCallPayload(value), [value]);
  const clipboardData = payload.truncated
    ? `${payload.text}\n\n${truncationLabel}`
    : payload.text;

  return (
    <section>
      <div className="mb-1 flex items-center justify-between gap-2">
        <h4 className="text-foreground text-xs font-medium">{label}</h4>
        <CopyButton
          aria-label={`${t.clipboard.copyToClipboard}: ${label}`}
          className="size-6"
          clipboardData={clipboardData}
        />
      </div>
      <pre className="border-border/70 bg-background text-foreground max-h-64 overflow-auto rounded border p-2 font-mono text-[11px] leading-4 break-words whitespace-pre-wrap">
        {payload.text}
      </pre>
      {payload.truncated && (
        <p className="text-muted-foreground mt-1 text-[11px]">
          {truncationLabel}
        </p>
      )}
    </section>
  );
}
