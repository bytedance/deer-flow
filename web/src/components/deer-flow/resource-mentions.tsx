// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useTranslations } from "next-intl";
import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import type { Resource } from "~/core/messages";
import { cn } from "~/lib/utils";

export interface ResourceMentionsProps {
  items: Array<Resource>;
  command: (item: { id: string; label: string }) => void;
}

export const ResourceMentions = forwardRef<
  { onKeyDown: (args: { event: KeyboardEvent }) => boolean },
  ResourceMentionsProps
>((props, ref) => {
  const t = useTranslations("common")
  const [selectedIndex, setSelectedIndex] = useState(0);

  const selectItem = (index: number) => {
    const item = props.items[index];

    if (item) {
      props.command({ id: item.uri, label: item.title });
    }
  };

  const upHandler = () => {
    setSelectedIndex(
      (selectedIndex + props.items.length - 1) % props.items.length,
    );
  };

  const downHandler = () => {
    setSelectedIndex((selectedIndex + 1) % props.items.length);
  };

  const enterHandler = () => {
    selectItem(selectedIndex);
  };

  useEffect(() => setSelectedIndex(0), [props.items]);

  useImperativeHandle(ref, () => ({
    onKeyDown: ({ event }) => {
      if (event.key === "ArrowUp") {
        upHandler();
        return true;
      }

      if (event.key === "ArrowDown") {
        downHandler();
        return true;
      }

      if (event.key === "Enter") {
        enterHandler();
        return true;
      }

      return false;
    },
  }));

  return (
    <div className="bg-card border-var(--border) relative flex flex-col gap-1 overflow-auto rounded-md border p-2 shadow">
      {props.items.length ? (
        props.items.map((item, index) => (
          <button
            className={cn(
              "focus-visible:ring-ring hover:bg-accent hover:text-accent-foreground inline-flex h-9 w-full items-center justify-start gap-2 rounded-md px-4 py-2 text-sm whitespace-nowrap transition-colors focus-visible:ring-1 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
              selectedIndex === index &&
                "bg-secondary text-secondary-foreground",
            )}
            key={index}
            onClick={() => selectItem(index)}
          >
            {item.title}
          </button>
        ))
      ) : (
        <div className="items-center justify-center text-gray-500">
          {t("noResult")}
        </div>
      )}
    </div>
  );
});
