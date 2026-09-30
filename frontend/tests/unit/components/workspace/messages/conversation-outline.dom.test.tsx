import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ConversationOutline } from "@/components/workspace/messages/conversation-outline";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import type { ConversationChapter } from "@/core/messages/conversation-outline";

const chapters: ConversationChapter[] = [
  { id: "human-1", groupIndex: 0, title: "First question" },
  { id: "human-2", groupIndex: 2, title: "Second question" },
];

function renderOutline(
  props: Partial<React.ComponentProps<typeof ConversationOutline>> = {},
) {
  return render(
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <ConversationOutline
        chapters={chapters}
        activeChapterId="human-2"
        onChapterSelect={() => undefined}
        {...props}
      />
      <div role="log">Conversation transcript</div>
    </I18nContext.Provider>,
  );
}

function openOutline() {
  fireEvent.pointerDown(
    screen.getByRole("button", { name: "Conversation outline" }),
    { button: 0, ctrlKey: false },
  );
}

afterEach(cleanup);
afterEach(() => {
  rs.restoreAllMocks();
});

describe("ConversationOutline", () => {
  it("renders ordered chapters and exposes the active location", async () => {
    renderOutline();

    openOutline();

    expect(await screen.findByText("First question")).toBeTruthy();
    expect(screen.getByText("Second question")).toBeTruthy();
    const menu = screen.getByTestId("conversation-outline-menu");
    expect(menu.classList.contains("overflow-y-auto")).toBe(true);
    expect(menu.classList.contains("max-h-[min(72vh,36rem)]")).toBe(true);
    expect(menu.className).not.toContain(" h-[");
    expect(menu.textContent).not.toContain("Conversation outline");
    expect(
      screen
        .getByText("Second question")
        .closest('[role="menuitem"]')
        ?.getAttribute("aria-current"),
    ).toBe("location");
  });

  it("selects a chapter", async () => {
    const onChapterSelect = rs.fn();
    renderOutline({ onChapterSelect });
    openOutline();

    fireEvent.click(await screen.findByText("First question"));

    expect(onChapterSelect).toHaveBeenCalledWith("human-1");
    expect(screen.getByTestId("conversation-outline-menu")).toBeTruthy();
    expect(screen.getByRole("log")).toBeTruthy();
  });
});
