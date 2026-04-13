import { CheckCircle2Icon, CircleIcon } from "lucide-react";
import { useCallback, useState } from "react";

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
  question?: string; // used in single mode
  clarification_type?: string; // used in single mode
  context?: string; // used in single mode
  options?: string[]; // used in single mode
  recommended_option?: string; // used in single mode
  allow_free_text?: boolean; // used in single mode
  interaction_mode?: "free_text" | "single_select"; // used in single mode
  submit_label?: string; // used in form mode
  questions?: ClarificationQuestion[]; // used in form mode
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

export function InteractiveClarificationCard({
  payload,
  onSubmit,
  disabled,
}: Props) {
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

  const isSelectMode =
    payload.interaction_mode === "single_select" ||
    (payload.options && payload.options.length > 0);

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

    if (!finalAnswer.trim()) return;

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
  }, [isSelectMode, selectedValue, freeText, payload, onSubmit]);

  return (
    <div className="bg-card text-card-foreground flex flex-col gap-4 rounded-xl border p-6 shadow-sm">
      <div className="flex flex-col gap-2">
        {payload.title && (
          <h3 className="text-lg font-semibold">{payload.title}</h3>
        )}
        {payload.context && (
          <p className="text-muted-foreground text-sm">{payload.context}</p>
        )}
        <p className="font-medium">{payload.question}</p>
      </div>

      <div className="flex flex-col gap-4">
        {isSelectMode ? (
          <div className="flex flex-col gap-3">
            {payload.options?.map((option) => (
              <div
                key={option}
                className={cn(
                  "flex cursor-pointer items-center space-x-3 rounded-md border p-3 transition-colors",
                  selectedValue === option
                    ? "border-primary bg-primary/5"
                    : "hover:bg-accent",
                  disabled &&
                    "pointer-events-none cursor-not-allowed opacity-50",
                )}
                onClick={() => !disabled && setSelectedValue(option)}
              >
                {selectedValue === option ? (
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
              </div>
            ))}
            {payload.allow_free_text && (
              <div className="flex flex-col gap-2">
                <div
                  className={cn(
                    "flex cursor-pointer items-center space-x-3 rounded-md border p-3 transition-colors",
                    selectedValue === "other"
                      ? "border-primary bg-primary/5"
                      : "hover:bg-accent",
                    disabled &&
                      "pointer-events-none cursor-not-allowed opacity-50",
                  )}
                  onClick={() => !disabled && setSelectedValue("other")}
                >
                  {selectedValue === "other" ? (
                    <CheckCircle2Icon className="text-primary size-5" />
                  ) : (
                    <CircleIcon className="text-muted-foreground size-5" />
                  )}
                  <div className="flex-1 text-sm font-medium">Other</div>
                </div>
                {selectedValue === "other" && (
                  <Input
                    disabled={disabled}
                    placeholder="Please specify..."
                    value={freeText}
                    onChange={(e) => setFreeText(e.target.value)}
                    className="ml-8 w-auto"
                    autoFocus
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
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
            disabled={disabled}
            placeholder="Type your answer here..."
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit();
              }
            }}
          />
        )}
      </div>

      <div className="flex justify-end pt-2">
        <Button
          disabled={
            disabled ??
            (!isSelectMode && !freeText?.trim()) ??
            (isSelectMode &&
              (!selectedValue ||
                (selectedValue === "other" && !freeText?.trim())))
          }
          onClick={handleSubmit}
        >
          Submit
        </Button>
      </div>
    </div>
  );
}

function ClarificationForm({ payload, onSubmit, disabled }: Props) {
  const [answers, setAnswers] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    payload.questions?.forEach((q) => {
      if (q.recommended_option) {
        initial[q.id] = q.recommended_option;
      }
    });
    return initial;
  });

  const handleSubmit = useCallback(() => {
    if (!payload.questions) return;

    // Check required
    for (const q of payload.questions) {
      if (q.required && !answers[q.id]?.trim()) {
        return; // Alternatively, show an error state
      }
    }

    onSubmit({
      kind: "clarification",
      mode: "form",
      title: payload.title,
      answers: payload.questions.map((q) => ({
        id: q.id,
        question: q.question,
        answer: answers[q.id] ?? "",
      })),
    });
  }, [payload, answers, onSubmit]);

  const isValid =
    payload.questions?.every((q) => !q.required || answers[q.id]?.trim()) ??
    true;

  return (
    <div className="bg-card text-card-foreground flex flex-col gap-6 rounded-xl border p-6 shadow-sm">
      <div className="flex flex-col gap-2">
        {payload.title && (
          <h3 className="text-lg font-semibold">{payload.title}</h3>
        )}
        {payload.description && (
          <p className="text-muted-foreground text-sm">{payload.description}</p>
        )}
      </div>

      <div className="flex flex-col gap-8">
        {payload.questions?.map((q, index) => (
          <div key={q.id} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              {q.header && (
                <span className="text-muted-foreground text-xs font-semibold uppercase">
                  {q.header}
                </span>
              )}
              <label className="text-base font-medium">
                {index + 1}. {q.question}
                {q.required && <span className="text-destructive ml-1">*</span>}
              </label>
            </div>

            {q.type === "single_select" ? (
              <div className="flex flex-col gap-3">
                {q.options?.map((option) => (
                  <div
                    key={option}
                    className={cn(
                      "flex cursor-pointer items-center space-x-3 rounded-md border p-3 transition-colors",
                      answers[q.id] === option
                        ? "border-primary bg-primary/5"
                        : "hover:bg-accent",
                      disabled &&
                        "pointer-events-none cursor-not-allowed opacity-50",
                    )}
                    onClick={() =>
                      !disabled &&
                      setAnswers((prev) => ({ ...prev, [q.id]: option }))
                    }
                  >
                    {answers[q.id] === option ? (
                      <CheckCircle2Icon className="text-primary size-5" />
                    ) : (
                      <CircleIcon className="text-muted-foreground size-5" />
                    )}
                    <div className="flex-1 text-sm font-medium">
                      {option}
                      {option === q.recommended_option && (
                        <span className="text-muted-foreground ml-2 text-xs font-normal">
                          (Recommended)
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <Textarea
                disabled={disabled}
                placeholder={q.placeholder ?? "Type your answer..."}
                value={answers[q.id] ?? ""}
                onChange={(e) =>
                  setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
                }
                className="min-h-[80px]"
              />
            )}
          </div>
        ))}
      </div>

      <div className="flex justify-end border-t pt-4">
        <Button disabled={disabled ?? !isValid} onClick={handleSubmit}>
          {payload.submit_label ?? "Submit Answers"}
        </Button>
      </div>
    </div>
  );
}
