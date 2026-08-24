import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { Trash2Icon } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";

rs.mock("next/link", () => ({
  default: ({
    href,
    children,
    className,
    ...props
  }: {
    href: string;
    children: ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className} {...props}>
      {children}
    </a>
  ),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    t: {
      common: {
        confirmTitle: "Confirm",
        cancel: "Cancel",
      },
    },
    changeLocale: rs.fn(),
  }),
}));

import {
  CardAction,
  ConfirmDialog,
  DialogTextareaField,
  formatItemListCountLabel,
  ItemRow,
  ItemRowMeta,
  ItemRowSubtitle,
  ItemRowTitle,
  WorkspaceIndexList,
} from "@/components/component";

afterEach(() => {
  rs.restoreAllMocks();
  cleanup();
});

describe("ItemRow flush href navigation", () => {
  it("renders stretched links for row content and isolates action clicks", () => {
    const onDelete = rs.fn();

    render(
      <ItemRow
        variant="flush"
        href="/workspace/chats/thread-1"
        topStart={
          <>
            <ItemRowTitle>Thread title</ItemRowTitle>
            <ItemRowSubtitle>Preview text</ItemRowSubtitle>
          </>
        }
        topEnd={<span>2h ago</span>}
        bottomStart={
          <ItemRowMeta>
            <span>Feishu</span>
          </ItemRowMeta>
        }
        bottomEnd={
          <CardAction
            icon={Trash2Icon}
            label="Delete"
            variant="destructive"
            onClick={onDelete}
          />
        }
      />,
    );

    const links = screen.getAllByRole("link");
    expect(links.length).toBeGreaterThan(0);
    expect(
      links.some(
        (link) => link.getAttribute("href") === "/workspace/chats/thread-1",
      ),
    ).toBe(true);
    expect(
      links.some((link) => within(link).queryByText("Feishu") != null),
    ).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledTimes(1);
  });
});

describe("DialogTextareaField auto-grow", () => {
  it("shrinks after deleting multiline content", () => {
    let scrollHeight = 32;
    const scrollHeightSpy = rs
      .spyOn(HTMLTextAreaElement.prototype, "scrollHeight", "get")
      .mockImplementation(() => scrollHeight);

    function NotesField() {
      const [value, setValue] = useState("");
      return (
        <DialogTextareaField
          label="Notes"
          autoGrow
          value={value}
          onChange={setValue}
        />
      );
    }

    render(<NotesField />);
    const textarea = screen.getByRole("textbox");

    scrollHeight = 96;
    fireEvent.change(textarea, {
      target: { value: "Line one\nLine two\nLine three" },
    });
    const expandedHeight = Number.parseInt(textarea.style.height, 10);
    expect(expandedHeight).toBeGreaterThan(32);

    scrollHeight = 32;
    fireEvent.change(textarea, { target: { value: "" } });
    const shrunkHeight = Number.parseInt(textarea.style.height, 10);
    expect(shrunkHeight).toBeLessThan(expandedHeight);

    scrollHeightSpy.mockRestore();
  });
});

describe("ConfirmDialog destructive confirm", () => {
  it("uses solid destructive styling when confirmVariant is destructive", () => {
    render(
      <ConfirmDialog
        open
        onOpenChange={rs.fn()}
        description="Delete this thread?"
        confirmLabel="Delete"
        confirmVariant="destructive"
        onConfirm={rs.fn()}
      />,
    );

    const confirm = screen.getByRole("button", { name: "Delete" });
    expect(confirm.getAttribute("data-variant")).toBe("destructive");
  });

  it("uses red-text outline styling for outline-delete variant", () => {
    render(
      <ConfirmDialog
        open
        onOpenChange={rs.fn()}
        description="Delete this thread?"
        confirmLabel="Delete"
        onConfirm={rs.fn()}
      />,
    );

    const confirm = screen.getByRole("button", { name: "Delete" });
    expect(confirm.getAttribute("data-variant")).toBe("ghost");
    expect(confirm.className).toContain("text-destructive");
  });
});

describe("CardAction destructive variant", () => {
  it("applies destructive outline classes", () => {
    render(
      <CardAction
        icon={Trash2Icon}
        label="Delete"
        variant="destructive"
        onClick={rs.fn()}
      />,
    );

    const button = screen.getByRole("button", { name: "Delete" });
    expect(button.className).toContain("text-destructive");
  });
});

describe("formatItemListCountLabel", () => {
  it("shows filtered count over loaded count while searching", () => {
    expect(
      formatItemListCountLabel({
        shownCount: 2,
        loadedCount: 10,
        hasNextPage: true,
        isFiltering: true,
      }),
    ).toBe("2 / 10");
  });

  it("shows trailing plus when more pages exist", () => {
    expect(
      formatItemListCountLabel({
        shownCount: 20,
        loadedCount: 20,
        hasNextPage: true,
        isFiltering: false,
      }),
    ).toBe("20+");
  });
});

describe("WorkspaceIndexList", () => {
  it("renders search toolbar and list children", () => {
    render(
      <WorkspaceIndexList
        title="Chats"
        countLabel="3"
        search={{
          value: "",
          onChange: rs.fn(),
          placeholder: "Search",
        }}
        isEmpty={false}
        empty="No chats"
      >
        <div data-testid="row">One</div>
      </WorkspaceIndexList>,
    );

    expect(screen.getByPlaceholderText("Search")).toBeTruthy();
    expect(screen.getByTestId("row")).toBeTruthy();
  });
});
