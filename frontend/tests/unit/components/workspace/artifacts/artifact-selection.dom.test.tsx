import { afterEach, expect, rs, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { useArtifactSelection } from "@/components/workspace/artifacts/use-artifact-selection";
import {
  SidecarProvider,
  useSidecar,
} from "@/components/workspace/sidecar/context";
import { I18nProvider } from "@/core/i18n/context";

rs.mock("@/core/sidecar/api", () => ({
  findLatestSidecarThread: async () => null,
}));
afterEach(cleanup);

function Source() {
  const selection = useArtifactSelection({
    filepath: "/report.md",
    threadId: "thread",
    ownerId: "owner",
    source: "Selected text\nOther text",
    revision: "a".repeat(64),
    enabled: true,
    editable: true,
  });
  return (
    <>
      <button
        onClick={() =>
          selection.onSourceSelection({
            from: 0,
            to: 13,
            rect: { left: 20, bottom: 20 },
          })
        }
      >
        Select passage
      </button>
      {selection.toolbar}
    </>
  );
}

function Panels() {
  const sidecar = useSidecar();
  // The real workspace uses one right-hand panel: opening side chat unmounts
  // ArtifactFileDetail. The edit must survive that transition.
  return (
    <>
      {!sidecar.open && <Source />}
      <output data-testid="target">
        {sidecar.artifactEdit?.context.label ?? "none"}
      </output>
      <output data-testid="references">
        {sidecar.conversationQuotes
          .map((quote) => quote.context.label)
          .join(",")}
      </output>
    </>
  );
}

function App({ threadId = "thread" }: { threadId?: string }) {
  return (
    <I18nProvider initialLocale="en-US">
      <SidecarProvider
        parentThreadId={threadId}
        context={{ thread_id: threadId, mode: "flash" }}
      >
        <Panels />
      </SidecarProvider>
    </I18nProvider>
  );
}

test("a rewrite survives the source panel unmount, then clears on chat navigation", () => {
  const app = render(<App />);
  fireEvent.click(screen.getByText("Select passage"));
  fireEvent.click(screen.getByRole("button", { name: "Rewrite selection" }));
  expect(screen.queryByText("Select passage")).toBeNull();
  expect(screen.getByTestId("target").textContent).toBe("/report.md:L1-L1");
  app.rerender(<App threadId="another-thread" />);
  expect(screen.getByTestId("target").textContent).toBe("none");
});

test("adding a quotation leaves the source open and carries source provenance", () => {
  render(<App />);
  fireEvent.click(screen.getByText("Select passage"));
  fireEvent.click(screen.getByRole("button", { name: "Add to conversation" }));
  expect(screen.getByText("Select passage")).toBeDefined();
  expect(screen.getByTestId("references").textContent).toBe("/report.md:L1-L1");
  expect(screen.getByTestId("target").textContent).toBe("none");
});
