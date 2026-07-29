"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import {
  openSettingsDialog,
  type SettingsSection,
  useSettingsDialog,
} from "./settings";

const SETTINGS_SECTIONS = new Set<SettingsSection>([
  "account",
  "appearance",
  "channels",
  "integrations",
  "memory",
  "tools",
  "skills",
  "notification",
  "about",
]);

function asSettingsSection(value: string | null): SettingsSection | null {
  if (!value) return null;
  return SETTINGS_SECTIONS.has(value as SettingsSection)
    ? (value as SettingsSection)
    : null;
}

/**
 * Bridges the `?settings=<section>` query param to the shared settings dialog
 * store. It does not mount its own dialog — a single {@link SettingsDialogHost}
 * renders the one dialog — so a deep link can never race a second dialog opened
 * from the nav menu or command palette.
 */
export function WorkspaceSettingsDeepLink() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { open } = useSettingsDialog();
  const openedFromDeepLinkRef = useRef(false);

  useEffect(() => {
    const nextSection = asSettingsSection(searchParams.get("settings"));
    if (nextSection) {
      openedFromDeepLinkRef.current = true;
      openSettingsDialog(nextSection);
    }
  }, [searchParams]);

  useEffect(() => {
    if (open || !openedFromDeepLinkRef.current) {
      return;
    }
    openedFromDeepLinkRef.current = false;
    if (searchParams.has("settings")) {
      const next = new URLSearchParams(searchParams);
      next.delete("settings");
      const suffix = next.toString();
      router.replace(suffix ? `${pathname}?${suffix}` : pathname, {
        scroll: false,
      });
    }
  }, [open, pathname, router, searchParams]);

  return null;
}
