import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render } from "@testing-library/react";

const routerPush = rs.hoisted(() => rs.fn());

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: { settings: "Settings" },
      shortcuts: {
        actions: "Actions",
        keyboardShortcuts: "Keyboard shortcuts",
        keyboardShortcutsDescription: "Available shortcuts",
        noResults: "No results",
        openCommandPalette: "Open command palette",
        searchActions: "Search actions",
        toggleSidebar: "Toggle sidebar",
      },
      sidebar: { newChat: "New chat" },
    },
  }),
}));

import { CommandPalette } from "@/components/workspace/command-palette";
import {
  openSettingsDialog,
  setSettingsDialogOpen,
} from "@/components/workspace/settings/settings-dialog-store";

function pressNewChatShortcut() {
  fireEvent.keyDown(window, {
    key: "n",
    metaKey: true,
    shiftKey: true,
  });
}

afterEach(() => {
  cleanup();
  routerPush.mockReset();
  setSettingsDialogOpen(false);
});

describe("CommandPalette global navigation", () => {
  it("does not navigate to a new chat while Settings is open", () => {
    openSettingsDialog("tokens");
    render(<CommandPalette />);

    pressNewChatShortcut();

    expect(routerPush).not.toHaveBeenCalled();
  });

  it("keeps the new-chat shortcut available when Settings is closed", () => {
    render(<CommandPalette />);

    pressNewChatShortcut();

    expect(routerPush).toHaveBeenCalledWith("/workspace/chats/new");
  });
});
