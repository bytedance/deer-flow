"use client";

import dynamic from "next/dynamic";

import {
  setSettingsDialogOpen,
  useSettingsDialog,
} from "./settings-dialog-store";

const SettingsDialog = dynamic(
  () => import("./settings-dialog").then((module) => module.SettingsDialog),
  {
    ssr: false,
    loading: () => (
      <div className="bg-background/80 fixed inset-0 z-50 grid place-items-center backdrop-blur-sm">
        <p role="status" className="text-muted-foreground text-sm">
          Loading settings…
        </p>
      </div>
    ),
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
