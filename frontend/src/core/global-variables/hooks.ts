import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { useI18n } from "@/core/i18n/hooks";

import {
  deleteProjectVariable,
  deleteThreadVariable,
  fetchProjectVariables,
  fetchThreadVariables,
  setProjectVariable,
  setThreadVariable,
} from "./api";
import type { GlobalVariable, VariableFormData, VariableScope } from "./types";

export function useGlobalVariables(scope: VariableScope, threadId?: string) {
  const { t } = useI18n();
  const [variables, setVariables] = useState<GlobalVariable[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();

    try {
      setIsLoading(true);
      setError(null);
      let result;
      if (scope === "project") {
        result = await fetchProjectVariables();
      } else {
        if (!threadId) {
          setVariables([]);
          setIsLoading(false);
          return;
        }
        result = await fetchThreadVariables(threadId);
      }
      if (!abortRef.current?.signal.aborted) {
        setVariables(result.variables);
      }
    } catch (err) {
      if (!abortRef.current?.signal.aborted) {
        setError(err instanceof Error ? err : new Error(String(err)));
        toast.error(err instanceof Error ? err.message : String(err));
      }
    } finally {
      if (!abortRef.current?.signal.aborted) {
        setIsLoading(false);
      }
    }
  }, [scope, threadId]);

  const addVariable = useCallback(
    async (data: VariableFormData) => {
      try {
        const request = {
          value: data.value,
          description: data.description,
          llm_editable: data.llm_editable,
          is_system: false,
        };
        if (scope === "project") {
          const result = await setProjectVariable(data.key, request);
          setVariables(result.variables);
        } else if (threadId) {
          const result = await setThreadVariable(threadId, data.key, request);
          setVariables(result.variables);
        }
        toast.success(t.globalVariables.addSuccess);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : String(err));
      }
    },
    [scope, threadId, t.globalVariables],
  );

  const updateVariable = useCallback(
    async (oldKey: string, data: VariableFormData) => {
      try {
        const request = {
          value: data.value,
          description: data.description,
          llm_editable: data.llm_editable,
          is_system: false,
        };
        if (scope === "project") {
          const result = await setProjectVariable(data.key, request);
          setVariables(result.variables);
        } else if (threadId) {
          const result = await setThreadVariable(threadId, data.key, request);
          setVariables(result.variables);
        }
        if (oldKey !== data.key) {
          if (scope === "project") {
            await deleteProjectVariable(oldKey);
          } else if (threadId) {
            await deleteThreadVariable(threadId, oldKey);
          }
          load();
        }
        toast.success(t.globalVariables.updateSuccess);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : String(err));
      }
    },
    [scope, threadId, t.globalVariables, load],
  );

  const deleteVariable = useCallback(
    async (key: string) => {
      try {
        if (scope === "project") {
          const result = await deleteProjectVariable(key);
          setVariables(result.variables);
        } else if (threadId) {
          const result = await deleteThreadVariable(threadId, key);
          setVariables(result.variables);
        }
        toast.success(t.globalVariables.deleteSuccess);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : String(err));
      }
    },
    [scope, threadId, t.globalVariables],
  );

  useEffect(() => {
    load();
    return () => {
      abortRef.current?.abort();
    };
  }, [load]);

  return {
    variables,
    isLoading,
    error,
    addVariable,
    updateVariable,
    deleteVariable,
    reload: load,
  };
}
