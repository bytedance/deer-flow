"use client";

import { useCallback, useSyncExternalStore } from "react";

import type { SettingsSection } from "./settings-dialog";

type Listener = () => void;

type SettingsDialogState = {
  open: boolean;
  section: SettingsSection;
};

const listeners = new Set<Listener>();

let state: SettingsDialogState = { open: false, section: "appearance" };

function emitChange() {
  for (const listener of listeners) {
    listener();
  }
}

function setState(next: SettingsDialogState) {
  if (next.open === state.open && next.section === state.section) {
    return;
  }
  state = next;
  emitChange();
}

export function subscribeSettingsDialog(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getSettingsDialogSnapshot(): SettingsDialogState {
  return state;
}

const SERVER_SNAPSHOT: SettingsDialogState = {
  open: false,
  section: "appearance",
};

function getServerSnapshot(): SettingsDialogState {
  return SERVER_SNAPSHOT;
}

export function openSettingsDialog(section: SettingsSection) {
  setState({ open: true, section });
}

export function setSettingsDialogOpen(open: boolean) {
  setState({ open, section: state.section });
}

/**
 * Shared open/section state for the single application-wide Settings dialog.
 *
 * Multiple entry points (nav menu, command palette, `?settings=` deep link)
 * drive this one store instead of each mounting its own `SettingsDialog`, so
 * two dialogs can never be open at once with racing per-instance flows (e.g.
 * duplicate Lark auth device-code polling).
 */
export function useSettingsDialog() {
  const snapshot = useSyncExternalStore(
    subscribeSettingsDialog,
    getSettingsDialogSnapshot,
    getServerSnapshot,
  );

  const open = useCallback((section: SettingsSection) => {
    openSettingsDialog(section);
  }, []);

  const setOpen = useCallback((next: boolean) => {
    setSettingsDialogOpen(next);
  }, []);

  return {
    open: snapshot.open,
    section: snapshot.section,
    openSettings: open,
    setSettingsOpen: setOpen,
  };
}
