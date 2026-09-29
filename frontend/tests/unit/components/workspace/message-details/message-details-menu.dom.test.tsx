import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import { MessageDetailsMenu } from "@/components/workspace/message-details/message-details-menu";

function renderMenu(onSelect = rs.fn()) {
  render(
    <>
      <input aria-label="Composer" />
      <MessageDetailsMenu
        label="Skills used"
        title="Skills"
        icon={<span aria-hidden="true">□</span>}
        entries={[{ id: "research", title: "Research", onSelect }]}
      />
    </>,
  );
  return screen.getByRole("button", { name: "Skills used" });
}

function advance(ms: number) {
  act(() => {
    void rs.advanceTimersByTime(ms);
  });
}

afterEach(() => {
  cleanup();
  rs.useRealTimers();
});

describe("message details menu interactions", () => {
  it("opens after a short mouse hover without stealing focus", async () => {
    rs.useFakeTimers();
    const trigger = renderMenu();
    const composer = screen.getByRole("textbox", { name: "Composer" });
    composer.focus();
    fireEvent.pointerEnter(trigger, { pointerType: "mouse" });
    advance(100);
    expect(screen.queryByRole("menu")).toBeNull();
    advance(30);
    expect(screen.getByRole("menuitem", { name: "Research" })).toBeTruthy();
    expect(document.activeElement).toBe(composer);
  });

  it("keeps the portaled list open while moving into it and closes after leaving", async () => {
    rs.useFakeTimers();
    const trigger = renderMenu();
    fireEvent.pointerEnter(trigger, { pointerType: "mouse" });
    advance(130);
    const menu = screen.getByRole("menu");
    fireEvent.pointerLeave(trigger, { pointerType: "mouse" });
    advance(80);
    fireEvent.pointerEnter(menu, { pointerType: "mouse" });
    advance(250);
    expect(screen.getByRole("menu")).toBe(menu);
    fireEvent.pointerLeave(menu, { pointerType: "mouse" });
    advance(100);
    expect(screen.getByRole("menu")).toBe(menu);
    advance(100);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("cancels a hover that leaves before opening and ignores touch hover", async () => {
    rs.useFakeTimers();
    const trigger = renderMenu();
    fireEvent.pointerEnter(trigger, { pointerType: "mouse" });
    advance(60);
    fireEvent.pointerLeave(trigger, { pointerType: "mouse" });
    advance(300);
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.pointerEnter(trigger, { pointerType: "touch" });
    advance(300);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("retains pointer toggling, keyboard Escape, and touch selection", async () => {
    const onSelect = rs.fn();
    const trigger = renderMenu(onSelect);
    fireEvent.pointerDown(trigger, { pointerType: "mouse", button: 0 });
    expect(await screen.findByRole("menu")).toBeTruthy();
    fireEvent.pointerDown(trigger, { pointerType: "mouse", button: 0 });
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.keyDown(trigger, { key: "Enter" });
    const menu = await screen.findByRole("menu");
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.pointerDown(trigger, { pointerType: "touch", button: 0 });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Research" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).toBeNull();
  });
});
