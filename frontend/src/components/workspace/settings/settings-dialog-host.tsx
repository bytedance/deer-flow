"use client";

import { SettingsDialog } from "./settings-dialog";
import {
  setSettingsDialogOpen,
  useSettingsDialog,
} from "./settings-dialog-store";

/**
 * The single application-wide Settings dialog instance.
 *
 * Mounted once at the workspace root; every entry point (nav menu, command
 * palette, deep link) opens it through the shared store rather than mounting
 * its own dialog.
 */
export function SettingsDialogHost() {
  const { open, section } = useSettingsDialog();
  return (
    <SettingsDialog
      open={open}
      onOpenChange={setSettingsDialogOpen}
      defaultSection={section}
    />
  );
}
