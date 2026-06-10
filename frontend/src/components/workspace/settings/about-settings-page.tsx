"use client";

import { ClipboardSafeStreamdown } from "@/components/ai-elements/streamdown";

import { aboutMarkdown } from "./about-content";

export function AboutSettingsPage() {
  return <ClipboardSafeStreamdown>{aboutMarkdown}</ClipboardSafeStreamdown>;
}
