import { describe, expect, test } from "@rstest/core";

import type { ChannelConnection } from "@/core/channels/types";
import {
  feishuNotificationGroups,
  notificationGroupName,
} from "@/core/scheduled-tasks/notification-groups";

const group: ChannelConnection = {
  id: "binding",
  provider: "feishu",
  status: "connected",
  workspace_id: "oc_group",
  workspace_name: "Project review",
  scopes: [],
  metadata: { chat_id: "oc_group", chat_type: "group" },
};

describe("additional Feishu notification groups", () => {
  test.each([
    { provider: "slack" },
    { status: "revoked" },
    { status: "pending" },
    { metadata: { chat_id: "oc_group", chat_type: "p2p" } },
    { metadata: { chat_id: "different-chat", chat_type: "group" } },
    { metadata: { chat_type: "group" } },
    { workspace_id: "" },
    { workspace_id: null },
  ])(
    "excludes bindings outside the trusted connected group route: %j",
    (overrides) => {
      expect(
        feishuNotificationGroups([{ ...group, ...overrides }, group]),
      ).toEqual([group]);
    },
  );

  test("keeps an unnamed connected group distinguishable from a missing binding without inventing a name", () => {
    const unnamed = { ...group, workspace_name: "  " };
    expect(feishuNotificationGroups([unnamed])).toEqual([unnamed]);
    expect(notificationGroupName(unnamed)).toBeNull();
    expect(notificationGroupName(undefined)).toBeNull();
    expect(
      notificationGroupName({ ...group, workspace_name: "  项目会议  " }),
    ).toBe("项目会议");
  });
});
