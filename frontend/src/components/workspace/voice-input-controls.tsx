import { Loader2Icon, MicIcon, SquareIcon, XIcon } from "lucide-react";

import { PromptInputButton } from "@/components/ai-elements/prompt-input";
import { useI18n } from "@/core/i18n/hooks";
import type { VoiceInputPhase } from "@/core/voice-input/use-voice-input";
import { cn } from "@/lib/utils";

import { Tooltip } from "./tooltip";

export function VoiceInputButton({
  disabled,
  phase,
  supported,
  onToggle,
}: {
  disabled: boolean;
  phase: VoiceInputPhase;
  supported: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const active = phase !== "idle";
  const label = active
    ? t.inputBox.voiceInputStopLabel
    : t.inputBox.voiceInputStartLabel;
  const tooltip = !supported
    ? t.inputBox.voiceInputUnsupported
    : phase === "stopping"
      ? t.inputBox.voiceInputFinishing
      : active
        ? t.inputBox.voiceInputStop
        : t.inputBox.voiceInputStart;

  return (
    <Tooltip
      content={
        <span className="block max-w-72">
          {tooltip} {supported && "(Ctrl+M)"}
        </span>
      }
    >
      <span className="inline-flex">
        <PromptInputButton
          aria-label={label}
          aria-keyshortcuts="Control+M"
          aria-pressed={active}
          className={cn(
            "size-9 rounded-full p-0! max-sm:size-11",
            active && "text-primary bg-primary/10 hover:bg-primary/15",
          )}
          data-testid="voice-input-button"
          disabled={disabled || !supported || phase === "stopping"}
          onClick={onToggle}
        >
          {phase === "starting" || phase === "stopping" ? (
            <Loader2Icon className="size-4 motion-safe:animate-spin" />
          ) : active ? (
            <SquareIcon className="size-4 fill-current" />
          ) : (
            <MicIcon className="size-4" />
          )}
        </PromptInputButton>
      </span>
    </Tooltip>
  );
}

export function VoiceInputStatus({
  phase,
  onCancel,
}: {
  phase: VoiceInputPhase;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  if (phase === "idle") return null;
  return (
    <div className="bg-secondary/60 flex items-center gap-2 rounded-lg px-3 py-1">
      <span
        className="bg-primary size-2 shrink-0 rounded-full motion-safe:animate-pulse"
        aria-hidden
      />
      <span
        role="status"
        data-testid="voice-input-status"
        className="flex-1 text-sm"
      >
        {phase === "starting"
          ? t.inputBox.voiceInputStarting
          : phase === "stopping"
            ? t.inputBox.voiceInputFinishing
            : t.inputBox.voiceInputListening}
      </span>
      <PromptInputButton
        aria-label={t.inputBox.voiceInputCancel}
        title={`${t.inputBox.voiceInputCancel} (Esc)`}
        className="size-9 shrink-0 max-sm:size-11"
        onClick={onCancel}
      >
        <XIcon className="size-4" />
      </PromptInputButton>
    </div>
  );
}
