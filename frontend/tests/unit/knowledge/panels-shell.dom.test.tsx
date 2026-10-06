/**
 * Three-column shell (spec §5.2): draggable gutters with pixel min/max guards
 * and the push-style collapsible kb list. Fold phases are intent-driven —
 * "folding" from the click until the CSS transition reports done (a safety
 * timer stands in for transitionend in the DOM-less test environment) — so
 * the tests simulate arrival by setting the resting width and letting the
 * settle timer fire.
 */
import { afterEach, beforeAll, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import { KnowledgePanelsShell } from "@/components/workspace/knowledge/panels-shell";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";

// The settle fallback is a timer; fake timers keep it deterministic.
rs.useFakeTimers();

// react-resizable-panels measures through ResizeObserver, which happy-dom
// does not implement; a no-op stub is enough for render-level assertions.
beforeAll(() => {
  if (!("ResizeObserver" in globalThis)) {
    class ResizeObserverStub {
      observe() {
        /* no-op stub */
      }
      unobserve() {
        /* no-op stub */
      }
      disconnect() {
        /* no-op stub */
      }
    }
    (globalThis as Record<string, unknown>).ResizeObserver = ResizeObserverStub;
  }
});

function renderShell() {
  return render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      <KnowledgePanelsShell
        left={({ collapseLeft }) => (
          <button data-testid="left-collapse" type="button" onClick={collapseLeft}>
            收起
          </button>
        )}
        middle={({ listToggle }) => (
          <div data-testid="middle-content">
            <div data-testid="middle-header">{listToggle}</div>
            文档
          </div>
        )}
        right={<div data-testid="right-content">会话</div>}
      />
    </I18nContext.Provider>,
  );
}

function headerToggle() {
  return screen.queryByTestId("kb-list-toggle");
}

function foldState() {
  return screen.getByTestId("knowledge-panels-shell").getAttribute("data-kb-fold-state");
}

/** Simulate the transition landing at a resting width (stand-in for
 *  transitionend): set the width, let the settle fallback fire. */
function settleAt(aside: HTMLElement, px: number) {
  Object.defineProperty(aside, "offsetWidth", { configurable: true, value: px });
  act(() => {
    rs.advanceTimersByTime(450);
  });
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("KnowledgePanelsShell", () => {
  it("renders all three columns with two draggable separators", () => {
    const { container } = renderShell();
    expect(screen.getByTestId("left-collapse")).toBeTruthy();
    expect(screen.getByTestId("middle-content")).toBeTruthy();
    expect(screen.getByTestId("right-content")).toBeTruthy();
    expect(container.querySelectorAll('[data-slot="resizable-handle"]').length).toBe(2);
  });

  it("keeps the restore overlay inert while the list is expanded", () => {
    const { container } = renderShell();
    // The list header owns the fold in this state. The overlay stays in the
    // DOM (its node identity is stable across phases, so a fold settle never
    // re-renders the consumer subtrees — the end-of-collapse jitter); the
    // shell's fold-state attribute gates it out of sight and reach.
    expect(foldState()).toBe("expanded");
    expect(headerToggle()).toBeTruthy();
    expect(screen.getByTestId("middle-header").textContent).toBe("");
    const styleText = container.querySelector("style")?.textContent ?? "";
    expect(styleText).toContain(".kb-restore-overlay { visibility: hidden");
    expect(styleText).toContain('[data-kb-fold-state="collapsed"] .kb-restore-overlay:hover');
  });

  it("marks the shell folding while the fold is mid-flight", () => {
    renderShell();
    fireEvent.click(screen.getByTestId("left-collapse"));
    expect(foldState()).toBe("folding");
  });

  it("narrow-viewport horizontal fallback rides the overlay ScrollArea, not a native bar", () => {
    const { container } = renderShell();
    const shell = screen.getByTestId("knowledge-panels-shell");
    // 老原生滑块常驻底部横跨文档栏+会话栏（2026-09-08 退役）。
    expect(shell.className).not.toContain("overflow-x-auto");
    const scroll = container.querySelector("[data-slot='scroll-area']");
    expect(scroll).toBeTruthy();
    // 三列 Group 沉进 overlay ScrollArea 的 Viewport（真滚动层）；横向细滑条
    // 元素在 jsdom 无溢出尺寸时不挂载，故钉结构不钉 scrollbar 节点。
    const viewport = scroll?.querySelector("[data-slot='scroll-area-viewport']");
    expect(viewport).toBeTruthy();
    expect(viewport?.querySelector("#kb-list")).toBeTruthy();
  });

  it("arms the hover reveal once the fold settles", () => {
    const { container } = renderShell();
    const aside = container.querySelector("aside")!;
    fireEvent.click(screen.getByTestId("left-collapse"));
    settleAt(aside, 0);
    // The attribute flips the scoped CSS gate — no mount, no re-render storm
    // on the fold's last frame.
    expect(foldState()).toBe("collapsed");
    const toggle = headerToggle();
    // Absolute overlay CONTAINER: the control never participates in the
    // header's layout flow.
    const overlay = toggle?.parentElement;
    expect(overlay?.getAttribute("data-testid")).toBe("kb-list-toggle-overlay");
    expect(overlay?.className).toContain("absolute");
    expect(overlay?.className).toContain("kb-restore-overlay");
    expect(overlay?.className).toContain("opacity-0");
    expect(overlay?.className).toContain("transition-opacity");
    // Single visible state: an OPAQUE chip (no semi-transparent backdrop over
    // the name — that read as smudged text under the button).
    expect(toggle?.className).toContain("bg-background");
    // Never a floating overlay over content: it renders inside the header row
    // the consumer chose (over the library name).
    expect(screen.getByTestId("middle-header").contains(toggle)).toBe(true);
  });

  it("restores the list and re-gates the overlay", () => {
    const { container } = renderShell();
    const aside = container.querySelector("aside")!;
    fireEvent.click(screen.getByTestId("left-collapse"));
    settleAt(aside, 0);
    fireEvent.click(screen.getByTestId("kb-list-toggle"));
    settleAt(aside, 224);
    // Expanded at rest: the gate closes again; the list header owns the fold.
    expect(foldState()).toBe("expanded");
  });

  it("arms the flex transition on click and disarms once the fold settles", () => {
    const { container } = renderShell();
    const aside = container.querySelector("aside")!;
    const shell = screen.getByTestId("knowledge-panels-shell");
    const styleText = container.querySelector("style")?.textContent ?? "";
    expect(styleText).toContain("#kb-list");
    expect(styleText).toContain("200ms");
    expect(shell.getAttribute("data-fold-animating")).toBeNull();

    fireEvent.click(screen.getByTestId("left-collapse"));
    expect(shell.getAttribute("data-fold-animating")).toBe("true");
    settleAt(aside, 0);
    expect(shell.getAttribute("data-fold-animating")).toBeNull();
  });

  it("keeps the content clipped, never squeezed, across the whole round trip", () => {
    // The app sidebar keeps its content at a constant width and slides it —
    // here the equivalent is pinning the content to its fold-start width for
    // BOTH directions, released only once the unfold has settled. Dropping
    // the pin earlier squeezed the content back into the per-character
    // wrapping the user reported.
    const { container } = renderShell();
    const aside = container.querySelector("aside")!;
    Object.defineProperty(aside, "offsetWidth", { configurable: true, value: 224 });
    const inner = aside.firstElementChild as HTMLElement;

    fireEvent.click(screen.getByTestId("left-collapse"));
    expect(inner.style.width).toBe("224px");
    settleAt(aside, 0);
    expect(inner.style.width).toBe("224px");
    fireEvent.click(screen.getByRole("button", { name: "展开列表栏" }));
    // Still pinned mid-unfold…
    expect(inner.style.width).toBe("224px");
    // …released exactly when the unfold settles at the pinned width.
    settleAt(aside, 224);
    expect(inner.style.width).toBe("");
  });

  it("fades the content per direction while mid-flight", () => {
    const { container } = renderShell();
    const aside = container.querySelector("aside")!;
    Object.defineProperty(aside, "offsetWidth", { configurable: true, value: 224 });

    fireEvent.click(screen.getByTestId("left-collapse"));
    // Collapsing: legible for the first half, then a late accelerating fade.
    // The opacity-0 TARGET is armed mid-flight too, so the curve actually
    // runs — arming it only at the settle snapped it in one frame (the
    // collapse's end jitter).
    expect(aside.className).toContain("duration-100");
    expect(aside.className).toContain("delay-100");
    expect(aside.className).toContain("opacity-0");
    // The divider does NOT fade with it — see the gutter test below.
    const handle = container.querySelectorAll('[data-slot="resizable-handle"]')[0]!;
    expect(handle.className).not.toContain("opacity-0");
    settleAt(aside, 0);
    expect(aside.className).toContain("opacity-0");

    fireEvent.click(screen.getByRole("button", { name: "展开列表栏" }));
    // Expanding: fade in over the whole curve, no delay.
    expect(aside.className).toContain("duration-200");
    expect(aside.className).not.toContain("delay-100");
    expect(aside.className).not.toContain("opacity-0");
  });

  it("keeps the collapsed gutter painted so the table stays flush with the divider", () => {
    const { container } = renderShell();
    const aside = container.querySelector("aside")!;
    Object.defineProperty(aside, "offsetWidth", { configurable: true, value: 224 });
    const handle = container.querySelectorAll('[data-slot="resizable-handle"]')[0]!;
    // Expanded: painted and draggable.
    expect(handle.className).toContain("w-0.5");
    expect(handle.className).not.toContain("opacity-0");
    expect(handle.className).not.toContain("pointer-events-none");

    fireEvent.click(screen.getByTestId("left-collapse"));
    // Painted through the whole fold, not merely at rest: a fade needs a
    // matching in-flight transition and still snaps back at the settle.
    expect(handle.className).not.toContain("opacity-0");
    settleAt(aside, 0);
    // Collapsed: the 2px slot still paints bg-border. Fading it out left that
    // slot as bare bg-background between the app sidebar's border-r and the
    // middle column, so the document table's left edge — hence the header
    // hairline, and a selected row's background — began 2px short of the
    // divider while the right gutter sat flush against its own. Only
    // interactivity goes: a zero-width panel has nothing to drag, and the
    // restore chip owns the unfold.
    expect(handle.className).not.toContain("opacity-0");
    expect(handle.className).toContain("pointer-events-none");

    fireEvent.click(screen.getByRole("button", { name: "展开列表栏" }));
    settleAt(aside, 224);
    expect(handle.className).not.toContain("pointer-events-none");
  });
});

describe("KnowledgePanelsShell 中栏通知面（2026-09-08）", () => {
  it("mounts the scoped toaster inside the middle column, never in the chat column", () => {
    renderShell();
    // 中栏容器 relative：absolute 通知面的定位锚（通知落在本栏右下角）。
    const middle = screen.getByTestId("middle-content").closest("section");
    expect(middle?.className).toContain("relative");
    // sonner scoped Toaster 挂在中栏内（其 section 是 absolute ol 的宿主）。
    expect(middle?.querySelector("section[aria-label^='Notifications']")).toBeTruthy();
    // 会话栏零通知面：通知不再 fixed 到视口右下压住输入框。
    const chat = screen.getByTestId("right-content").closest("aside");
    expect(chat?.querySelector("section[aria-label^='Notifications']")).toBeFalsy();
  });
});
