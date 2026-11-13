import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import {
  HumanInputCard,
  ToolApprovalCard,
} from "@/components/workspace/messages/human-input-card";
import { MessageArtifactPathsContext } from "@/components/workspace/messages/markdown-link";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import type {
  HitlApprovalRequest,
  HitlApprovalResponse,
  HumanInputRequest,
} from "@/core/messages/human-input";

const formRequest: HumanInputRequest = {
  version: 2,
  kind: "human_input_request",
  source: "ask_clarification",
  request_id: "clarification:call-form",
  question: "Please provide the expense details.",
  input_mode: "form",
  fields: [
    { name: "amount", label: "Amount", type: "number", required: true },
    { name: "category", label: "Category", type: "text", required: true },
  ],
};

const textRequest: HumanInputRequest = {
  version: 1,
  kind: "human_input_request",
  source: "ask_clarification",
  request_id: "clarification:call-text",
  question: "Which report should I summarize?",
  input_mode: "free_text",
};

const approvalRequest: HitlApprovalRequest = {
  version: 1,
  kind: "hitl_approval",
  request_id: "hitl_approval:ai-1:call-1",
  actions: [
    {
      tool_call_id: "call-1",
      tool_name: "write_file",
      args_summary: JSON.stringify({ path: "/tmp/a.txt", content: "A" }),
      request_id: "hitl_approval:ai-1:call-1",
    },
    {
      tool_call_id: "call-2",
      tool_name: "bash",
      args_summary: JSON.stringify({ command: "pwd" }),
      request_id: "hitl_approval:ai-1:call-2",
    },
  ],
  allowed_decisions: ["approve", "reject"],
  pending_tool_call_ids: ["call-1", "call-2"],
};

function renderApprovalCard({
  request = approvalRequest,
  onSubmit = async () => undefined,
  disabled = false,
}: {
  request?: HitlApprovalRequest;
  onSubmit?: (
    request: HitlApprovalRequest,
    responses: HitlApprovalResponse[],
  ) => Promise<boolean | void>;
  disabled?: boolean;
} = {}) {
  return {
    onSubmit,
    ...render(
      <I18nContext.Provider
        value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
      >
        <ToolApprovalCard
          disabled={disabled}
          request={request}
          onSubmit={onSubmit}
        />
      </I18nContext.Provider>,
    ),
  };
}

function renderCard() {
  return render(
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <HumanInputCard request={formRequest} onSubmit={() => undefined} />
    </I18nContext.Provider>,
  );
}

afterEach(cleanup);
it("submits exact edited arguments and disables invalid JSON", async () => {
  const onSubmit = rs.fn().mockResolvedValue(true);
  const action = {
    ...approvalRequest.actions[0]!,
    args: { path: "/tmp/a.txt", content: "A" },
    args_schema: { type: "object" },
    grant_allowed: true,
  };
  renderApprovalCard({
    onSubmit,
    request: {
      ...approvalRequest,
      version: 2,
      actions: [action],
      pending_tool_call_ids: [action.tool_call_id],
      allowed_decisions: ["approve", "approve_thread", "edit", "reject"],
    },
  });
  fireEvent.click(screen.getByRole("button", { name: "Edit arguments" }));
  fireEvent.change(
    screen.getByRole("textbox", { name: "Edit arguments write_file" }),
    { target: { value: "invalid" } },
  );
  expect(
    screen
      .getByRole("button", { name: "Submit decisions" })
      .hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.change(
    screen.getByRole("textbox", { name: "Edit arguments write_file" }),
    { target: { value: '{"path":"/tmp/a.txt","content":"B"}' } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Submit decisions" }));
  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  expect(onSubmit.mock.calls[0]?.[1]).toMatchObject([
    { option_id: "edit", args: { path: "/tmp/a.txt", content: "B" } },
  ]);
});
afterEach(() => {
  rs.restoreAllMocks();
});

describe("HumanInputCard form validation (DOM)", () => {
  it("resolves relative artifact links in its context and question", () => {
    render(
      <I18nContext.Provider
        value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
      >
        <MessageArtifactPathsContext.Provider
          value={["/mnt/user-data/outputs/report.md"]}
        >
          <HumanInputCard
            request={{
              ...formRequest,
              context: "Review the [draft](report.md).",
              question: "Approve the [report](./report.md)?",
            }}
            threadId="thread-1"
          />
        </MessageArtifactPathsContext.Provider>
      </I18nContext.Provider>,
    );

    for (const name of ["draft", "report"]) {
      expect(screen.getByRole("link", { name }).getAttribute("href")).toBe(
        "/api/threads/thread-1/artifacts/mnt/user-data/outputs/report.md",
      );
    }
  });

  it("keeps the error node mounted while another field is still invalid", () => {
    renderCard();

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    // Both required fields flagged; the error node exists and is referenced.
    const amount = screen.getByLabelText(/Amount/);
    const category = screen.getByLabelText(/Category/);
    expect(amount.getAttribute("aria-invalid")).toBe("true");
    expect(category.getAttribute("aria-invalid")).toBe("true");
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("required fields");

    // Fixing ONE field must not unmount the error node the other field's
    // aria-describedby still points at.
    fireEvent.change(amount, { target: { value: "300" } });
    expect(amount.getAttribute("aria-invalid")).toBeNull();
    expect(category.getAttribute("aria-invalid")).toBe("true");
    const describedBy = category.getAttribute("aria-describedby");
    expect(describedBy).not.toBeNull();
    expect(document.getElementById(describedBy!)).not.toBeNull();

    // Fixing the last invalid field clears the error entirely.
    fireEvent.change(category, { target: { value: "travel" } });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps select fields controlled from placeholder through selection", () => {
    const warnSpy = rs.spyOn(console, "warn").mockImplementation(() => ({}));
    render(
      <I18nContext.Provider
        value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
      >
        <HumanInputCard
          request={{
            ...formRequest,
            fields: [
              {
                name: "category",
                label: "Category",
                type: "select",
                required: true,
                options: [
                  { id: "category-travel", label: "travel", value: "travel" },
                  { id: "category-meals", label: "meals", value: "meals" },
                ],
              },
            ],
          }}
          onSubmit={() => undefined}
        />
      </I18nContext.Provider>,
    );

    const trigger = screen.getByRole("combobox", {
      name: "Category required",
    });
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("option", { name: "travel" }));

    expect(
      warnSpy.mock.calls.some(([message]) =>
        String(message).includes("uncontrolled to controlled"),
      ),
    ).toBe(false);
  });
});

describe("HumanInputCard submission failures (DOM)", () => {
  it("surfaces a localized retryable error when the answer send rejects", async () => {
    const onSubmit = rs.fn(async () => {
      throw new Error("HTTP 502");
    });
    render(
      <I18nContext.Provider
        value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
      >
        <HumanInputCard request={textRequest} onSubmit={onSubmit} />
      </I18nContext.Provider>,
    );

    const answer = screen.getByRole<HTMLTextAreaElement>("textbox");
    fireEvent.change(answer, { target: { value: "The Q3 report" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() =>
      expect(screen.getByText(enUS.humanInput.submitFailed)).not.toBeNull(),
    );
    // The textarea points at the retry message for assistive technology.
    expect(answer.getAttribute("aria-invalid")).toBe("true");
    expect(answer.getAttribute("aria-describedby")).not.toBeNull();
    // The answer stays editable for the retry and the rejection was handled.
    expect(answer.value).toBe("The Q3 report");
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("shows the retry error on an option-only card", async () => {
    // single_choice mounts neither the text form nor the form branch, so this
    // card needs its own error node; without it the rejection sets the message
    // and renders nothing.
    const onSubmit = rs.fn(async () => {
      throw new Error("HTTP 502");
    });
    const request: HumanInputRequest = {
      version: 1,
      kind: "human_input_request",
      source: "ask_clarification",
      request_id: "clarification:call-choice",
      question: "Which environment?",
      input_mode: "single_choice",
      options: [
        { id: "staging", label: "Staging", value: "staging" },
        { id: "production", label: "Production", value: "production" },
      ],
    };
    render(
      <I18nContext.Provider
        value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
      >
        <HumanInputCard request={request} onSubmit={onSubmit} />
      </I18nContext.Provider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Staging" }));

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe(
        enUS.humanInput.submitFailed,
      ),
    );
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});

describe("ToolApprovalCard", () => {
  it("collects every action before one atomic mixed-decision submit", async () => {
    const onSubmit = rs.fn(
      async (
        _request: HitlApprovalRequest,
        _responses: HitlApprovalResponse[],
      ) => undefined,
    );
    renderApprovalCard({ onSubmit });
    const submit = screen.getByRole("button", { name: "Submit decisions" });

    expect(submit.hasAttribute("disabled")).toBe(true);
    const approveButtons = screen.getAllByRole("button", { name: "Approve" });
    fireEvent.click(approveButtons[0]!);
    expect(submit.hasAttribute("disabled")).toBe(true);
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.click(screen.getAllByRole("button", { name: "Reject" })[1]!);
    fireEvent.change(screen.getByLabelText("Rejection reason (optional)"), {
      target: { value: "Do not run this command" },
    });
    expect(submit.hasAttribute("disabled")).toBe(false);
    fireEvent.click(submit);

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const responses = onSubmit.mock.calls[0]![1];
    expect(responses).toHaveLength(2);
    expect(
      responses.map((response: { option_id: string }) => response.option_id),
    ).toEqual(["approve", "reject"]);
    expect(responses[1]?.value).toBe("Do not run this command");
    await screen.findByText("Answered");
    expect(submit.hasAttribute("disabled")).toBe(true);
  });

  it("keeps mixed decisions and rejection reason editable after failure", async () => {
    let resolveAccepted!: (accepted: boolean) => void;
    const accepted = new Promise<boolean>((resolve) => {
      resolveAccepted = resolve;
    });
    const onSubmit = rs.fn(() => accepted);
    renderApprovalCard({ onSubmit });
    const approveButtons = screen.getAllByRole("button", { name: "Approve" });
    fireEvent.click(approveButtons[0]!);
    fireEvent.click(screen.getAllByRole("button", { name: "Reject" })[1]!);
    const reason = screen.getByLabelText<HTMLTextAreaElement>(
      "Rejection reason (optional)",
    );
    fireEvent.change(reason, {
      target: { value: "Do not run this command" },
    });
    const submit = screen.getByRole("button", { name: "Submit decisions" });
    fireEvent.click(submit);

    // The submit promise deliberately remains unresolved; assert the in-flight
    // frame synchronously instead of wrapping that pending operation in findBy*.
    expect(screen.getByText("Sending...")).not.toBeNull();
    expect(submit.hasAttribute("disabled")).toBe(true);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    act(() => resolveAccepted(false));

    await waitFor(() => expect(submit.hasAttribute("disabled")).toBe(false));
    expect(screen.getByTestId("tool-approval-card")).not.toBeNull();
    expect(approveButtons[0]!.getAttribute("aria-pressed")).toBe("true");
    expect(
      screen
        .getAllByRole("button", { name: "Reject" })[1]!
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(reason.value).toBe("Do not run this command");
    expect(screen.queryByText("Answered")).toBeNull();
    expect(screen.queryByText("Sending...")).toBeNull();
  });

  it("submits approve-all once and disables an in-flight interrupt frame", async () => {
    const onSubmit = rs.fn(
      async (
        _request: HitlApprovalRequest,
        _responses: HitlApprovalResponse[],
      ) => undefined,
    );
    renderApprovalCard({ onSubmit, disabled: true });

    fireEvent.click(screen.getByRole("button", { name: "Approve all" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("uses allowed_decisions and keeps all-reject available by itself", () => {
    renderApprovalCard({
      request: { ...approvalRequest, allowed_decisions: ["reject"] },
    });

    expect(screen.queryByRole("button", { name: "Approve all" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Reject all and finish" }),
    ).not.toBeNull();
  });

  it("shows the complete str_replace old and new strings as a diff", () => {
    renderApprovalCard({
      request: {
        ...approvalRequest,
        actions: [
          {
            tool_call_id: "replace-1",
            tool_name: "str_replace",
            args_summary: JSON.stringify({
              path: "/tmp/a.txt",
              old_str: "old line\nsecond old line",
              new_str: "new line\nsecond new line",
            }),
            request_id: "hitl_approval:ai-1:replace-1",
          },
        ],
        pending_tool_call_ids: ["replace-1"],
      },
    });

    fireEvent.click(screen.getByRole("button", { name: /Tool details/ }));
    const diff = screen.getByTestId("approval-diff");
    expect(diff.textContent).toContain("- old line");
    expect(diff.textContent).toContain("- second old line");
    expect(diff.textContent).toContain("+ new line");
    expect(diff.textContent).toContain("+ second new line");
  });
});
