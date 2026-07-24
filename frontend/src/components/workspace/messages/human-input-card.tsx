"use client";

import {
  CheckCircle2Icon,
  Loader2Icon,
  MessageCircleQuestionMarkIcon,
} from "lucide-react";
import { useId, useState, type KeyboardEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import {
  createHumanInputOptionResponse,
  createHumanInputTextResponse,
  type HumanInputOption,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/core/messages/human-input";
import { isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";

import { MarkdownContent } from "./markdown-content";

export type HumanInputSubmitResult = boolean | void;

export function shouldSubmitHumanInputTextOnKeyDown(
  event: KeyboardEvent<HTMLTextAreaElement>,
  isComposing = false,
) {
  return (
    event.key === "Enter" &&
    !event.shiftKey &&
    !isIMEComposing(event, isComposing)
  );
}

export function HumanInputCard({
  request,
  disabled = false,
  pending = false,
  answeredResponse = null,
  onSubmit,
}: {
  request: HumanInputRequest;
  disabled?: boolean;
  pending?: boolean;
  answeredResponse?: HumanInputResponse | null;
  onSubmit?: (
    response: HumanInputResponse,
  ) => HumanInputSubmitResult | Promise<HumanInputSubmitResult>;
}) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [isComposing, setIsComposing] = useState(false);
  const titleId = useId();
  const textInputId = useId();
  const allowText =
    request.input_mode === "free_text" ||
    request.input_mode === "choice_with_other";
  const options = request.options ?? [];
  const readOnly = !onSubmit;
  const isDisabled =
    disabled || pending || Boolean(answeredResponse) || readOnly;
  const statusLabel = answeredResponse
    ? t.humanInput.answered
    : pending
      ? t.humanInput.pending
      : readOnly
        ? t.humanInput.readOnly
        : null;

  const submitResponse = async (response: HumanInputResponse) => {
    if (isDisabled || !onSubmit) {
      return;
    }
    setError("");
    const result = await onSubmit(response);
    if (result !== false && response.response_kind === "text") {
      setText("");
    }
  };

  const handleOptionClick = (option: HumanInputOption) => {
    void submitResponse(createHumanInputOptionResponse(request, option));
  };

  const handleTextSubmit = (event: { preventDefault(): void }) => {
    event.preventDefault();
    const value = text.trim();
    if (!value) {
      setError(t.humanInput.emptyError);
      return;
    }
    void submitResponse(createHumanInputTextResponse(request, value));
  };

  const handleTextKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (shouldSubmitHumanInputTextOnKeyDown(event, isComposing)) {
      event.preventDefault();
      const value = text.trim();
      if (!value) {
        setError(t.humanInput.emptyError);
        return;
      }
      void submitResponse(createHumanInputTextResponse(request, value));
    }
  };

  return (
    <section
      aria-labelledby={titleId}
      className="border-border bg-card/70 text-card-foreground rounded-lg border p-4 shadow-xs"
      data-testid="human-input-card"
    >
      <div className="flex items-start gap-3">
        <div className="bg-primary/10 text-primary mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md">
          <MessageCircleQuestionMarkIcon className="size-4" />
        </div>
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0 space-y-1">
              <h2 id={titleId} className="text-sm leading-5 font-medium">
                {request.title ?? t.toolCalls.needYourHelp}
              </h2>
              {request.context ? (
                <div className="text-muted-foreground text-sm leading-6">
                  <MarkdownContent
                    content={request.context}
                    isLoading={false}
                  />
                </div>
              ) : null}
            </div>
            {statusLabel ? (
              <Badge
                className={cn(
                  "h-6 rounded-md px-2",
                  pending && "gap-1.5",
                  answeredResponse &&
                    "border-primary/20 bg-primary/10 text-primary",
                )}
                variant={answeredResponse ? "outline" : "secondary"}
              >
                {pending ? (
                  <Loader2Icon className="size-3 animate-spin" />
                ) : null}
                {answeredResponse ? (
                  <CheckCircle2Icon className="size-3" />
                ) : null}
                {statusLabel}
              </Badge>
            ) : null}
          </div>

          <div className="text-foreground text-sm leading-6">
            <MarkdownContent content={request.question} isLoading={false} />
          </div>

          {options.length > 0 ? (
            <div className="grid gap-2">
              {options.map((option) => (
                <Button
                  key={option.id}
                  className="min-h-11 w-full justify-start rounded-md px-3 py-2 text-left leading-5 whitespace-normal"
                  disabled={isDisabled}
                  type="button"
                  variant="outline"
                  onClick={() => handleOptionClick(option)}
                >
                  <span className="min-w-0 wrap-break-word whitespace-pre-wrap">
                    {option.label}
                  </span>
                </Button>
              ))}
            </div>
          ) : null}

          {allowText ? (
            <form className="space-y-2" onSubmit={handleTextSubmit}>
              <label className="sr-only" htmlFor={textInputId}>
                {t.humanInput.otherLabel}
              </label>
              <Textarea
                id={textInputId}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? `${textInputId}-error` : undefined}
                className="min-h-20 resize-y text-sm"
                disabled={isDisabled}
                placeholder={t.humanInput.otherPlaceholder}
                value={text}
                onChange={(event) => {
                  setText(event.target.value);
                  if (error) {
                    setError("");
                  }
                }}
                onCompositionEnd={() => setIsComposing(false)}
                onCompositionStart={() => setIsComposing(true)}
                onKeyDown={handleTextKeyDown}
              />
              <div className="flex min-h-9 flex-wrap items-center justify-between gap-2">
                {error ? (
                  <p
                    className="text-destructive text-sm"
                    id={`${textInputId}-error`}
                  >
                    {error}
                  </p>
                ) : answeredResponse ? (
                  <p
                    className="text-muted-foreground text-sm"
                    aria-live="polite"
                  >
                    {t.humanInput.answeredValue(answeredResponse.value)}
                  </p>
                ) : (
                  <span />
                )}
                <Button
                  className="min-w-24"
                  disabled={isDisabled}
                  type="submit"
                  variant="secondary"
                >
                  {pending ? (
                    <Loader2Icon className="size-4 animate-spin" />
                  ) : null}
                  {t.humanInput.submit}
                </Button>
              </div>
            </form>
          ) : answeredResponse ? (
            <p className="text-muted-foreground text-sm" aria-live="polite">
              {t.humanInput.answeredValue(answeredResponse.value)}
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}
