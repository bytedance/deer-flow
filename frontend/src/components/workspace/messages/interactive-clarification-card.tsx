import { CheckCircle2Icon, CircleIcon } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

export interface ClarificationQuestion {
  id: string;
  header?: string;
  question: string;
  type: "single_select" | "text";
  options?: string[];
  required?: boolean;
  placeholder?: string;
  recommended_option?: string;
  allow_free_text?: boolean;
}

export interface ClarificationPayload {
  kind: "clarification";
  mode: "single" | "form";
  title?: string;
  description?: string;
  question?: string;
  clarification_type?: string;
  context?: string;
  options?: string[];
  recommended_option?: string;
  allow_free_text?: boolean;
  interaction_mode?: "free_text" | "single_select";
  submit_label?: string;
  questions?: ClarificationQuestion[];
}

export interface ClarificationResponse {
  kind: "clarification";
  mode: "single" | "form";
  title?: string;
  answers: {
    id?: string;
    question: string;
    answer: string | string[];
  }[];
}

interface Props {
  payload: ClarificationPayload;
  onSubmit: (response: ClarificationResponse) => void;
  disabled?: boolean;
}

export function InteractiveClarificationCard({ payload, onSubmit, disabled }: Props) {
  if (payload.mode === "form") {
    return (
      <ClarificationForm
        payload={payload}
        onSubmit={onSubmit}
        disabled={disabled}
      />
    );
  }

  return (
    <ClarificationSingle
      payload={payload}
      onSubmit={onSubmit}
      disabled={disabled}
    />
  );
}

function ClarificationSingle({ payload, onSubmit, disabled }: Props) {
  const [selectedValue, setSelectedValue] = useState<string>(
    payload.recommended_option ?? "",
  );
  const [freeText, setFreeText] = useState<string>("");
  const isDisabled = disabled ?? false;

  const isSelectMode = useMemo(() => {
    if (payload.interaction_mode === "single_select") {
      return true;
    }
    return (payload.options?.length ?? 0) > 0;
  }, [payload.interaction_mode, payload.options]);

  const handleSubmit = useCallback(() => {
    let finalAnswer = "";
    if (isSelectMode) {
      if (selectedValue === "other" && payload.allow_free_text) {
        finalAnswer = freeText;
      } else {
        finalAnswer = selectedValue;
      }
    } else {
      finalAnswer = freeText;
    }

    if (!finalAnswer.trim()) {
      return;
    }

    onSubmit({
      kind: "clarification",
      mode: "single",
      title: payload.title,
      answers: [
        {
          question: payload.question ?? "",
          answer: finalAnswer,
        },
      ],
    });
  }, [freeText, isSelectMode, onSubmit, payload.allow_free_text, payload.question, payload.title, selectedValue]);

  const submitDisabled =
    (disabled ?? false) ||
    (!isSelectMode && !freeText.trim()) ||
    (isSelectMode &&
      (!selectedValue ||
        (selectedValue === "other" && !freeText.trim())));

  return (
    <div className="bg-card text-card-foreground flex flex-col gap-4 rounded-xl border p-6 shadow-sm">
      <div className="flex flex-col gap-2">
        {payload.title && (
          <h3 className="text-lg font-semibold">{payload.title}</h3>
        )}
        {payload.context && (
          <p className="text-muted-foreground text-sm whitespace-pre-wrap">{payload.context}</p>
        )}
        <p className="font-medium whitespace-pre-wrap">{payload.question}</p>
      </div>

      <div className="flex flex-col gap-4">
        {isSelectMode ? (
          <div className="flex flex-col gap-3">
            {payload.options?.map((option) => {
              const isSelected = selectedValue === option;
              return (
                <button
                  key={option}
                  type="button"
                  disabled={isDisabled}
                  className={cn(
                    "flex items-center space-x-3 rounded-md border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                    isSelected
                      ? "border-primary bg-primary/5"
                      : "hover:bg-accent",
                    isDisabled && "cursor-not-allowed opacity-60",
                  )}
                  aria-pressed={isSelected}
                  onClick={() => {
                    if (isDisabled) return;
                    setSelectedValue(option);
                  }}
                  onKeyDown={(event) => {
                    if (isDisabled) return;
                    if (event.key === " " || event.key === "Enter") {
                      event.preventDefault();
                      setSelectedValue(option);
                    }
                  }}
                >
                  {isSelected ? (
                    <CheckCircle2Icon className="text-primary size-5" />
                  ) : (
                    <CircleIcon className="text-muted-foreground size-5" />
                  )}
                  <div className="flex-1 text-sm font-medium">
                    {option}
                    {option === payload.recommended_option && (
                      <span className="text-muted-foreground ml-2 text-xs font-normal">
                        (Recommended)
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
            {payload.allow_free_text && (
              <div className="flex flex-col gap-2">
                <button
                  type="button"
                  disabled={isDisabled}
                  className={cn(
                    "flex items-center space-x-3 rounded-md border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                    selectedValue === "other"
                      ? "border-primary bg-primary/5"
                      : "hover:bg-accent",
                    isDisabled && "cursor-not-allowed opacity-60",
                  )}
                  aria-pressed={selectedValue === "other"}
                  onClick={() => {
                    if (isDisabled) return;
                    setSelectedValue("other");
                  }}
                  onKeyDown={(event) => {
                    if (isDisabled) return;
                    if (event.key === " " || event.key === "Enter") {
                      event.preventDefault();
                      setSelectedValue("other");
                    }
                  }}
                >
                  {selectedValue === "other" ? (
                    <CheckCircle2Icon className="text-primary size-5" />
                  ) : (
                    <CircleIcon className="text-muted-foreground size-5" />
                  )}
                  <div className="flex-1 text-sm font-medium">Other</div>
                </button>
                {selectedValue === "other" && (
                  <Input
                    disabled={isDisabled}
                    placeholder="Please specify..."
                    value={freeText}
                    onChange={(event) => setFreeText(event.target.value)}
                    className="ml-8 w-auto"
                    autoFocus
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        handleSubmit();
                      }
                    }}
                  />
                )}
              </div>
            )}
          </div>
        ) : (
          <Textarea
            disabled={isDisabled}
            placeholder="Type your answer here..."
            value={freeText}
            onChange={(event) => setFreeText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                handleSubmit();
              }
            }}
          />
        )}
      </div>

      <div className="flex justify-end pt-2">
        <Button disabled={submitDisabled} onClick={handleSubmit}>
          Submit
        </Button>
      </div>
    </div>
  );
}

function ClarificationForm({ payload, onSubmit, disabled }: Props) {
  const [answers, setAnswers] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    payload.questions?.forEach((question) => {
      if (question.recommended_option) {
        initial[question.id] = question.recommended_option;
      }
    });
    return initial;
  });
  const isDisabled = disabled ?? false;

  const handleSubmit = useCallback(() => {
    if (!payload.questions) {
      return;
    }

    for (const question of payload.questions) {
      if (question.required && !answers[question.id]?.trim()) {
        return;
      }
    }

    onSubmit({
      kind: "clarification",
      mode: "form",
      title: payload.title,
      answers: payload.questions.map((question) => ({
        id: question.id,
        question: question.question,
        answer: answers[question.id] ?? "",
      })),
    });
  }, [answers, onSubmit, payload.questions, payload.title]);

  const isValid = useMemo(() => {
    if (!payload.questions) {
      return true;
    }
    return payload.questions.every((question) => {
      if (!question.required) {
        return true;
      }
      return Boolean(answers[question.id]?.trim());
    });
  }, [answers, payload.questions]);

  const submitDisabled = (disabled ?? false) || !isValid;

  return (
    <div className="bg-card text-card-foreground flex flex-col gap-6 rounded-xl border p-6 shadow-sm">
      <div className="flex flex-col gap-2">
        {payload.title && (
          <h3 className="text-lg font-semibold">{payload.title}</h3>
        )}
        {payload.description && (
          <p className="text-muted-foreground text-sm whitespace-pre-wrap">
            {payload.description}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-8">
        {payload.questions?.map((question, index) => {
          return (
            <div key={question.id} className="flex flex-col gap-3">
              <div className="flex flex-col gap-1">
                {question.header && (
                  <span className="text-muted-foreground text-xs font-semibold uppercase">
                    {question.header}
                  </span>
                )}
                <label className="text-base font-medium">
                  {index + 1}. {question.question}
                  {question.required && (
                    <span className="text-destructive ml-1">*</span>
                  )}
                </label>
              </div>

              {question.type === "single_select" ? (
                <div className="flex flex-col gap-3">
                  {question.options?.map((option) => {
                    const isSelected = answers[question.id] === option;
                    return (
                      <button
                        key={option}
                        type="button"
                        disabled={isDisabled}
                        className={cn(
                          "flex items-center space-x-3 rounded-md border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                          isSelected
                            ? "border-primary bg-primary/5"
                            : "hover:bg-accent",
                          isDisabled && "cursor-not-allowed opacity-60",
                        )}
                        aria-pressed={isSelected}
                        onClick={() => {
                          if (isDisabled) return;
                          setAnswers((prev) => ({ ...prev, [question.id]: option }));
                        }}
                        onKeyDown={(event) => {
                          if (isDisabled) return;
                          if (event.key === " " || event.key === "Enter") {
                            event.preventDefault();
                            setAnswers((prev) => ({ ...prev, [question.id]: option }));
                          }
                        }}
                      >
                        {isSelected ? (
                          <CheckCircle2Icon className="text-primary size-5" />
                        ) : (
                          <CircleIcon className="text-muted-foreground size-5" />
                        )}
                        <div className="flex-1 text-sm font-medium">
                          {option}
                          {option === question.recommended_option && (
                            <span className="text-muted-foreground ml-2 text-xs font-normal">
                              (Recommended)
                            </span>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              ) : (
                <Textarea
                  disabled={isDisabled}
                  placeholder={question.placeholder ?? "Type your answer..."}
                  value={answers[question.id] ?? ""}
                  onChange={(event) =>
                    setAnswers((prev) => ({ ...prev, [question.id]: event.target.value }))
                  }
                  className="min-h-[80px]"
                />
              )}
            </div>
          );
        })}
      </div>

      <div className="flex justify-end border-t pt-4">
        <Button disabled={submitDisabled} onClick={handleSubmit}>
          {payload.submit_label ?? "Submit Answers"}
        </Button>
      </div>
    </div>
  );
}
