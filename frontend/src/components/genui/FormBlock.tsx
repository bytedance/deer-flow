"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { type Control, Controller, useForm } from "react-hook-form";

import type { InteractionState } from "@/core/genui/store";

interface FormFieldValidation {
  min?: number;
  max?: number;
  pattern?: string;
  message?: string;
}

interface FormFieldOption {
  label: string;
  value: string;
  group?: string;
  description?: string;
}

interface FormField {
  name: string;
  type: "text" | "number" | "email" | "password" | "textarea" | "select" | "checkbox" | "radio" | "date" | "multi-select";
  label: string;
  placeholder?: string;
  required?: boolean;
  options?: FormFieldOption[];
  searchable?: boolean;
  max_visible?: number;
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

function MultiSelectField({
  value,
  onChange,
  options,
  disabled,
  searchable,
  maxVisible = 10,
}: {
  value: string[];
  onChange: (value: string[]) => void;
  options: FormFieldOption[];
  disabled?: boolean;
  searchable?: boolean;
  maxVisible?: number;
}) {
  const [search, setSearch] = useState("");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  const filteredOptions = useMemo(() => {
    if (!search) return options;
    const lower = search.toLowerCase();
    return options.filter(
      (opt) =>
        opt.label.toLowerCase().includes(lower) ||
        opt.value.toLowerCase().includes(lower) ||
        (opt.description && opt.description.toLowerCase().includes(lower)),
    );
  }, [options, search]);

  const groups = useMemo(() => {
    const grouped = new Map<string, FormFieldOption[]>();
    for (const opt of filteredOptions) {
      const group = opt.group ?? "";
      const list = grouped.get(group) ?? [];
      list.push(opt);
      grouped.set(group, list);
    }
    return grouped;
  }, [filteredOptions]);

  const hasGroups = groups.size > 1 || (groups.size === 1 && !groups.has(""));

  const selectedSet = useMemo(() => new Set(value), [value]);

  const allFilteredSelected =
    filteredOptions.length > 0 &&
    filteredOptions.every((o) => selectedSet.has(o.value));

  const handleToggle = (optValue: string) => {
    if (selectedSet.has(optValue)) {
      onChange(value.filter((v) => v !== optValue));
    } else {
      onChange([...value, optValue]);
    }
  };

  const handleSelectAll = () => {
    const existing = new Set(value);
    for (const o of filteredOptions) existing.add(o.value);
    onChange(Array.from(existing));
  };

  const handleDeselectAll = () => {
    const filtered = new Set(filteredOptions.map((o) => o.value));
    onChange(value.filter((v) => !filtered.has(v)));
  };

  const handleGroupSelectAll = (groupOpts: FormFieldOption[]) => {
    const existing = new Set(value);
    for (const o of groupOpts) existing.add(o.value);
    onChange(Array.from(existing));
  };

  const handleGroupDeselectAll = (groupOpts: FormFieldOption[]) => {
    const groupValues = new Set(groupOpts.map((o) => o.value));
    onChange(value.filter((v) => !groupValues.has(v)));
  };

  const toggleGroupCollapse = (group: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  };

  const maxHeight = maxVisible * 32;

  const ITEM_HEIGHT = 28;
  const GROUP_HEADER_HEIGHT = 30;
  const VIRTUAL_THRESHOLD = 500;
  const useVirtual = filteredOptions.length > VIRTUAL_THRESHOLD && !hasGroups;

  const [scrollTop, setScrollTop] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  const handleScroll = useCallback(() => {
    if (scrollRef.current) setScrollTop(scrollRef.current.scrollTop);
  }, []);

  const virtualRange = useMemo(() => {
    if (!useVirtual) return null;
    const totalHeight = filteredOptions.length * ITEM_HEIGHT;
    const overscan = 5;
    const startIdx = Math.max(0, Math.floor(scrollTop / ITEM_HEIGHT) - overscan);
    const visibleCount = Math.ceil(maxHeight / ITEM_HEIGHT) + overscan * 2;
    const endIdx = Math.min(filteredOptions.length, startIdx + visibleCount);
    return { totalHeight, startIdx, endIdx };
  }, [useVirtual, filteredOptions.length, scrollTop, maxHeight]);

  const renderOption = (opt: FormFieldOption) => (
    <label
      key={opt.value}
      className="flex cursor-pointer items-center gap-2 px-3 py-1 hover:bg-muted/50"
    >
      <input
        type="checkbox"
        className="rounded border"
        checked={selectedSet.has(opt.value)}
        onChange={() => handleToggle(opt.value)}
        disabled={disabled}
      />
      <span className="text-xs">{opt.label}</span>
      {opt.description && (
        <span className="text-xs text-muted-foreground">{opt.description}</span>
      )}
    </label>
  );

  return (
    <div className="rounded-md border">
      {searchable !== false && (
        <div className="border-b p-2">
          <input
            type="text"
            placeholder="🔍 搜索..."
            className="w-full rounded-md border bg-background px-3 py-1.5 text-sm"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            disabled={disabled}
          />
        </div>
      )}

      <div className="flex items-center gap-2 border-b px-3 py-1.5">
        <label className="flex cursor-pointer items-center gap-1.5 text-xs">
          <input
            type="checkbox"
            checked={allFilteredSelected}
            onChange={() =>
              allFilteredSelected ? handleDeselectAll() : handleSelectAll()
            }
            disabled={disabled}
            className="rounded border"
          />
          全选 ({filteredOptions.length})
        </label>
      </div>

      <div
        ref={useVirtual ? scrollRef : undefined}
        className="overflow-y-auto"
        style={{ maxHeight }}
        onScroll={useVirtual ? handleScroll : undefined}
      >
        {filteredOptions.length === 0 ? (
          <div className="p-4 text-center text-xs text-muted-foreground">
            无数据
          </div>
        ) : useVirtual && virtualRange ? (
          <div style={{ height: virtualRange.totalHeight, position: "relative" }}>
            <div style={{ position: "absolute", top: virtualRange.startIdx * ITEM_HEIGHT, left: 0, right: 0 }}>
              {filteredOptions.slice(virtualRange.startIdx, virtualRange.endIdx).map(renderOption)}
            </div>
          </div>
        ) : hasGroups ? (
          Array.from(groups.entries()).map(([group, groupOpts]) => {
            const groupAllSelected = groupOpts.every((o) =>
              selectedSet.has(o.value),
            );
            const collapsed = collapsedGroups.has(group);
            return (
              <div key={group}>
                <div className="flex items-center justify-between border-b bg-muted/30 px-3 py-1">
                  <button
                    type="button"
                    className="flex items-center gap-1 text-xs font-medium"
                    onClick={() => toggleGroupCollapse(group)}
                    disabled={disabled}
                  >
                    <span>{collapsed ? "▶" : "▼"}</span>
                    {group} ({groupOpts.length})
                  </button>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="text-xs text-primary hover:underline"
                      onClick={() => handleGroupSelectAll(groupOpts)}
                      disabled={disabled || groupAllSelected}
                    >
                      全选
                    </button>
                    <button
                      type="button"
                      className="text-xs text-primary hover:underline"
                      onClick={() => handleGroupDeselectAll(groupOpts)}
                      disabled={disabled}
                    >
                      全不选
                    </button>
                  </div>
                </div>
                {!collapsed && groupOpts.map(renderOption)}
              </div>
            );
          })
        ) : (
          filteredOptions.map(renderOption)
        )}
      </div>

      <div className="border-t px-3 py-1.5 text-xs text-muted-foreground">
        已选：{value.length} / {options.length}
      </div>
    </div>
  );
}

export default function FormBlock({ block }: FormBlockProps) {
  const { props, callback_id, interactionState, onInteraction } = block;
  const { title, description, fields, submit_label = "Submit", default_values } = props;

  const { register, control, handleSubmit, formState: { errors } } = useForm({
    defaultValues: default_values as Record<string, unknown>,
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
    return null;
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
              {field.type === "multi-select" ? (
                <Controller
                  name={field.name}
                  control={control as Control}
                  rules={buildValidationRules(field)}
                  render={({ field: controllerField }) => (
                    <MultiSelectField
                      value={(controllerField.value as string[]) ?? []}
                      onChange={controllerField.onChange}
                      options={field.options ?? []}
                      disabled={isDisabled}
                      searchable={field.searchable}
                      maxVisible={field.max_visible}
                    />
                  )}
                />
              ) : field.type === "textarea" ? (
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
