"use client";

import { useMemo } from "react";
import { Streamdown } from "streamdown";

import { useAppConfig } from "@/core/config";

import { aboutMarkdown } from "./about-content";

export function AboutSettingsPage() {
  const { brand } = useAppConfig();
  const markdown = useMemo(() => {
    return aboutMarkdown
      .replaceAll("{{brandName}}", brand.name)
      .replaceAll("{{websiteUrl}}", brand.website_url ?? "https://thinktank.ai")
      .replaceAll(
        "{{githubUrl}}",
        brand.github_url ?? "https://github.com/thinktank-ai/thinktank-ai",
      )
      .replaceAll("{{supportEmail}}", brand.support_email ?? "support@thinktank.ai");
  }, [brand.github_url, brand.name, brand.support_email, brand.website_url]);

  return <Streamdown>{markdown}</Streamdown>;
}
