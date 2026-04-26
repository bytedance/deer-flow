"use client";

import { Streamdown } from "streamdown";

import { aboutMarkdown } from "./about-content";

export function AboutSettingsPage() {
  return <Streamdown>{aboutMarkdown}</Streamdown>;
}
