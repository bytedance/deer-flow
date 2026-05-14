"use client";

import type { InteractionState } from "@/core/genui/store";

interface ConfirmBlockProps {
  block: {
    props: {
      title: string;
      message: string;
      confirm_label?: string;
      cancel_label?: string;
      variant?: "default" | "destructive";
    };
    callback_id?: string;
    interactionState?: InteractionState;
    onInteraction?: (callbackId: string, payload: Record<string, unknown>) => void;
  };
}

export default function ConfirmBlock({ block }: ConfirmBlockProps) {
  const { props, callback_id, interactionState, onInteraction } = block;
  const { title, message, confirm_label = "Confirm", cancel_label = "Cancel", variant = "default" } = props;

  const isDisabled = interactionState?.status === "loading" ||
    interactionState?.status === "submitted" ||
    interactionState?.status === "expired" ||
    interactionState?.status === "readonly";

  const handleConfirm = () => {
    if (callback_id && onInteraction) {
      onInteraction(callback_id, { confirmed: true });
    }
  };

  const handleCancel = () => {
    if (callback_id && onInteraction) {
      onInteraction(callback_id, { confirmed: false });
    }
  };

  if (interactionState?.status === "submitted") {
    return (
      <div className="rounded-lg border border-green-200 bg-green-50 p-4 dark:border-green-800 dark:bg-green-950" role="status">
        <p className="text-sm text-green-800 dark:text-green-200">Action confirmed.</p>
      </div>
    );
  }

  if (interactionState?.status === "expired") {
    return (
      <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4 dark:border-yellow-800 dark:bg-yellow-950" role="status">
        <p className="text-sm text-yellow-800 dark:text-yellow-200">This action has expired.</p>
      </div>
    );
  }

  const confirmButtonClass = variant === "destructive"
    ? "bg-red-600 text-white hover:bg-red-700"
    : "bg-primary text-primary-foreground hover:bg-primary/90";

  return (
    <div className="rounded-lg border bg-card p-4" role="alertdialog" aria-label={title} aria-describedby="confirm-message">
      <h3 className="text-sm font-medium">{title}</h3>
      <p id="confirm-message" className="mt-1 text-sm text-muted-foreground">{message}</p>
      <div className="mt-4 flex gap-2" role="group" aria-label="Actions">
        <button
          onClick={handleConfirm}
          disabled={isDisabled}
          className={`rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50 ${confirmButtonClass}`}
          aria-label={confirm_label}
        >
          {interactionState?.status === "loading" ? "Processing..." : confirm_label}
        </button>
        <button
          onClick={handleCancel}
          disabled={isDisabled}
          className="rounded-md border px-4 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50"
          aria-label={cancel_label}
        >
          {cancel_label}
        </button>
      </div>
      {interactionState?.status === "error" && (
        <p className="mt-2 text-xs text-red-600" role="alert">{interactionState.error}</p>
      )}
    </div>
  );
}
