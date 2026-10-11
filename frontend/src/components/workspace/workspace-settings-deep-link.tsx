"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import {
  openSettingsDialog,
  type SettingsSection,
  useSettingsDialog,
} from "./settings";

// Record form: the compiler enforces one entry per SettingsSection, so a new
// section cannot silently stay unreachable from `?settings=` deep links.
const SETTINGS_SECTIONS: Record<SettingsSection, true> = {
  models: true,
  users: true,
  account: true,
  appearance: true,
  channels: true,
  memory: true,
  subagents: true,
  notification: true,
  about: true,
};

function asSettingsSection(value: string | null): SettingsSection | null {
  if (!value) return null;
  // `=== true` rejects inherited keys ("toString" in obj is true) that both
  // `in` and bare indexing would admit.
  return SETTINGS_SECTIONS[value as SettingsSection] === true
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
