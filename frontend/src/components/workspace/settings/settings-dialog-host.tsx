"use client";

import dynamic from "next/dynamic";

import { useI18n } from "@/core/i18n/hooks";

import {
  setSettingsDialogOpen,
  useSettingsDialog,
} from "./settings-dialog-store";

function SettingsDialogFallback() {
  const { t } = useI18n();
  return (
    <div className="bg-background/80 fixed inset-0 z-50 grid place-items-center backdrop-blur-sm">
      <p role="status" className="text-muted-foreground text-sm">
        {t.settings.title}…
      </p>
    </div>
  );
}

const SettingsDialog = dynamic(
  () => import("./settings-dialog").then((module) => module.SettingsDialog),
  {
    ssr: false,
    loading: SettingsDialogFallback,
  },
);

/**
 * The single application-wide Settings dialog instance.
 *
 * Mounted once at the workspace root; every entry point (nav menu, command
 * palette, deep link) opens it through the shared store rather than mounting
 * its own dialog.
 */
export function SettingsDialogHost() {
  const { open, section } = useSettingsDialog();
  if (!open) return null;
  return (
    <SettingsDialog
      open={open}
      onOpenChange={setSettingsDialogOpen}
      defaultSection={section}
    />
  );
}
