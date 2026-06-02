"use client";

import { useSearchParams } from "next/navigation";
import { useMemo, useRef } from "react";

const RESERVED_PARAMS = new Set(["prompt", "auto_send", "source", "context"]);

const MAX_PROMPT_LEN = 2000;
const MAX_SOURCE_LEN = 100;
const MAX_CONTEXT_LEN = 500;
const MAX_PASSTHROUGH_LEN = 500;

/** Strip control characters except space, tab, newline, carriage return */
function stripControlChars(s: string): string {
  return s.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, "");
}

function validatePrompt(raw: string | null): string | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  return stripControlChars(trimmed).slice(0, MAX_PROMPT_LEN);
}

function validateAutoSend(raw: string | null): boolean {
  return raw === "1";
}

function validateSource(raw: string | null): string | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  return stripControlChars(trimmed).slice(0, MAX_SOURCE_LEN);
}

function validateContext(raw: string | null): string | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  return stripControlChars(trimmed).slice(0, MAX_CONTEXT_LEN);
}

function validatePassthroughValue(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  return stripControlChars(trimmed).slice(0, MAX_PASSTHROUGH_LEN);
}

export interface DeepLinkParams {
  prompt: string | null;
  autoSend: boolean;
  source: string | null;
  context: string | null;
  passthroughParams: Record<string, string>;
}

/**
 * Parse deep-link URL parameters and return structured data.
 * Only activates for new threads (isNewThread === true).
 * Uses a useRef sentinel to fire exactly once per mount.
 */
export function useDeepLinkChat(isNewThread: boolean): DeepLinkParams {
  const searchParams = useSearchParams();
  const firedRef = useRef(false);

  const result = useMemo<DeepLinkParams>(() => {
    if (!isNewThread || firedRef.current) {
      return { prompt: null, autoSend: false, source: null, context: null, passthroughParams: {} };
    }
    firedRef.current = true;

    const prompt = validatePrompt(searchParams.get("prompt"));
    const autoSend = validateAutoSend(searchParams.get("auto_send"));
    const source = validateSource(searchParams.get("source"));
    const context = validateContext(searchParams.get("context"));

    const passthroughParams: Record<string, string> = {};
    searchParams.forEach((value, key) => {
      if (RESERVED_PARAMS.has(key)) return;
      const validated = validatePassthroughValue(value);
      if (validated !== null) {
        passthroughParams[key] = validated;
      }
    });

    return { prompt, autoSend, source, context, passthroughParams };
  }, [isNewThread, searchParams]);

  return result;
}

export const __test_only = {
  stripControlChars,
  validatePrompt,
  validateAutoSend,
  validateSource,
  validateContext,
  validatePassthroughValue,
  RESERVED_PARAMS,
  MAX_PROMPT_LEN,
  MAX_SOURCE_LEN,
  MAX_CONTEXT_LEN,
  MAX_PASSTHROUGH_LEN,
};
