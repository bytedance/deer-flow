"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import type {
  HumanInputRequest,
  HumanInputResponse,
} from "@/core/messages/human-input";
import { uuid } from "@/core/utils/uuid";

import {
  maySelectModel,
  resolveModelControl,
  type ModelControlDecision,
  type ModelControlScope,
} from "./control";

type Answer = (response: HumanInputResponse | null) => void;

/** A pending choice owns no agent run; navigation/account changes cancel it. */
export function useModelControl(owner: string, locale: string) {
  const [request, setRequest] = useState<HumanInputRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const answer = useRef<Answer | null>(null);
  const generation = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const zh = locale.startsWith("zh");

  useEffect(
    () => () => {
      generation.current += 1;
      abort.current?.abort();
      abort.current = null;
      answer.current?.(null);
      answer.current = null;
      setRequest(null);
      setBusy(false);
    },
    [owner],
  );

  const choose = useCallback((response: HumanInputResponse | null) => {
    answer.current?.(response);
    answer.current = null;
    setRequest(null);
  }, []);

  const prepare = useCallback(
    async (text: string): Promise<ModelControlDecision | null> => {
      if (!maySelectModel(text)) return null;
      if (abort.current)
        throw new Error("A model selection is already pending.");
      const epoch = generation.current;
      const controller = new AbortController();
      abort.current = controller;
      setBusy(true);
      const selection: { model_name?: string; scope?: ModelControlScope } = {};
      try {
        for (let attempt = 0; attempt < 4; attempt++) {
          const result = await resolveModelControl(
            text,
            selection,
            controller.signal,
          );
          if (epoch !== generation.current)
            throw new Error("model-selection-cancelled");
          if (result.status === "none") return null;
          if (result.status === "resolved") return result;
          const needsScope = result.scope === null;
          const choices = needsScope
            ? [
                {
                  name: "task",
                  label: zh ? "只交给子任务" : "Delegate this task",
                },
                {
                  name: "turn",
                  label: zh ? "主任务仅这次" : "Main task, this turn",
                },
                {
                  name: "conversation",
                  label: zh ? "以后这个对话都用" : "Conversation default",
                },
              ]
            : result.candidates;
          const response = await new Promise<HumanInputResponse | null>(
            (resolve) => {
              answer.current = resolve;
              setRequest({
                version: 1,
                kind: "human_input_request",
                source: "model_selection",
                request_id: uuid(),
                title: zh ? "选择这次使用的模型" : "Choose a model",
                question: needsScope
                  ? zh
                    ? "这次选择要用于哪里？"
                    : "Where should this choice apply?"
                  : result.status === "unavailable"
                    ? zh
                      ? `没有可用模型与“${result.query}”对应。请输入已配置的模型名称，或取消。`
                      : `No available model matches “${result.query}”. Enter a configured name, or cancel.`
                    : zh
                      ? `“${result.query}”对应多个配置，你指的是哪一个？`
                      : `Which configured model do you mean by “${result.query}”?`,
                context: needsScope
                  ? undefined
                  : zh
                    ? "只在你选定后执行；不会自动更改其他会话。"
                    : "Execution waits for your choice. Other conversations are unchanged.",
                input_mode: needsScope ? "single_choice" : "choice_with_other",
                options: [
                  ...choices.map((item) => ({
                    id: item.name,
                    value: item.name,
                    label: item.label,
                  })),
                  {
                    id: "cancel",
                    value: "__cancel__",
                    label: zh ? "取消这次操作" : "Cancel this operation",
                  },
                ],
              });
            },
          );
          if (
            !response ||
            response.value === "__cancel__" ||
            epoch !== generation.current
          )
            throw new Error("model-selection-cancelled");
          if (needsScope) selection.scope = response.value as ModelControlScope;
          else selection.model_name = response.value;
        }
        throw new Error(
          zh
            ? "还无法确定模型，请换一个说法。"
            : "The model is still unclear. Please rephrase.",
        );
      } catch (error) {
        if (
          epoch === generation.current &&
          !controller.signal.aborted &&
          !(
            error instanceof Error &&
            error.message === "model-selection-cancelled"
          )
        ) {
          toast.error(
            error instanceof Error
              ? error.message
              : zh
                ? "无法确认模型选择，请稍后再试。"
                : "Unable to check the model selection. Please retry.",
          );
        }
        throw error;
      } finally {
        if (epoch === generation.current) {
          abort.current = null;
          setBusy(false);
          setRequest(null);
        }
      }
    },
    [zh],
  );

  return { request, busy, prepare, choose };
}
