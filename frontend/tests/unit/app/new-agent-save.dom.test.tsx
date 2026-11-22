import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import type { ButtonHTMLAttributes, PropsWithChildren } from "react";

import NewAgentPage from "@/app/workspace/agents/new/page";
import type { Agent } from "@/core/agents";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

const mocks = rs.hoisted(() => ({
  getAgent: rs.fn(),
  checkAgentName: rs.fn(),
  sendMessage: rs.fn(),
  toastError: rs.fn(),
  toastSuccess: rs.fn(),
  onFinish: undefined as ((state: { messages: Message[] }) => void) | undefined,
}));

rs.mock("next/navigation", () => ({ useRouter: () => ({ push: rs.fn() }) }));
rs.mock("sonner", () => ({
  toast: { error: mocks.toastError, success: mocks.toastSuccess },
}));
rs.mock("@/core/agents/api", () => ({
  ...rs.requireActual("@/core/agents/api"),
  getAgent: mocks.getAgent,
  checkAgentName: mocks.checkAgentName,
}));
rs.mock("@/core/threads/hooks", () => ({
  ...rs.requireActual("@/core/threads/hooks"),
  useThreadStream: (options: { onFinish: typeof mocks.onFinish }) => {
    mocks.onFinish = options.onFinish;
    return {
      thread: { isLoading: false, messages: [], values: {} },
      sendMessage: mocks.sendMessage,
    };
  },
}));
rs.mock("@/components/workspace/artifacts", () => ({
  ArtifactsProvider: ({ children }: PropsWithChildren) => <>{children}</>,
}));
rs.mock("@/components/workspace/messages", () => ({ MessageList: () => null }));
// Keep Save interactions accessible without depending on menu positioning.
rs.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: PropsWithChildren) => <>{children}</>,
  DropdownMenuContent: ({ children }: PropsWithChildren) => <>{children}</>,
  DropdownMenuTrigger: ({ children }: PropsWithChildren) => <>{children}</>,
  DropdownMenuItem: ({
    children,
    disabled,
    onSelect,
  }: PropsWithChildren<{
    disabled?: boolean;
    onSelect: () => void;
  }>) => (
    <button disabled={disabled} onClick={onSelect}>
      {children}
    </button>
  ),
}));
rs.mock("@/components/ai-elements/prompt-input", () => ({
  PromptInput: ({
    children,
    onSubmit,
  }: PropsWithChildren<{ onSubmit: (input: { text: string }) => void }>) => (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({ text: "Please adjust the agent" });
      }}
    >
      {children}
    </form>
  ),
  PromptInputTextarea: () => <textarea aria-label="Agent setup chat" />,
  PromptInputFooter: ({ children }: PropsWithChildren) => <>{children}</>,
  PromptInputSubmit: (props: ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props} type="submit">
      Send
    </button>
  ),
}));

const savedAgent: Agent = {
  name: "researcher",
  description: "Research assistant",
  model: null,
  tool_groups: null,
  skills: null,
};
let messages: Message[];

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function openSetup() {
  const view = render(
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <NewAgentPage />
    </I18nContext.Provider>,
  );
  fireEvent.change(
    screen.getByPlaceholderText(enUS.agents.nameStepPlaceholder),
    {
      target: { value: savedAgent.name },
    },
  );
  await act(async () => {
    fireEvent.click(
      screen.getByRole("button", { name: enUS.agents.nameStepContinue }),
    );
  });
  return view;
}

async function save() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: enUS.agents.save }));
  });
}

async function finish(status: "success" | "error" | "pending") {
  const id = `setup-${messages.length}`;
  messages.push({
    type: "ai",
    content: "",
    tool_calls: [{ id, name: "setup_agent", args: {} }],
  } as Message);
  if (status !== "pending") {
    messages.push({
      type: "tool",
      content: status,
      name: "setup_agent",
      tool_call_id: id,
      status,
    } as Message);
  }
  await act(async () => {
    mocks.onFinish!({ messages: [...messages] });
  });
}

async function subsequentSetupError() {
  await act(async () => {
    fireEvent.submit(
      screen
        .getByRole("textbox", { name: "Agent setup chat" })
        .closest("form")!,
    );
  });
  await finish("error");
}

async function exhaustRead(read: ReturnType<typeof deferred<Agent>>) {
  await act(async () => {
    read.reject(new Error("not visible yet"));
  });
  await act(() => rs.advanceTimersByTimeAsync(4_000));
}

beforeEach(() => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  mocks.getAgent.mockReset().mockRejectedValue(new Error("not visible yet"));
  mocks.checkAgentName.mockReset().mockResolvedValue({ available: true });
  mocks.sendMessage.mockReset().mockResolvedValue(undefined);
  mocks.toastError.mockReset();
  mocks.toastSuccess.mockReset();
  mocks.onFinish = undefined;
  messages = [];
});

afterEach(() => {
  cleanup();
  rs.useRealTimers();
});

describe("New-Agent Save read-back ownership", () => {
  it.each(["missing", "found"] as const)(
    "ignores an older %s read-back while a newer Save is requested",
    async (outcome) => {
      const oldRead = deferred<Agent>();
      mocks.getAgent.mockReturnValueOnce(oldRead.promise);
      await openSetup();
      await save();
      await finish("success");
      expect(mocks.getAgent).toHaveBeenCalledTimes(1);
      await subsequentSetupError();
      await save();
      mocks.toastError.mockClear();

      if (outcome === "found") {
        await act(async () => {
          oldRead.resolve(savedAgent);
        });
      } else {
        await exhaustRead(oldRead);
      }

      expect(screen.queryByText(enUS.agents.agentCreated)).toBeNull();
      expect(
        screen
          .getByRole("button", { name: enUS.agents.saving })
          .hasAttribute("disabled"),
      ).toBe(true);
      expect(mocks.toastError).not.toHaveBeenCalled();
      const readsBeforeLatestFinish = mocks.getAgent.mock.calls.length;
      mocks.getAgent.mockResolvedValueOnce(savedAgent);
      await finish("success");
      expect(mocks.getAgent).toHaveBeenCalledTimes(readsBeforeLatestFinish + 1);
      expect(screen.getByText(enUS.agents.agentCreated)).toBeTruthy();
    },
  );

  it("does not confirm an old read after a newer setup error restores Save", async () => {
    const oldRead = deferred<Agent>();
    mocks.getAgent.mockReturnValueOnce(oldRead.promise);
    await openSetup();
    await save();
    await finish("success");
    await subsequentSetupError();
    await act(async () => {
      oldRead.resolve(savedAgent);
    });
    expect(screen.queryByText(enUS.agents.agentCreated)).toBeNull();
    expect(
      screen
        .getByRole("button", { name: enUS.agents.save })
        .hasAttribute("disabled"),
    ).toBe(false);
  });

  it("ignores an older read failure after a newer read confirms creation", async () => {
    const oldRead = deferred<Agent>();
    mocks.getAgent.mockReturnValueOnce(oldRead.promise);
    await openSetup();
    await save();
    await finish("success");
    // Another chat completion starts a second read while Save is still requested.
    mocks.getAgent.mockResolvedValueOnce(savedAgent);
    await finish("success");
    expect(screen.getByText(enUS.agents.agentCreated)).toBeTruthy();
    mocks.toastError.mockClear();
    await exhaustRead(oldRead);
    expect(screen.getByText(enUS.agents.agentCreated)).toBeTruthy();
    expect(mocks.toastError).not.toHaveBeenCalled();
  });

  it("ignores read-back exhaustion after the page unmounts", async () => {
    const oldRead = deferred<Agent>();
    mocks.getAgent.mockReturnValueOnce(oldRead.promise);
    const view = await openSetup();
    await save();
    await finish("success");
    view.unmount();
    await exhaustRead(oldRead);
    expect(mocks.toastError).not.toHaveBeenCalled();
  });

  it("restores Save after current read-back exhaustion and confirms a retry", async () => {
    await openSetup();
    await save();
    await finish("success");
    await act(() => rs.advanceTimersByTimeAsync(4_000));
    expect(mocks.getAgent).toHaveBeenCalledTimes(5);
    expect(mocks.toastError).toHaveBeenCalledWith(
      enUS.agents.agentCreatedPendingRefresh,
    );
    expect(
      screen
        .getByRole("button", { name: enUS.agents.save })
        .hasAttribute("disabled"),
    ).toBe(false);
    mocks.getAgent.mockResolvedValueOnce(savedAgent);
    await save();
    await finish("success");
    expect(screen.getByText(enUS.agents.agentCreated)).toBeTruthy();
  });

  it.each(["rejected", "resolved"] as const)(
    "ignores a superseded Save send that later %s",
    async (outcome) => {
      const oldSend = deferred<void>();
      const oldRead = deferred<Agent>();
      await openSetup();
      mocks.sendMessage.mockReturnValueOnce(oldSend.promise);
      mocks.getAgent.mockReturnValueOnce(oldRead.promise);
      await save();
      await finish("success");
      await subsequentSetupError();
      await save();
      mocks.toastError.mockClear();
      mocks.toastSuccess.mockClear();
      await act(async () => {
        if (outcome === "rejected")
          oldSend.reject(new Error("old send failed"));
        else oldSend.resolve();
      });
      expect(
        screen
          .getByRole("button", { name: enUS.agents.saving })
          .hasAttribute("disabled"),
      ).toBe(true);
      expect(mocks.toastError).not.toHaveBeenCalled();
      expect(mocks.toastSuccess).not.toHaveBeenCalled();
      mocks.getAgent.mockResolvedValueOnce(savedAgent);
      await finish("success");
      expect(screen.getByText(enUS.agents.agentCreated)).toBeTruthy();
      await act(async () => {
        oldRead.resolve(savedAgent);
      });
    },
  );

  it("restores Save and reports a current send failure", async () => {
    await openSetup();
    mocks.sendMessage.mockRejectedValueOnce(new Error("save send failed"));
    await save();
    expect(mocks.toastError).toHaveBeenCalledWith("save send failed");
    expect(
      screen
        .getByRole("button", { name: enUS.agents.save })
        .hasAttribute("disabled"),
    ).toBe(false);
    expect(mocks.getAgent).not.toHaveBeenCalled();
  });
});
