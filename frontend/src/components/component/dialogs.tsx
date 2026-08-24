"use client";

import type { ComponentProps, PointerEvent, ReactNode } from "react";
import { useLayoutEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { FormField } from "./form-field";
import { formatWorkspaceItemTimestamp } from "./item";
import { FormSelect, type FormSelectOption } from "./select";
import {
  dialogFieldControlClass,
  dialogTextareaControlClass,
  dialogFooterClass,
  dialogFormActionCancelGlyphClass,
  dialogDestructiveOutlineButtonClass,
  dialogFooterButtonClass,
  dialogSecondaryButtonClass,
  readOnlyFieldClass,
  selectTriggerWrapClass,
  workspaceConfirmDialogContentClass,
  workspaceDialogBodyScrollClass,
  workspaceDialogContentClass,
  workspaceFieldFocusClass,
} from "./styles";
import { Toggle, type ToggleProps } from "./toggle";

const dialogFormSectionLegendClass =
  "text-foreground/85 bg-background absolute top-0 left-3.5 z-[1] max-w-[calc(100%-1.75rem)] -translate-y-1/2 px-1.5 text-xs font-semibold tracking-wide whitespace-nowrap";

function dialogFieldWrapClass(colSpan?: "full", fieldClassName?: string) {
  return cn("min-w-0", colSpan === "full" && "sm:col-span-2", fieldClassName);
}

function DialogFieldLayout({
  label,
  colSpan,
  fieldClassName,
  hint,
  error,
  children,
}: {
  label?: string;
  colSpan?: "full";
  fieldClassName?: string;
  hint?: ReactNode;
  error?: string;
  children: ReactNode;
}) {
  const footer = error ? (
    <p className="text-destructive text-xs">{error}</p>
  ) : hint ? (
    <p className="text-muted-foreground text-xs">{hint}</p>
  ) : null;

  if (!label) {
    return (
      <>
        {children}
        {footer}
      </>
    );
  }

  return (
    <FormField
      label={label}
      className={dialogFieldWrapClass(colSpan, fieldClassName)}
    >
      {children}
      {footer}
    </FormField>
  );
}

const autoGrowMaxPx = 192;

function syncAutoGrowHeight(el: HTMLTextAreaElement) {
  el.style.height = "auto";
  const contentHeight = Math.min(el.scrollHeight, autoGrowMaxPx);
  el.style.height = `${contentHeight}px`;
}

function DialogAutoGrowTextarea({
  className,
  value,
  onChange,
  ...props
}: ComponentProps<typeof Textarea>) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (el) {
      syncAutoGrowHeight(el);
    }
  }, [value]);

  return (
    <Textarea
      ref={ref}
      value={value}
      rows={1}
      onChange={(event) => {
        onChange?.(event);
        syncAutoGrowHeight(event.currentTarget);
      }}
      className={className}
      {...props}
    />
  );
}

function dialogAutoGrowTextareaClass(textareaClassName?: string) {
  return cn(
    "border-input field-sizing-fixed max-h-96 min-h-8 w-full resize-y overflow-y-auto bg-transparent py-1.5 text-xs leading-snug shadow-xs md:text-xs dark:bg-transparent",
    workspaceFieldFocusClass,
    textareaClassName,
  );
}

function useDraggableDialogShell(open: boolean, enabled: boolean) {
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const offsetRef = useRef(offset);
  offsetRef.current = offset;
  const dragRef = useRef({
    active: false,
    startX: 0,
    startY: 0,
    originX: 0,
    originY: 0,
  });

  useLayoutEffect(() => {
    if (!open) {
      setOffset({ x: 0, y: 0 });
      dragRef.current.active = false;
    }
  }, [open]);

  const onHeaderPointerDown = (event: PointerEvent<HTMLElement>) => {
    if (!enabled || event.button !== 0) {
      return;
    }
    if (
      (event.target as HTMLElement).closest(
        "button, a, input, textarea, select, [role='combobox']",
      )
    ) {
      return;
    }
    dragRef.current = {
      active: true,
      startX: event.clientX,
      startY: event.clientY,
      originX: offsetRef.current.x,
      originY: offsetRef.current.y,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onHeaderPointerMove = (event: PointerEvent<HTMLElement>) => {
    if (!dragRef.current.active) {
      return;
    }
    setOffset({
      x: dragRef.current.originX + (event.clientX - dragRef.current.startX),
      y: dragRef.current.originY + (event.clientY - dragRef.current.startY),
    });
  };

  const endHeaderDrag = (event: PointerEvent<HTMLElement>) => {
    if (!dragRef.current.active) {
      return;
    }
    dragRef.current.active = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  return {
    contentStyle: enabled
      ? { marginLeft: offset.x, marginTop: offset.y }
      : undefined,
    headerDragProps: enabled
      ? {
          onPointerDown: onHeaderPointerDown,
          onPointerMove: onHeaderPointerMove,
          onPointerUp: endHeaderDrag,
          onPointerCancel: endHeaderDrag,
        }
      : {},
    headerClassName: enabled ? "cursor-move touch-none select-none" : undefined,
  };
}

export function DialogShell({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  bodyClassName,
  footerClassName,
  contentClassName,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  bodyClassName?: string;
  footerClassName?: string;
  contentClassName?: string;
}) {
  const { t } = useI18n();
  const isConfirm = children == null;
  const drag = useDraggableDialogShell(open, !isConfirm);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          isConfirm
            ? workspaceConfirmDialogContentClass
            : workspaceDialogContentClass,
          contentClassName,
        )}
        style={drag.contentStyle}
        showCloseButton={false}
      >
        {!isConfirm ? (
          <DialogClose className="text-muted-foreground hover:text-foreground focus-visible:ring-ring hover:bg-muted/50 absolute top-3 right-3 flex size-7 items-center justify-center rounded-md transition-colors focus-visible:ring-[3px] focus-visible:outline-none">
            <span aria-hidden className={dialogFormActionCancelGlyphClass}>
              ×
            </span>
            <span className="sr-only">{t.common.close}</span>
          </DialogClose>
        ) : null}
        <DialogHeader
          className={cn(
            "shrink-0 text-left sm:text-left",
            isConfirm && "gap-3",
            !isConfirm && "border-border/40 border-b pb-3",
            drag.headerClassName,
          )}
          {...drag.headerDragProps}
        >
          <DialogTitle
            className={cn(
              "text-base leading-snug font-semibold",
              isConfirm ? "text-base" : undefined,
              !isConfirm && "pr-8",
            )}
          >
            {title}
          </DialogTitle>
          {description ? (
            <DialogDescription
              className={
                isConfirm
                  ? "text-foreground py-2 text-center text-base leading-snug sm:text-center"
                  : undefined
              }
            >
              {description}
            </DialogDescription>
          ) : null}
        </DialogHeader>
        {children != null ? (
          <div className={cn(workspaceDialogBodyScrollClass, bodyClassName)}>
            {children}
          </div>
        ) : null}
        {footer != null ? (
          <div className={cn("shrink-0", footerClassName)}>{footer}</div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

export function DialogFormSection({
  title,
  children,
  className,
  contentClassName,
  variant = "bordered",
}: {
  title?: string;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  variant?: "plain" | "bordered";
}) {
  if (variant === "plain") {
    return (
      <section className={cn("flex min-w-0 flex-col gap-3", className)}>
        {title ? (
          <h3 className="text-foreground/90 text-xs font-medium">{title}</h3>
        ) : null}
        <div className={cn("flex min-w-0 flex-col gap-3", contentClassName)}>
          {children}
        </div>
      </section>
    );
  }

  return (
    <Card
      className={cn(
        "border-border/50 bg-muted/10 relative gap-0 overflow-visible rounded-xl border py-0 shadow-none",
        className,
      )}
    >
      {title ? (
        <span className={dialogFormSectionLegendClass}>{title}</span>
      ) : null}
      <CardContent
        className={cn(
          "flex min-w-0 flex-col gap-3 px-3 pt-4 pb-3 sm:px-4",
          contentClassName,
        )}
      >
        {children}
      </CardContent>
    </Card>
  );
}

export function DialogSlotField({
  label,
  hint,
  children,
  colSpan,
  fieldClassName,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
  colSpan?: "full";
  fieldClassName?: string;
}) {
  return (
    <DialogFieldLayout
      label={label}
      colSpan={colSpan}
      fieldClassName={fieldClassName}
      hint={hint}
    >
      {children}
    </DialogFieldLayout>
  );
}

export type FormDialogEditResourceMeta = {
  creator?: string;
  createdAt?: string;
};

export function buildFormDialogEditResourceMeta(
  record:
    | {
        user_id?: string | null;
        created_at?: string | null;
        created_by?: string | null;
      }
    | null
    | undefined,
  locale: string,
  viewer?: { id: string; email: string } | null,
): FormDialogEditResourceMeta | undefined {
  if (!record) {
    return undefined;
  }
  let creator: string | undefined;
  const trimmedCreatedBy = record.created_by?.trim();
  if (trimmedCreatedBy) {
    creator = trimmedCreatedBy;
  }
  if (!creator && viewer?.email && record.user_id === viewer.id) {
    const email = viewer.email.trim();
    if (email) {
      creator = email;
    }
  }
  const raw = record.created_at?.trim();
  const createdAt = raw ? formatWorkspaceItemTimestamp(raw, locale) : undefined;
  return Boolean(creator) || createdAt ? { creator, createdAt } : undefined;
}

export function DialogResourceMetaSection({
  title,
  creatorLabel,
  createdAtLabel,
  creator,
  createdAt,
}: {
  title: string;
  creatorLabel: string;
  createdAtLabel: string;
  creator?: string | null;
  createdAt?: string | null;
}) {
  const showCreator = Boolean(creator?.trim());
  const showCreatedAt = Boolean(createdAt?.trim());
  if (!showCreator && !showCreatedAt) {
    return null;
  }

  const rows: { label: string; value: string; tabular?: boolean }[] = [];
  if (showCreator) {
    rows.push({ label: creatorLabel, value: creator!.trim() });
  }
  if (showCreatedAt) {
    rows.push({
      label: createdAtLabel,
      value: createdAt!.trim(),
      tabular: true,
    });
  }

  return (
    <DialogFormSection title={title}>
      <DialogFieldGrid>
        {rows.map((row) => (
          <FormField key={row.label} label={row.label} className="min-w-0">
            <div
              className={cn(readOnlyFieldClass, row.tabular && "tabular-nums")}
            >
              {row.value}
            </div>
          </FormField>
        ))}
      </DialogFieldGrid>
    </DialogFormSection>
  );
}

export function DialogFieldGrid({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn("grid min-w-0 gap-x-3 gap-y-3 sm:grid-cols-2", className)}
    >
      {children}
    </div>
  );
}

export function DialogInputField({
  label,
  value,
  onChange,
  placeholder,
  disabled,
  autoFocus,
  maxLength,
  fieldClassName,
  inputClassName,
  colSpan,
  hint,
  error,
  spellCheck,
  autoCapitalize,
  autoCorrect,
  autoComplete,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  autoFocus?: boolean;
  maxLength?: number;
  fieldClassName?: string;
  inputClassName?: string;
  colSpan?: "full";
  hint?: ReactNode;
  error?: string;
  spellCheck?: boolean;
  autoCapitalize?: string;
  autoCorrect?: string;
  autoComplete?: string;
}) {
  return (
    <DialogFieldLayout
      label={label}
      colSpan={colSpan}
      fieldClassName={fieldClassName}
      hint={hint}
      error={error}
    >
      <Input
        className={cn(
          dialogFieldControlClass,
          error && "border-destructive",
          inputClassName,
        )}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        autoFocus={autoFocus}
        maxLength={maxLength}
        spellCheck={spellCheck}
        autoCapitalize={autoCapitalize}
        autoCorrect={autoCorrect}
        autoComplete={autoComplete}
      />
    </DialogFieldLayout>
  );
}

export function DialogTextareaField({
  label,
  value,
  onChange,
  placeholder,
  disabled,
  rows = 4,
  autoGrow,
  fieldClassName,
  textareaClassName,
  colSpan,
  hint,
}: {
  label?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  rows?: number;
  autoGrow?: boolean;
  fieldClassName?: string;
  textareaClassName?: string;
  colSpan?: "full";
  hint?: ReactNode;
}) {
  const control = autoGrow ? (
    <DialogAutoGrowTextarea
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      spellCheck={false}
      className={dialogAutoGrowTextareaClass(textareaClassName)}
    />
  ) : (
    <Textarea
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      rows={rows}
      className={cn(
        "field-sizing-fixed min-h-0",
        dialogTextareaControlClass,
        textareaClassName,
      )}
      spellCheck={false}
    />
  );

  if (!label) {
    return control;
  }

  return (
    <DialogFieldLayout
      label={label}
      colSpan={colSpan}
      fieldClassName={fieldClassName}
      hint={hint}
    >
      {control}
    </DialogFieldLayout>
  );
}

export function DialogSelectField({
  label,
  value,
  onValueChange,
  options,
  placeholder,
  disabled,
  hint,
  className,
  contentClassName,
  triggerLabel,
  colSpan,
  fieldClassName,
}: {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  options: FormSelectOption[];
  placeholder?: string;
  disabled?: boolean;
  hint?: ReactNode;
  className?: string;
  contentClassName?: string;
  triggerLabel?: ReactNode;
  colSpan?: "full";
  fieldClassName?: string;
}) {
  return (
    <DialogFieldLayout
      label={label}
      colSpan={colSpan}
      fieldClassName={fieldClassName}
      hint={hint}
    >
      <FormSelect
        value={value}
        onValueChange={onValueChange}
        options={options}
        placeholder={placeholder}
        disabled={disabled}
        className={cn("w-full", selectTriggerWrapClass, className)}
        contentClassName={contentClassName}
        triggerLabel={triggerLabel}
      />
    </DialogFieldLayout>
  );
}

export function DialogToggleField({
  label,
  hint,
  colSpan,
  fieldClassName,
  ...toggleProps
}: {
  label?: string;
  hint?: ReactNode;
  colSpan?: "full";
  fieldClassName?: string;
} & ToggleProps) {
  return (
    <DialogFieldLayout
      label={label}
      colSpan={colSpan}
      fieldClassName={fieldClassName}
      hint={hint}
    >
      <Toggle {...toggleProps} />
    </DialogFieldLayout>
  );
}

export function dialogSaveFooterProps(
  common: {
    cancel: string;
    save: string;
    saving: string;
    loading: string;
  },
  options: {
    busy: boolean;
    disabled?: boolean;
    busyLabel?: string;
    saveLabel?: string;
  },
) {
  const { busy, disabled, busyLabel, saveLabel } = options;
  return {
    cancelLabel: common.cancel,
    confirmLabel: busy
      ? (busyLabel ?? common.saving)
      : (saveLabel ?? common.save),
    confirmPending: busy,
    confirmDisabled: (disabled ?? false) || busy,
  };
}

export type FormDialogLeadingDestructive = {
  label: string;
  onClick: () => void;
  disabled?: boolean;
};

export function FormDialogDeleteButton({
  label,
  onClick,
  disabled,
  className,
}: FormDialogLeadingDestructive & { className?: string }) {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className={cn(dialogSecondaryButtonClass, className)}
      disabled={disabled}
      onClick={onClick}
    >
      {label}
    </Button>
  );
}

export function FormActions({
  cancelLabel,
  onCancel,
  confirmLabel,
  onConfirm,
  confirmDisabled,
  confirmPending,
  confirmVariant = "default",
  leadingDestructive,
  footerStart,
  className,
  asDialogFooter = true,
  confirmButtonTestId,
}: {
  cancelLabel?: string;
  onCancel?: () => void;
  confirmLabel: string;
  onConfirm: () => void;
  confirmDisabled?: boolean;
  confirmPending?: boolean;
  confirmVariant?: "default" | "destructive" | "outline-delete";
  leadingDestructive?: FormDialogLeadingDestructive;
  footerStart?: ReactNode;
  className?: string;
  asDialogFooter?: boolean;
  confirmButtonTestId?: string;
}) {
  const leading =
    leadingDestructive != null ? (
      <FormDialogDeleteButton {...leadingDestructive} />
    ) : (
      footerStart
    );

  const confirmUiVariant =
    confirmVariant === "destructive"
      ? "destructive"
      : confirmVariant === "outline-delete"
        ? "ghost"
        : "default";
  const confirmClass =
    confirmVariant === "destructive"
      ? dialogFooterButtonClass
      : confirmVariant === "outline-delete"
        ? dialogDestructiveOutlineButtonClass
        : dialogFooterButtonClass;

  const body = (
    <div className="flex w-full flex-wrap items-center justify-center gap-3">
      {leading}
      {cancelLabel ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className={dialogSecondaryButtonClass}
          disabled={confirmPending}
          onClick={onCancel}
        >
          {cancelLabel}
        </Button>
      ) : null}
      <Button
        type="button"
        size="sm"
        variant={confirmUiVariant}
        className={confirmClass}
        disabled={(confirmDisabled ?? false) || (confirmPending ?? false)}
        onClick={onConfirm}
        data-testid={confirmButtonTestId}
      >
        {confirmLabel}
      </Button>
    </div>
  );

  const footerClassName = cn(dialogFooterClass, className);

  if (asDialogFooter) {
    return <DialogFooter className={footerClassName}>{body}</DialogFooter>;
  }

  return <div className={cn("flex", footerClassName)}>{body}</div>;
}

export function FormDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  cancelLabel,
  confirmLabel,
  confirmDisabled,
  confirmPending,
  confirmVariant = "default",
  onConfirm,
  onCancel,
  leadingDestructive,
  footerStart,
  footer,
  footerClassName,
  confirmButtonTestId,
  editResourceMeta,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  cancelLabel?: string;
  confirmLabel: string;
  confirmDisabled?: boolean;
  confirmPending?: boolean;
  confirmVariant?: "default" | "destructive" | "outline-delete";
  onConfirm: () => void;
  onCancel?: () => void;
  leadingDestructive?: FormDialogLeadingDestructive;
  footerStart?: ReactNode;
  footer?: ReactNode;
  footerClassName?: string;
  confirmButtonTestId?: string;
  editResourceMeta?: FormDialogEditResourceMeta | null;
}) {
  const { t } = useI18n();
  const metaLabels = t.common.resourceMeta;
  const showEditMeta = editResourceMeta != null;
  const showBody = children != null || showEditMeta;

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      footer={
        footer ?? (
          <FormActions
            cancelLabel={cancelLabel}
            onCancel={() => {
              onCancel?.();
              onOpenChange(false);
            }}
            confirmLabel={confirmLabel}
            onConfirm={onConfirm}
            confirmDisabled={confirmDisabled}
            confirmPending={confirmPending}
            confirmVariant={confirmVariant}
            leadingDestructive={leadingDestructive}
            footerStart={footerStart}
            className={footerClassName}
            confirmButtonTestId={confirmButtonTestId}
          />
        )
      }
    >
      {showBody ? (
        <div className="flex flex-col gap-4">
          {children}
          {showEditMeta ? (
            <DialogResourceMetaSection
              title={metaLabels.title}
              creatorLabel={metaLabels.createdBy}
              createdAtLabel={metaLabels.createdAt}
              creator={editResourceMeta.creator}
              createdAt={editResourceMeta.createdAt}
            />
          ) : null}
        </div>
      ) : null}
    </DialogShell>
  );
}

export function ConfirmDialog({
  open,
  onOpenChange,
  description,
  title,
  cancelLabel,
  confirmLabel,
  confirmDisabled,
  confirmPending,
  confirmVariant = "outline-delete",
  onConfirm,
  onCancel,
  confirmButtonTestId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  description: ReactNode;
  title?: string;
  cancelLabel?: string;
  confirmLabel: string;
  confirmDisabled?: boolean;
  confirmPending?: boolean;
  confirmVariant?: "default" | "destructive" | "outline-delete";
  onConfirm: () => void;
  onCancel?: () => void;
  confirmButtonTestId?: string;
}) {
  const { t } = useI18n();

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title ?? t.common.confirmTitle}
      description={description}
      cancelLabel={cancelLabel ?? t.common.cancel}
      confirmLabel={confirmLabel}
      confirmDisabled={confirmDisabled}
      confirmPending={confirmPending}
      confirmVariant={confirmVariant}
      onConfirm={onConfirm}
      onCancel={onCancel}
      confirmButtonTestId={confirmButtonTestId}
    />
  );
}
