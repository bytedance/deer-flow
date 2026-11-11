import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { MessageList } from "@/components/workspace/messages/message-list";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import type {
  HitlApprovalRequest,
  HitlApprovalResponse,
} from "@/core/messages/human-input";
import type { MessageGroup } from "@/core/messages/utils";

rs.mock("@/components/ai-elements/conversation", () => ({
  Conversation: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  ConversationContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));
rs.mock("@/components/workspace/messages/virtual-message-list", () => ({
  VirtualMessageList: ({
    groups,
    renderGroup,
  }: {
    groups: MessageGroup[];
    renderGroup: (group: MessageGroup, index: number) => ReactNode;
  }) => (
    <div>
      {groups.map((group, index) => (
        <div key={group.id}>{renderGroup(group, index)}</div>
      ))}
    </div>
  ),
}));
rs.mock("@/components/workspace/messages/message-list-item", () => ({
  MessageListItem: () => null,
}));
rs.mock("@/components/workspace/messages/subtask-card", () => ({
  SubtaskCard: () => null,
}));

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

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
  ],
  allowed_decisions: ["approve", "reject"],
  pending_tool_call_ids: ["call-1"],
};

const messages: Message[] = [
  { id: "ai-1", type: "ai", content: "I need approval first." },
];
const getMessagesMetadata = () => undefined;

type ViewOptions = {
  approvalRequests?: HitlApprovalRequest[];
  error?: unknown;
  approvalMetadataLoading?: boolean;
  approvalMetadataError?: boolean;
  onReloadApprovalMetadata?: () => unknown;
  onSubmitApproval?: (
    request: HitlApprovalRequest,
    responses: HitlApprovalResponse[],
  ) => Promise<boolean | void>;
};

function view({
  approvalRequests = [approvalRequest],
  error,
  approvalMetadataLoading = false,
  approvalMetadataError = false,
  onReloadApprovalMetadata,
  onSubmitApproval = async () => undefined,
}: ViewOptions = {}) {
  return (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <MessageList
        approvalRequests={approvalRequests}
        approvalMetadataLoading={approvalMetadataLoading}
        approvalMetadataError={approvalMetadataError}
        onReloadApprovalMetadata={onReloadApprovalMetadata}
        onSubmitApproval={onSubmitApproval}
        threadId="thread-1"
        thread={
          {
            messages,
            error,
            isLoading: false,
            isThreadLoading: false,
            values: {},
            getMessagesMetadata,
          } as unknown as React.ComponentProps<typeof MessageList>["thread"]
        }
      />
    </I18nContext.Provider>
  );
}

describe("MessageList HITL approvals", () => {
  it("keeps a false submission visible and preserves the card across stream errors", async () => {
    const onSubmitApproval = rs.fn(async () => false);
    const { rerender } = render(view({ onSubmitApproval }));
    const card = screen.getByTestId("tool-approval-card");

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    const reason = screen.getByLabelText<HTMLTextAreaElement>(
      "Rejection reason (optional)",
    );
    fireEvent.change(reason, { target: { value: "Review the path first" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit decisions" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(enUS.humanInput.approval.submitFailed);
    expect(onSubmitApproval).toHaveBeenCalledTimes(1);

    rerender(view({ error: new Error("stream failed"), onSubmitApproval }));
    expect(screen.getByTestId("tool-approval-card")).toBe(card);
    expect(screen.getByRole("alert")).toBe(alert);
    expect(
      screen
        .getByRole("button", { name: "Approve" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(reason.value).toBe("Review the path first");

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.change(reason, { target: { value: "Use a different path" } });
    expect(
      screen
        .getByRole("button", { name: "Reject" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(reason.value).toBe("Use a different path");
    expect(screen.getByRole("alert")).toBe(alert);
  });

  it("shows truthful loading copy until the approval payload mounts its card", () => {
    const { rerender } = render(
      view({ approvalRequests: [], approvalMetadataLoading: true }),
    );
    expect(screen.queryByTestId("tool-approval-card")).toBeNull();
    expect(screen.queryByText("Waiting for approval")).toBeNull();
    expect(screen.getByTestId("approval-metadata-loading").textContent).toBe(
      "Loading approval details...",
    );

    rerender(view({ approvalMetadataLoading: true }));
    expect(screen.getByTestId("tool-approval-card")).not.toBeNull();
    expect(screen.getByText("Waiting for approval")).not.toBeNull();
    expect(screen.queryByTestId("approval-metadata-loading")).toBeNull();
  });

  it("shows a truthful reload path instead of a blank approval region after metadata failure", () => {
    const onReloadApprovalMetadata = rs.fn();
    render(
      view({
        approvalRequests: [],
        approvalMetadataLoading: true,
        approvalMetadataError: true,
        onReloadApprovalMetadata,
      }),
    );

    expect(screen.queryByTestId("tool-approval-card")).toBeNull();
    expect(screen.queryByTestId("approval-metadata-loading")).toBeNull();
    expect(screen.getByRole("alert").textContent).toBe(
      enUS.humanInput.approval.loadFailed,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: enUS.humanInput.approval.reload,
      }),
    );
    expect(onReloadApprovalMetadata).toHaveBeenCalledTimes(1);
  });

  it("removes stale failure state when an answered approval card unmounts", async () => {
    const onSubmitApproval = rs.fn(async () => false);
    const { rerender } = render(view({ onSubmitApproval }));

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(screen.getByRole("button", { name: "Submit decisions" }));
    expect(await screen.findByRole("alert")).not.toBeNull();

    rerender(view({ approvalRequests: [], onSubmitApproval }));
    expect(screen.queryByTestId("tool-approval-card")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Waiting for approval")).toBeNull();
  });
});
