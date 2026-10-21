import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import {
  SidebarProvider,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import {
  WorkspaceSidebarFrame,
  useWorkspaceSidebarExpanded,
} from "@/components/workspace/workspace-sidebar-frame";

const { mobile, navigation } = rs.hoisted(() => ({
  mobile: { value: true },
  navigation: { pathname: "/workspace/chats/new" },
}));
rs.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => mobile.value }));
rs.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
}));

function Contents() {
  const expanded = useWorkspaceSidebarExpanded();
  const { toggleSidebar } = useSidebar();
  return (
    <>
      <button data-sidebar="trigger" onClick={toggleSidebar}>
        Toggle navigation
      </button>
      <a href="#agents">Agents</a>
      {expanded && <p>Projects and recent chats</p>}
    </>
  );
}

function DesktopState() {
  const { open } = useSidebar();
  return <output data-testid="desktop-state">{String(open)}</output>;
}

function Harness({
  defaultOpen = false,
  collapsible = "icon",
}: {
  defaultOpen?: boolean;
  collapsible?: "icon" | "offcanvas" | "none";
}) {
  return (
    <SidebarProvider defaultOpen={defaultOpen}>
      <WorkspaceSidebarFrame collapsible={collapsible}>
        <Contents />
      </WorkspaceSidebarFrame>
      <DesktopState />
      <SidebarTrigger />
    </SidebarProvider>
  );
}

afterEach(() => {
  cleanup();
  mobile.value = true;
  navigation.pathname = "/workspace/chats/new";
  document.cookie = "sidebar_state=; path=/; max-age=0";
});

describe("workspace mobile sidebar", () => {
  it("uses the standard mobile drawer width with a collapsed desktop preference", async () => {
    render(<Harness defaultOpen />);
    fireEvent.click(screen.getByRole("button", { name: "Toggle Sidebar" }));
    const standardDrawer = await screen.findByRole("dialog");
    const standardWidth =
      standardDrawer.style.getPropertyValue("--sidebar-width");
    expect(standardWidth).not.toBe("");
    cleanup();

    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Toggle navigation" }));
    const drawer = await screen.findByRole("dialog");
    expect(drawer.style.getPropertyValue("--sidebar-width")).toBe(
      standardWidth,
    );
  });

  for (const defaultOpen of [false, true]) {
    it(`closes the mobile drawer on navigation with desktop open=${defaultOpen}`, async () => {
      const view = render(<Harness defaultOpen={defaultOpen} />);
      fireEvent.click(
        screen.getByRole("button", {
          name: defaultOpen ? "Toggle Sidebar" : "Toggle navigation",
        }),
      );
      await screen.findByRole("dialog");

      navigation.pathname = "/workspace/agents";
      view.rerender(<Harness defaultOpen={defaultOpen} />);

      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      expect(screen.getByTestId("desktop-state").textContent).toBe(
        String(defaultOpen),
      );
      expect(document.cookie).not.toContain("sidebar_state=");
    });
  }

  it("keeps a collapsed rail and opens full content without changing the desktop preference", async () => {
    render(<Harness />);
    expect(screen.getByRole("link", { name: "Agents" })).toBeDefined();
    expect(screen.queryByText("Projects and recent chats")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Toggle navigation" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Projects and recent chats")).toBeDefined();
    expect(screen.getAllByRole("link", { name: "Agents" })).toHaveLength(1);
    expect(screen.getByTestId("desktop-state").textContent).toBe("false");
    expect(document.cookie).not.toContain("sidebar_state=");

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.queryByText("Projects and recent chats")).toBeNull();
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: "Toggle navigation" }),
      ),
    );
  });

  it("restores the desktop state when leaving the mobile breakpoint", async () => {
    const view = render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Toggle navigation" }));
    await screen.findByRole("dialog");
    mobile.value = false;
    view.rerender(<Harness />);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByTestId("desktop-state").textContent).toBe("false");
    expect(screen.queryByText("Projects and recent chats")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Toggle navigation" }));
    expect(screen.getByTestId("desktop-state").textContent).toBe("true");
    expect(screen.getByText("Projects and recent chats")).toBeDefined();
  });

  for (const collapsible of ["icon", "offcanvas"] as const) {
    it(`keeps the standard mobile drawer for ${collapsible} with an expanded desktop preference`, async () => {
      render(<Harness defaultOpen collapsible={collapsible} />);
      expect(screen.queryByRole("link", { name: "Agents" })).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Toggle Sidebar" }));
      const dialog = await screen.findByRole("dialog");
      expect(
        within(dialog).getByText("Projects and recent chats"),
      ).toBeDefined();
      expect(screen.getByTestId("desktop-state").textContent).toBe("true");
    });
  }

  it("leaves a non-collapsible sidebar visible on mobile", () => {
    render(<Harness defaultOpen collapsible="none" />);
    expect(screen.getByRole("link", { name: "Agents" })).toBeDefined();
    expect(screen.getByText("Projects and recent chats")).toBeDefined();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
