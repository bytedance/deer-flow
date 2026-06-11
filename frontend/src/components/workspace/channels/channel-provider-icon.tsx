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

  if (normalizedProvider === "feishu") {
    return (
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className={cn("size-5", className)}
        {...props}
      >
        <circle cx="12" cy="12" r="11" fill="#FFFFFF" />
        <path
          d="M7.5 4.4a3.1 3.1 0 0 1 4.4 0L14 6.5l-4.4 4.4-2.1-2.1a3.1 3.1 0 0 1 0-4.4Z"
          fill="#3370FF"
        />
        <path
          d="M15.2 7.5a3.1 3.1 0 0 1 4.4 4.4L17.5 14l-4.4-4.4 2.1-2.1Z"
          fill="#00D6B9"
        />
        <path
          d="M16.5 13.1 18.6 15.2a3.1 3.1 0 1 1-4.4 4.4L12 17.5l4.5-4.4Z"
          fill="#FFB400"
        />
        <path
          d="M6.5 10 11 14.5l-2.2 2.1a3.1 3.1 0 0 1-4.4-4.4L6.5 10Z"
          fill="#00A0FF"
        />
        <circle cx="12" cy="12" r="2.4" fill="#FFFFFF" />
      </svg>
    );
  }

  if (normalizedProvider === "dingtalk") {
    return (
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className={cn("size-5", className)}
        {...props}
      >
        <circle cx="12" cy="12" r="11" fill="#1677FF" />
        <path
          fill="#FFFFFF"
          d="M7.3 6.3c3 .5 6.2 1 9.4 1.2.5 0 .7.6.3 1l-2.1 2.1 2.5 1c.4.2.4.8 0 1l-9.7 4.9c-.5.3-1-.3-.7-.8l2.3-3.9-2.9-1.3c-.5-.2-.4-.9.1-1l4.6-.9-4.3-2.3c-.5-.3-.2-1.1.5-1Z"
        />
      </svg>
    );
  }

  if (normalizedProvider === "wechat") {
    return (
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className={cn("size-5", className)}
        {...props}
      >
        <circle cx="12" cy="12" r="11" fill="#07C160" />
        <path
          fill="#FFFFFF"
          d="M10.4 6.5c-3 0-5.4 2-5.4 4.5 0 1.4.8 2.7 2.1 3.5l-.5 1.8 2-.9c.6.1 1.2.2 1.8.2 3 0 5.4-2 5.4-4.5s-2.4-4.6-5.4-4.6Zm-1.9 3.7a.7.7 0 1 1 0-1.4.7.7 0 0 1 0 1.4Zm3.7 0a.7.7 0 1 1 0-1.4.7.7 0 0 1 0 1.4Z"
        />
        <path
          fill="#FFFFFF"
          fillOpacity=".86"
          d="M14.4 12.3c2.5 0 4.6 1.7 4.6 3.8 0 1.1-.6 2.1-1.6 2.8l.4 1.5-1.7-.8c-.5.1-1.1.2-1.7.2-2.5 0-4.6-1.7-4.6-3.8s2.1-3.7 4.6-3.7Zm-1.6 3.1a.6.6 0 1 0 0-1.2.6.6 0 0 0 0 1.2Zm3.1 0a.6.6 0 1 0 0-1.2.6.6 0 0 0 0 1.2Z"
        />
      </svg>
    );
  }

  if (normalizedProvider === "wecom") {
    return (
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className={cn("size-5", className)}
        {...props}
      >
        <circle cx="12" cy="12" r="11" fill="#2A7DE1" />
        <path
          fill="#FFFFFF"
          d="M11 5.8c-3.4 0-6.1 2.2-6.1 5 0 1.6.9 3 2.4 3.9l-.5 2 2.1-1c.7.2 1.4.2 2.1.2 3.4 0 6.1-2.3 6.1-5.1s-2.7-5-6.1-5Zm-2.2 4.3a.8.8 0 1 1 0-1.6.8.8 0 0 1 0 1.6Zm4.3 0a.8.8 0 1 1 0-1.6.8.8 0 0 1 0 1.6Z"
        />
        <path
          fill="#31C48D"
          d="M15.1 12.4c2.2 0 4 1.5 4 3.3 0 1-.5 1.9-1.4 2.5l.4 1.4-1.5-.7c-.5.1-1 .2-1.5.2-2.2 0-4-1.5-4-3.4 0-1.8 1.8-3.3 4-3.3Z"
        />
      </svg>
    );
  }

  return (
    <MessageCircleIcon aria-hidden="true" className={cn("size-5", className)} />
  );
}
