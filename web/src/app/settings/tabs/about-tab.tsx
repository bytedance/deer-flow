// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { BadgeInfo } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Markdown } from "~/components/deer-flow/markdown";

import aboutEn from "./about-en.md";
import aboutZh from "./about-zh.md";
import type { Tab } from "./types";

export const AboutTab: Tab = () => {
  const locale = useLocale();
  const t = useTranslations("settings.about");

  const aboutContent = locale === "zh" ? aboutZh : aboutEn;

  return <Markdown>{aboutContent}</Markdown>;
};
AboutTab.icon = BadgeInfo;
AboutTab.displayName = "About";
