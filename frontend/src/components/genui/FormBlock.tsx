"use client";

import { useForm } from "react-hook-form";

import type { InteractionState } from "@/core/genui/store";

interface FormFieldValidation {
  min?: number;
  max?: number;
  pattern?: string;
  message?: string;
}

interface FormField {
  name: string;
  type: "text" | "number" | "email" | "password" | "textarea" | "select" | "checkbox" | "radio" | "date";
  label: string;
  placeholder?: string;
  required?: boolean;
  options?: { label: string; value: string }[];
  validation?: FormFieldValidation;
}

interface FormBlockProps {
  block: {
    props: {
      title?: string;
      description?: string;
      fields: FormField[];
      submit_label?: string;
      cancel_label?: string;
      default_values?: Record<string, unknown>;
    };
    callback_id?: string;
    interactionState?: InteractionState;
    onInteraction?: (callbackId: string, payload: Record<string, unknown>) => void;
  };
}

function buildValidationRules(field: FormField) {
  const rules: Record<string, unknown> = {};
  if (field.required) {
    rules.required = `${field.label} is required`;
  }
  if (field.validation) {
    if (field.validation.min !== undefined) {
      rules.min = { value: field.validation.min, message: field.validation.message ?? `Minimum value is ${field.validation.min}` };
    }
    if (field.validation.max !== undefined) {
      rules.max = { value: field.validation.max, message: field.validation.message ?? `Maximum value is ${field.validation.max}` };
    }
    if (field.validation.pattern) {
      rules.pattern = { value: new RegExp(field.validation.pattern), message: field.validation.message ?? "Invalid format" };
    }
  }
  return rules;
}

export default function FormBlock({ block }: FormBlockProps) {
  const { props, callback_id, interactionState, onInteraction } = block;
  const { title, description, fields, submit_label = "Submit", default_values } = props;

  const { register, handleSubmit, formState: { errors } } = useForm({
    defaultValues: default_values as Record<string, string>,
  });

  const isDisabled = interactionState?.status === "loading" ||
    interactionState?.status === "submitted" ||
    interactionState?.status === "expired";

  const onSubmit = (data: Record<string, unknown>) => {
    if (callback_id && onInteraction) {
      onInteraction(callback_id, data);
    }
  };

  if (interactionState?.status === "submitted") {
    return (
      <div className="rounded-lg border border-green-200 bg-green-50 p-4 dark:border-green-800 dark:bg-green-950" role="status">
        <p className="text-sm text-green-800 dark:text-green-200">Form submitted successfully.</p>
      </div>
    );
  }

  if (interactionState?.status === "expired") {
    return (
      <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4 dark:border-yellow-800 dark:bg-yellow-950" role="status">
        <p className="text-sm text-yellow-800 dark:text-yellow-200">This form has expired.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card p-4" role="region" aria-label={title ?? "Form"}>
      {title && <h3 className="mb-1 text-sm font-medium">{title}</h3>}
      {description && <p className="mb-3 text-xs text-muted-foreground">{description}</p>}
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-3" noValidate aria-label={title ?? "Form"}>
        {fields.map((field) => {
          const fieldError = errors[field.name];
          const errorId = `${field.name}-error`;
          return (
            <div key={field.name} className="space-y-1">
              <label className="text-xs font-medium" htmlFor={field.name}>
                {field.label}
                {field.required && <span className="text-red-500" aria-hidden="true"> *</span>}
              </label>
              {field.type === "textarea" ? (
                <textarea
                  id={field.name}
                  className={`w-full rounded-md border bg-background px-3 py-2 text-sm ${fieldError ? "border-red-500" : ""}`}
                  placeholder={field.placeholder}
                  disabled={isDisabled}
                  aria-invalid={!!fieldError}
                  aria-describedby={fieldError ? errorId : undefined}
                  aria-required={field.required}
                  {...register(field.name, buildValidationRules(field))}
                />
              ) : field.type === "select" ? (
                <select
                  id={field.name}
                  className={`w-full rounded-md border bg-background px-3 py-2 text-sm ${fieldError ? "border-red-500" : ""}`}
                  disabled={isDisabled}
                  aria-invalid={!!fieldError}
                  aria-describedby={fieldError ? errorId : undefined}
                  aria-required={field.required}
                  {...register(field.name, buildValidationRules(field))}
                >
                  <option value="">{field.placeholder ?? "Select..."}</option>
                  {field.options?.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              ) : field.type === "checkbox" ? (
                <input
                  id={field.name}
                  type="checkbox"
                  className="rounded border"
                  disabled={isDisabled}
                  aria-invalid={!!fieldError}
                  aria-describedby={fieldError ? errorId : undefined}
                  {...register(field.name, buildValidationRules(field))}
                />
              ) : (
                <input
                  id={field.name}
                  type={field.type}
                  className={`w-full rounded-md border bg-background px-3 py-2 text-sm ${fieldError ? "border-red-500" : ""}`}
                  placeholder={field.placeholder}
                  disabled={isDisabled}
                  aria-invalid={!!fieldError}
                  aria-describedby={fieldError ? errorId : undefined}
                  aria-required={field.required}
                  {...register(field.name, buildValidationRules(field))}
                />
              )}
              {fieldError && (
                <p id={errorId} className="text-xs text-red-600" role="alert">
                  {fieldError.message!}
                </p>
              )}
            </div>
          );
        })}
        <button
          type="submit"
          disabled={isDisabled}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {interactionState?.status === "loading" ? "Submitting..." : submit_label}
        </button>
      </form>
      {interactionState?.status === "error" && (
        <p className="mt-2 text-xs text-red-600" role="alert">{interactionState.error}</p>
      )}
    </div>
  );
}
