"use client";

import { MessageCircleIcon } from "lucide-react";
import type { SVGProps } from "react";

import { cn } from "@/lib/utils";

type ChannelProviderIconProps = SVGProps<SVGSVGElement> & {
  provider: string;
};

export function ChannelProviderIcon({
  provider,
  className,
  ...props
}: ChannelProviderIconProps) {
  const normalizedProvider = provider.toLowerCase();

  if (normalizedProvider === "telegram") {
    return (
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className={cn("size-5", className)}
        {...props}
      >
        <circle cx="12" cy="12" r="11" fill="#2AABEE" />
        <path
          fill="#FFFFFF"
          d="M17.4 7.2 15.7 16c-.1.7-.5.9-1 .6l-2.8-2.1-1.4 1.3c-.1.2-.3.3-.6.3l.2-2.9 5.3-4.8c.2-.2 0-.3-.3-.1l-6.6 4.1-2.8-.9c-.6-.2-.6-.6.1-.8l10.9-4.2c.5-.2.9.1.7.7Z"
        />
      </svg>
    );
  }

  if (normalizedProvider === "slack") {
    return (
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className={cn("size-5", className)}
        {...props}
      >
        <rect x="10.1" y="2" width="3.8" height="8.5" rx="1.9" fill="#36C5F0" />
        <rect
          x="10.1"
          y="13.5"
          width="3.8"
          height="8.5"
          rx="1.9"
          fill="#2EB67D"
        />
        <rect x="2" y="10.1" width="8.5" height="3.8" rx="1.9" fill="#ECB22E" />
        <rect
          x="13.5"
          y="10.1"
          width="8.5"
          height="3.8"
          rx="1.9"
          fill="#E01E5A"
        />
        <path
          d="M8.2 2a1.9 1.9 0 0 1 1.9 1.9v1.9H8.2a1.9 1.9 0 1 1 0-3.8Z"
          fill="#36C5F0"
        />
        <path
          d="M15.8 22a1.9 1.9 0 0 1-1.9-1.9v-1.9h1.9a1.9 1.9 0 1 1 0 3.8Z"
          fill="#2EB67D"
        />
        <path
          d="M2 15.8a1.9 1.9 0 0 1 1.9-1.9h1.9v1.9a1.9 1.9 0 1 1-3.8 0Z"
          fill="#ECB22E"
        />
        <path
          d="M22 8.2a1.9 1.9 0 0 1-1.9 1.9h-1.9V8.2a1.9 1.9 0 1 1 3.8 0Z"
          fill="#E01E5A"
        />
      </svg>
    );
  }

  if (normalizedProvider === "discord") {
    return (
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className={cn("size-5", className)}
        {...props}
      >
        <circle cx="12" cy="12" r="11" fill="#5865F2" />
        <path
          fill="#FFFFFF"
          d="M8.1 8.4c1.4-.6 2.7-.7 3.9-.7s2.5.1 3.9.7c1 1.5 1.5 3.1 1.4 4.8-.9.7-1.8 1.1-2.8 1.3l-.7-1.1c.4-.1.7-.3 1.1-.5-.3.1-.6.3-.9.4-.7.3-1.4.4-2 .4s-1.3-.1-2-.4c-.3-.1-.6-.2-.9-.4.3.2.7.4 1.1.5l-.7 1.1c-1-.2-1.9-.6-2.8-1.3-.1-1.7.4-3.3 1.4-4.8Zm2.1 3.9c.5 0 .9-.5.9-1.1s-.4-1.1-.9-1.1-.9.5-.9 1.1.4 1.1.9 1.1Zm3.6 0c.5 0 .9-.5.9-1.1s-.4-1.1-.9-1.1-.9.5-.9 1.1.4 1.1.9 1.1Z"
        />
      </svg>
    );
  }

  return (
    <MessageCircleIcon aria-hidden="true" className={cn("size-5", className)} />
  );
}
