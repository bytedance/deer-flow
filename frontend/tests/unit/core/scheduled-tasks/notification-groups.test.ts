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

  test("includes connected QQ and WeCom group bindings while excluding private or unsupported bindings", () => {
    const qqGroup: ChannelConnection = {
      id: "qq-group",
      provider: "qq",
      status: "connected",
      workspace_id: "app1:group:group-openid",
      scopes: [],
      metadata: { chat_type: "group", group_openid: "group-openid" },
    };
    const wecomGroup: ChannelConnection = {
      id: "wecom-group",
      provider: "wecom",
      status: "connected",
      workspace_id: "bot1:group:wr_chat_1",
      scopes: [],
      metadata: { aibotid: "bot1", chattype: "group", chatid: "wr_chat_1" },
    };
    const qqPrivate: ChannelConnection = {
      id: "qq-private",
      provider: "qq",
      status: "connected",
      workspace_id: "app1:c2c",
      scopes: [],
      metadata: { chat_type: "c2c" },
    };
    const wechatGroup: ChannelConnection = {
      id: "wechat-group",
      provider: "wechat",
      status: "connected",
      workspace_id: "group:wx_1",
      scopes: [],
      metadata: { chat_type: "group", chat_id: "group:wx_1" },
    };
    const qqGroup2: ChannelConnection = {
      ...qqGroup,
      id: "qq-group-2",
      workspace_id: "app1:group:group-openid-2",
      metadata: { chat_type: "group", group_openid: "group-openid-2" },
    };
    const wecomGroup2: ChannelConnection = {
      ...wecomGroup,
      id: "wecom-group-2",
      workspace_id: "bot1:group:wr_chat_2",
      metadata: { aibotid: "bot1", chattype: "group", chatid: "wr_chat_2" },
    };
    expect(
      feishuNotificationGroups([
        qqGroup,
        qqGroup2,
        wecomGroup,
        wecomGroup2,
        qqPrivate,
        wechatGroup,
      ]),
    ).toEqual([qqGroup, qqGroup2, wecomGroup, wecomGroup2]);
    expect(notificationGroupName(qqGroup)).toBeNull();
    expect(notificationGroupName(qqGroup2)).toBeNull();
    expect(notificationGroupName(wecomGroup)).toBeNull();
    expect(notificationGroupName(wecomGroup2)).toBeNull();
    expect(
      notificationGroupName({ ...qqGroup, workspace_name: "Release team" }),
    ).toBe("Release team");
    expect(
      notificationGroupName({ ...qqGroup2, workspace_name: "Support team" }),
    ).toBe("Support team");
    expect(
      notificationGroupName({
        ...qqGroup,
        workspace_name: "QQ group (group-openid)",
      }),
    ).toBeNull();
    expect(
      notificationGroupName({
        ...wecomGroup,
        workspace_name: "WeCom group (wr_chat_1)",
      }),
    ).toBeNull();
    expect(
      notificationGroupName({ ...wecomGroup, workspace_name: "Ops War Room" }),
    ).toBe("Ops War Room");
  });
});
