"use client";

import { Streamdown } from "streamdown";

import { withSafeParagraph } from "@/core/streamdown/components";

import { aboutMarkdown } from "./about-content";

export function AboutSettingsPage() {
  return (
    <Streamdown components={withSafeParagraph()}>{aboutMarkdown}</Streamdown>
  );
}