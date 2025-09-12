// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useEffect, useRef, useState } from "react";

import { env } from "~/env";

import type { DeerFlowConfig } from "../config";
import type { Conversation } from "../messages";
import { useReplay } from "../replay";

import { fetchReplayTitle } from "./chat";
import { queryConversations } from "./conversations";
import { resolveServiceURL } from "./resolve-service-url";

export function useReplayMetadata() {
  const { isReplay } = useReplay();
  const [title, setTitle] = useState<string | null>(null);
  const isLoading = useRef(false);
  const [error, setError] = useState<boolean>(false);
  useEffect(() => {
    if (!isReplay) {
      return;
    }
    if (title || isLoading.current) {
      return;
    }
    isLoading.current = true;
    fetchReplayTitle()
      .then((title) => {
        setError(false);
        setTitle(title ?? null);
        if (title) {
          document.title = `${title} - DeerFlow`;
        }
      })
      .catch(() => {
        setError(true);
        setTitle("Error: the replay is not available.");
        document.title = "DeerFlow";
      })
      .finally(() => {
        isLoading.current = false;
      });
  }, [isLoading, isReplay, title]);
  return { title, isLoading, hasError: error };
}

export function useConfig(): {
  config: DeerFlowConfig | null;
  loading: boolean;
} {
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<DeerFlowConfig | null>(null);

  useEffect(() => {
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY) {
      setLoading(false);
      return;
    }
    fetch(resolveServiceURL("./config"))
      .then((res) => res.json())
      .then((config) => {
        setConfig(config);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to fetch config", err);
        setConfig(null);
        setLoading(false);
      });
  }, []);

  return { config, loading };
}

export function useConversations(): {
  results: Conversation[] | null;
  loading: boolean;
} {
  const [results, setResults] = useState<Array<Conversation>>([]);
  const [loading, setLoading] = useState(true);
  const hasInitialized = useRef(false);
  const maxRetries = useRef(3);

  useEffect(() => {
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY) {
      setLoading(false);
      return;
    }
    // Prevent multiple calls
    if (hasInitialized.current || maxRetries.current <= 0) {
      return;
    }

    queryConversations()
      .then((data) => {
        setResults(data);
        setLoading(false);
        hasInitialized.current = true;
        maxRetries.current = 0; // Reset retries after successful fetch
      })
      .catch((error) => {
        console.error("Failed to fetch replays", error);
        setLoading(false);
        if (maxRetries.current > 0) {
          maxRetries.current -= 1;
          console.warn(`Retrying... (${3 - maxRetries.current} attempts left)`);
        }
      });

    return () => {
      hasInitialized.current = false;
      maxRetries.current = 3; // Reset retries on unmount
    };
  }, []);

  return { results, loading };
}