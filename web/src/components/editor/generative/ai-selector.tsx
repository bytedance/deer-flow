// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { Command, CommandInput } from "../../ui/command";

import { ArrowUp } from "lucide-react";
import { useEditor } from "novel";
import { addAIHighlight } from "novel";
import { useCallback, useState } from "react";
import Markdown from "react-markdown";
import { toast } from "sonner";
import { Button } from "../../ui/button";
import Magic from "../../ui/icons/magic";
import { ScrollArea } from "../../ui/scroll-area";
import AICompletionCommands from "./ai-completion-command";
import AISelectorCommands from "./ai-selector-commands";
import { LoadingOutlined } from "@ant-design/icons";
import { resolveServiceURL } from "~/core/api/resolve-service-url";
import { fetchStream } from "~/core/sse";
//TODO: I think it makes more sense to create a custom Tiptap extension for this functionality https://tiptap.dev/docs/editor/ai/introduction

interface AISelectorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function useProseCompletion() {
  const [completion, setCompletion] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const complete = useCallback(
    async (prompt: string, options?: { body?: Record<string, any> }) => {
      setIsLoading(true);
      setError(null);

      try {
        const response = await fetchStream(
          resolveServiceURL("/api/prose/generate"),
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              prompt,
              ...options?.body,
            }),
          },
        );

        let fullText = "";

        // Process the streaming response with debounced updates
        let chunkBuffer = "";
        let updateTimer: NodeJS.Timeout | undefined;

        const scheduleUpdate = () => {
          if (updateTimer) clearTimeout(updateTimer);
          updateTimer = setTimeout(() => {
            if (chunkBuffer) {
              fullText += chunkBuffer;
              setCompletion(fullText);
              chunkBuffer = "";
            }
          }, 16); // ~60fps
        };

        for await (const chunk of response) {
          fullText += chunk.data;
          chunkBuffer += chunk.data;
          scheduleUpdate();
        }

        // Final update
        if (chunkBuffer) {
          fullText += chunkBuffer;
          setCompletion(fullText);
        }

        setIsLoading(false);
        return fullText;
      } catch (e) {
        const error = e instanceof Error ? e : new Error("An error occurred");
        setError(error);
        toast.error(error.message);
        setIsLoading(false);
        throw error;
      }
    },
    [],
  );

  const reset = useCallback(() => {
    setCompletion("");
    setError(null);
    setIsLoading(false);
  }, []);

  return {
    completion,
    complete,
    isLoading,
    error,
    reset,
  };
}

export function AISelector({ onOpenChange }: AISelectorProps) {
  const { editor } = useEditor();
  const [inputValue, setInputValue] = useState("");

  const { completion, complete, isLoading } = useProseCompletion();

  if (!editor) return null;

  const hasCompletion = completion.length > 0;

  return (
    <Command className="w-[350px]">
      {hasCompletion && (
        <div className="flex max-h-[400px]">
          <ScrollArea>
            <div className="prose prose-sm dark:prose-invert p-2 px-4">
              <Markdown>{completion}</Markdown>
            </div>
          </ScrollArea>
        </div>
      )}

      {isLoading && (
        <div className="flex h-12 w-full items-center px-4 text-sm font-medium text-purple-500">
          <Magic className="mr-2 h-4 w-4 shrink-0" />
          AI is thinking
          <div className="mt-1 ml-2">
            <LoadingOutlined />
          </div>
        </div>
      )}
      {!isLoading && (
        <>
          <div className="relative">
            <CommandInput
              value={inputValue}
              onValueChange={setInputValue}
              autoFocus
              placeholder={
                hasCompletion
                  ? "Tell AI what to do next"
                  : "Ask AI to edit or generate..."
              }
              onFocus={() => addAIHighlight(editor)}
            />
            <Button
              size="icon"
              className="absolute top-1/2 right-2 h-6 w-6 -translate-y-1/2 rounded-full bg-purple-500 hover:bg-purple-900"
              onClick={() => {
                if (completion)
                  return complete(completion, {
                    body: { option: "zap", command: inputValue },
                  }).then(() => setInputValue(""));

                const slice = editor.state.selection.content();
                const text = editor.storage.markdown.serializer.serialize(
                  slice.content,
                );

                complete(text, {
                  body: { option: "zap", command: inputValue },
                }).then(() => setInputValue(""));
              }}
            >
              <ArrowUp className="h-4 w-4" />
            </Button>
          </div>
          {hasCompletion ? (
            <AICompletionCommands
              onDiscard={() => {
                editor.chain().unsetHighlight().focus().run();
                onOpenChange(false);
              }}
              completion={completion}
            />
          ) : (
            <AISelectorCommands
              onSelect={(value, option) =>
                complete(value, { body: { option } })
              }
            />
          )}
        </>
      )}
    </Command>
  );
}
