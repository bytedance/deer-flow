"use client";

import { useI18n } from "@/core/i18n/hooks";
import { SafeStreamdown } from "@/core/streamdown/components";

import { aboutMarkdownEnUS, aboutMarkdownZhCN } from "./about-content";

export function AboutSettingsPage() {
  const { locale } = useI18n();
  const aboutMarkdown = locale.startsWith("zh")
    ? aboutMarkdownZhCN
    : aboutMarkdownEnUS;
  return <SafeStreamdown>{aboutMarkdown}</SafeStreamdown>;
}
