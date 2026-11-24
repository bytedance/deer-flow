import { describe, expect, it } from "@rstest/core";

import {
  createHitlApprovalResponses,
  parseHitlApprovalRequest,
} from "@/core/messages/human-input";

describe("tool approval v2", () => {
  it("preserves the exact editable operation and live child routing", () => {
    const request = parseHitlApprovalRequest({
      kind: "hitl_approval",
      version: 2,
      request_id: "review",
      transport: "live",
      run_id: "run",
      actions: [
        {
          request_id: "review",
          tool_call_id: "call",
          tool_name: "send_email",
          args_summary: { recipient: "a@example.test" },
          args: { recipient: "a@example.test" },
          args_schema: { type: "object" },
          fingerprint: "fingerprint",
          grant_allowed: true,
        },
      ],
      allowed_decisions: ["approve", "approve_thread", "reject", "edit"],
      pending_tool_call_ids: ["call"],
    });
    expect(request?.transport).toBe("live");
    expect(request?.actions[0]?.args).toEqual({ recipient: "a@example.test" });
    expect(
      createHitlApprovalResponses(request!, { call: "edit" }, "", {
        call: { recipient: "b@example.test" },
      })?.[0]?.args,
    ).toEqual({ recipient: "b@example.test" });
  });

  it("does not accept malformed live routing", () => {
    expect(
      parseHitlApprovalRequest({
        kind: "hitl_approval",
        version: 2,
        transport: "live",
      }),
    ).toBeNull();
  });
});
