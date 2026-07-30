"use client";

import { SafeStreamdown } from "@/core/streamdown/components";

import { aboutMarkdown } from "./about-content";

export function AboutSettingsPage() {
  return <SafeStreamdown>{aboutMarkdown}</SafeStreamdown>;
}
