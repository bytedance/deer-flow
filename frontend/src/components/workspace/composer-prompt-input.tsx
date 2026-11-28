import {
  useLayoutEffect,
  type ComponentProps,
  type SyntheticEvent,
} from "react";

import {
  PromptInput,
  usePromptInputController,
} from "@/components/ai-elements/prompt-input";

// PromptInput owns the native file input, drop and paste handlers. Intercept file
// events before those handlers while leaving keyboard and plain text input intact.
export function ComposerPromptInput({
  filesBlocked,
  textOnly,
  globalDrop,
  ...props
}: ComponentProps<typeof PromptInput> & {
  filesBlocked: boolean;
  textOnly: boolean;
}) {
  const { attachments } = usePromptInputController();
  const { clear, files } = attachments;
  useLayoutEffect(() => {
    if (textOnly && files.length) clear();
  }, [clear, textOnly, files.length]);

  function stopFileEvent(event: SyntheticEvent) {
    event.preventDefault();
    event.stopPropagation();
  }

  return (
    <div
      className="contents"
      onChangeCapture={(event) => {
        if (
          filesBlocked &&
          event.target instanceof HTMLInputElement &&
          event.target.type === "file"
        ) {
          event.target.value = "";
          stopFileEvent(event);
        }
      }}
      onDropCapture={(event) => {
        if (filesBlocked && event.dataTransfer.files.length)
          stopFileEvent(event);
      }}
      onPasteCapture={(event) => {
        if (!filesBlocked) return;
        const items = Array.from(event.clipboardData.items);
        if (items.some((item) => item.kind === "file")) {
          // Skip PromptInput's file handler, but let the browser insert the
          // text flavor of a mixed clipboard at the current selection.
          event.stopPropagation();
          if (
            !items.some(
              (item) => item.kind === "string" && item.type === "text/plain",
            )
          )
            event.preventDefault();
        }
      }}
    >
      <PromptInput {...props} globalDrop={globalDrop && !filesBlocked} />
    </div>
  );
}
