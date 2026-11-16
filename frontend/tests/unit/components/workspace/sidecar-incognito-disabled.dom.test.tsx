import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import {
  SidecarProvider,
  useSidecar,
} from "@/components/workspace/sidecar/context";

// The provider restores the last side thread on mount; an incognito chat must
// never make that query at all.
const api = rs.hoisted(() => ({ findLatestSidecarThread: rs.fn() }));
rs.mock("@/core/sidecar/api", () => api);

const referenceContext = {
  type: "referenced_message" as const,
  label: "Assistant message #1",
  messageId: "message-1",
  role: "assistant" as const,
  content: "quoted text",
};

function Probe() {
  const sidecar = useSidecar();
  return (
    <div>
      <span data-testid="open">{String(sidecar.open)}</span>
      <span data-testid="disabled">{String(sidecar.disabled)}</span>
      <span data-testid="sidecar-thread">
        {String(sidecar.sidecarThreadId)}
      </span>
      <span data-testid="quotes">{sidecar.conversationQuotes.length}</span>
      <button type="button" onClick={sidecar.openSidecar}>
        open-sidecar
      </button>
      <button
        type="button"
        onClick={() => sidecar.openContext(referenceContext)}
      >
        open-context
      </button>
      <button
        type="button"
        onClick={() =>
          sidecar.openSelectedText(
            {
              id: "message-1",
              type: "ai",
              content: "Hello",
            } as unknown as Message,
            "Hello",
            1,
          )
        }
      >
        open-selected-text
      </button>
      <button
        type="button"
        onClick={() => sidecar.addContextToConversation(referenceContext)}
      >
        quote
      </button>
    </div>
  );
}

function renderProbe(disabled: boolean) {
  return render(
    <SidecarProvider
      context={{ mode: "flash" }}
      disabled={disabled}
      parentThreadId="thread-1"
    >
      <Probe />
    </SidecarProvider>,
  );
}

beforeEach(() => {
  api.findLatestSidecarThread.mockReset();
  api.findLatestSidecarThread.mockResolvedValue(null);
});

afterEach(cleanup);

describe("SidecarProvider in an incognito chat", () => {
  it("never queries, restores or opens a side thread", async () => {
    renderProbe(true);

    expect(screen.getByTestId("disabled").textContent).toBe("true");
    await waitFor(() =>
      expect(api.findLatestSidecarThread).not.toHaveBeenCalled(),
    );

    fireEvent.click(screen.getByText("open-sidecar"));
    fireEvent.click(screen.getByText("open-context"));
    fireEvent.click(screen.getByText("open-selected-text"));

    expect(screen.getByTestId("open").textContent).toBe("false");
    expect(screen.getByTestId("sidecar-thread").textContent).toBe("null");
  });

  it("still quotes selected text into the main composer", () => {
    renderProbe(true);

    fireEvent.click(screen.getByText("quote"));

    expect(screen.getByTestId("quotes").textContent).toBe("1");
    expect(screen.getByTestId("open").textContent).toBe("false");
  });

  it("keeps the ordinary restore and open paths when enabled", async () => {
    renderProbe(false);

    expect(screen.getByTestId("disabled").textContent).toBe("false");
    await waitFor(() =>
      expect(api.findLatestSidecarThread).toHaveBeenCalledTimes(1),
    );

    fireEvent.click(screen.getByText("open-context"));

    expect(screen.getByTestId("open").textContent).toBe("true");
  });
});
