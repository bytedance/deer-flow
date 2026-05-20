"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { SkillSettingsPage } from "@/components/workspace/settings/skill-settings-page";

export default function SettingsSkillsRoute() {
  const router = useRouter();
  const handleClose = useCallback(() => {
    router.push("/workspace");
  }, [router]);
  return <SkillSettingsPage onClose={handleClose} />;
}
