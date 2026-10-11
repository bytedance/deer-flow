import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const mocks = rs.hoisted(() => ({
  pathname: "/workspace/chats/a",
  user: { id: "account-a" } as { id: string } | null,
}));

rs.mock("next/navigation", () => ({ usePathname: () => mocks.pathname }));
rs.mock("@/components/ui/sidebar", () => ({
  useSidebar: () => ({ setOpen: rs.fn() }),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: mocks.user }),
}));
rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

import {
  ArtifactsProvider,
  useArtifacts,
} from "@/components/workspace/artifacts/context";
import {
  ArtifactDraftsProvider,
  useArtifactDraftOwner,
} from "@/core/artifacts/draft-context";

const filepath = "/mnt/user-data/outputs/report.txt";

function Probe() {
  const { drafts, setDrafts } = useArtifacts();
  const draft = drafts[filepath];
  return (
    <>
      <output data-testid="draft">{draft?.draftContent ?? "no draft"}</output>
      <button
        onClick={() =>
          setDrafts({
            [filepath]: {
              filepath,
              baselineContent: "original",
              draftContent: mocks.pathname.endsWith("/b")
                ? "B edit"
                : "unsaved edit",
              baselineSha256: "a".repeat(64),
              conflict: false,
            },
          })
        }
      >
        Edit
      </button>
      <button onClick={() => setDrafts({})}>Discard</button>
      <button
        onClick={() =>
          setDrafts((current) => ({
            ...current,
            [filepath]: {
              ...current[filepath]!,
              baselineContent: current[filepath]!.draftContent,
              baselineSha256: "b".repeat(64),
            },
          }))
        }
      >
        Save
      </button>
    </>
  );
}

function AccountWorkspace({
  show = true,
  routeKey = "stable",
}: {
  show?: boolean;
  routeKey?: string;
}) {
  useArtifactDraftOwner(mocks.user?.id ?? null);
  return (
    <>
      {show ? (
        <ArtifactsProvider key={routeKey}>
          <Probe />
        </ArtifactsProvider>
      ) : null}
    </>
  );
}

function Workspace(props: {
  show?: boolean;
  workspace?: boolean;
  routeKey?: string;
}) {
  return (
    <ArtifactDraftsProvider>
      {props.workspace === false ? (
        <p>Home</p>
      ) : (
        <AccountWorkspace {...props} />
      )}
    </ArtifactDraftsProvider>
  );
}

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  mocks.pathname = "/workspace/chats/a";
  mocks.user = { id: "account-a" };
});

describe("artifact draft navigation", () => {
  it("keeps drafts and the unload warning across the workspace-to-home exit", () => {
    const view = render(<Workspace />);
    fireEvent.click(screen.getByText("Edit"));
    mocks.pathname = "/";
    view.rerender(<Workspace workspace={false} />);
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    mocks.pathname = "/workspace/chats/a";
    view.rerender(<Workspace />);
    expect(screen.getByTestId("draft").textContent).toBe("unsaved edit");
  });
  it("keeps separate drafts through A-B-A navigation", () => {
    const view = render(<Workspace />);
    fireEvent.click(screen.getByText("Edit"));
    mocks.pathname = "/workspace/chats/b";
    view.rerender(<Workspace />);
    expect(screen.getByTestId("draft").textContent).toBe("no draft");
    fireEvent.click(screen.getByText("Edit"));
    expect(screen.getByTestId("draft").textContent).toBe("B edit");
    mocks.pathname = "/workspace/chats/a";
    view.rerender(<Workspace />);
    expect(screen.getByTestId("draft").textContent).toBe("unsaved edit");
    mocks.pathname = "/workspace/chats/b";
    view.rerender(<Workspace />);
    expect(screen.getByTestId("draft").textContent).toBe("B edit");
  });

  it("retains a draft when the route-local provider unmounts", () => {
    const view = render(<Workspace />);
    fireEvent.click(screen.getByText("Edit"));
    view.rerender(<Workspace show={false} />);
    view.rerender(<Workspace routeKey="replacement" />);
    expect(screen.getByTestId("draft").textContent).toBe("unsaved edit");
  });

  it("does not show the previous account's draft on the same route", () => {
    const view = render(<Workspace />);
    fireEvent.click(screen.getByText("Edit"));
    mocks.user = { id: "account-b" };
    view.rerender(<Workspace />);
    expect(screen.getByTestId("draft").textContent).toBe("no draft");
    mocks.user = { id: "account-a" };
    view.rerender(<Workspace />);
    expect(screen.getByTestId("draft").textContent).toBe("no draft");
  });

  it("clears account drafts on logout and removes their unload warning", () => {
    const view = render(<Workspace />);
    fireEvent.click(screen.getByText("Edit"));
    mocks.user = null;
    view.rerender(<Workspace />);
    expect(screen.getByTestId("draft").textContent).toBe("no draft");
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    mocks.user = { id: "account-a" };
    view.rerender(<Workspace />);
    expect(screen.getByTestId("draft").textContent).toBe("no draft");
  });

  it("warns about dirty drafts when no artifact page is mounted", () => {
    const view = render(<Workspace />);
    fireEvent.click(screen.getByText("Edit"));
    view.rerender(<Workspace show={false} />);
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("does not keep file contents in browser storage or across root unmount", () => {
    const view = render(<Workspace />);
    fireEvent.click(screen.getByText("Edit"));
    const stored = Object.values(window.sessionStorage).join("");
    expect(stored).not.toContain("unsaved edit");
    view.unmount();
    render(<Workspace />);
    expect(screen.getByTestId("draft").textContent).toBe("no draft");
  });

  it("clears the unload warning after Save and does not revive discarded drafts", () => {
    const view = render(<Workspace />);
    fireEvent.click(screen.getByText("Edit"));
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByText("Save"));
    const saved = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(saved);
    expect(saved.defaultPrevented).toBe(false);
    fireEvent.click(screen.getByText("Discard"));
    view.rerender(<Workspace show={false} />);
    view.rerender(<Workspace />);
    expect(screen.getByTestId("draft").textContent).toBe("no draft");
  });
});
