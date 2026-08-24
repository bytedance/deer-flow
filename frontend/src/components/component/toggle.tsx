"use client";

import type { ReactNode } from "react";

import {
  ToggleGroup as UIToggleGroup,
  ToggleGroupItem,
} from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";

import { toggleClass, toggleItemClass } from "./styles";

const scrollWrapClass =
  "flex min-h-8 items-center overflow-x-auto [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden";

export type ToggleOption = {
  value: string;
  label: ReactNode;
  ariaLabel?: string;
};

function toggleAriaLabel(item: ToggleOption): string {
  if (item.ariaLabel) {
    return item.ariaLabel;
  }
  if (typeof item.label === "string" || typeof item.label === "number") {
    return String(item.label);
  }
  return item.value;
}

type ToggleBase = {
  items: ToggleOption[];
  disabled?: boolean;
  scrollable?: boolean;
  className?: string;
  "data-testid"?: string;
};

export type ToggleProps = ToggleBase &
  (
    | {
        type?: "single";
        value: string;
        onValueChange: (value: string) => void;
      }
    | {
        type: "multiple";
        value: string[];
        onValueChange: (value: string[]) => void;
      }
  );

export function Toggle(props: ToggleProps) {
  const {
    items,
    disabled,
    scrollable = false,
    className,
    "data-testid": testId,
  } = props;

  const rowClass = cn(
    toggleClass,
    scrollable && "inline-flex w-max min-w-0",
    className,
  );

  const body =
    props.type === "multiple" ? (
      <UIToggleGroup
        type="multiple"
        variant="outline"
        size="sm"
        spacing={0}
        value={props.value}
        disabled={disabled}
        data-testid={testId}
        className={rowClass}
        onValueChange={(next) => {
          if (next.length === 0) {
            return;
          }
          props.onValueChange(next);
        }}
      >
        {items.map((item) => (
          <ToggleGroupItem
            key={item.value}
            value={item.value}
            className={toggleItemClass}
            aria-label={toggleAriaLabel(item)}
          >
            {item.label}
          </ToggleGroupItem>
        ))}
      </UIToggleGroup>
    ) : (
      <UIToggleGroup
        type="single"
        variant="outline"
        size="sm"
        spacing={0}
        value={props.value}
        disabled={disabled}
        data-testid={testId}
        className={rowClass}
        onValueChange={(value) => {
          if (value) {
            props.onValueChange(value);
          }
        }}
      >
        {items.map((item) => (
          <ToggleGroupItem
            key={item.value}
            value={item.value}
            className={toggleItemClass}
            aria-label={toggleAriaLabel(item)}
          >
            {item.label}
          </ToggleGroupItem>
        ))}
      </UIToggleGroup>
    );

  if (scrollable) {
    return <div className={scrollWrapClass}>{body}</div>;
  }

  return body;
}
