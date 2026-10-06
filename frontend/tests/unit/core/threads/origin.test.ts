import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, test } from "@rstest/core";

import { enUS, zhCN } from "@/core/i18n";
import {
  DEERFLOW_ORIGIN_KEY,
  labelOfThreadOrigin,
  THREAD_ORIGIN_KINDS,
  threadOriginOf,
} from "@/core/threads/origin";
import {
  channelSourceOfThread,
  labelOfChannelProvider,
} from "@/core/threads/utils";

import { expectNoRawIdentifiers } from "../../helpers/readable";

const CONTRACT = JSON.parse(
  readFileSync(
    resolve(__dirname, "../../../../../contracts/thread_origin_contract.json"),
    "utf-8",
  ),
) as { version: number; key: string; kinds: string[] };

const thread = (metadata: Record<string, unknown>) => ({ metadata });

describe("threadOriginOf", () => {
  test("the frontend key and kinds equal the contract fixture", () => {
    expect(CONTRACT.key).toBe(DEERFLOW_ORIGIN_KEY);
    expect([...THREAD_ORIGIN_KINDS].sort()).toEqual([...CONTRACT.kinds].sort());
  });

  test("deerflow_origin wins over channel_source and the legacy task id", () => {
    expect(
      threadOriginOf(
        thread({
          deerflow_origin: { kind: "schedule" },
          channel_source: { type: "im_channel", provider: "feishu" },
          scheduled_task_id: "task-1",
        }),
      ),
    ).toEqual({ kind: "schedule" });
  });

  test("channel_source wins over the legacy scheduled task id", () => {
    expect(
      threadOriginOf(
        thread({
          channel_source: { type: "im_channel", provider: "Feishu" },
          scheduled_task_id: "task-1",
        }),
      ),
    ).toEqual({ kind: "im_channel", provider: "feishu" });
  });

  test("a legacy scheduled run thread reads as a scheduled run", () => {
    expect(threadOriginOf(thread({ scheduled_task_id: "task-1" }))).toEqual({
      kind: "schedule",
    });
  });

  test("a GitHub channel thread is a GitHub origin", () => {
    expect(
      threadOriginOf(
        thread({ channel_source: { type: "im_channel", provider: "github" } }),
      ),
    ).toEqual({ kind: "github", provider: "github" });
    expect(
      threadOriginOf(
        thread({ deerflow_origin: { kind: "github", provider: "github" } }),
      ),
    ).toEqual({ kind: "github", provider: "github" });
  });

  test("an extension origin keeps its namespace", () => {
    expect(
      threadOriginOf(
        thread({
          deerflow_origin: { kind: "extension", namespace: "acme.notes" },
        }),
      ),
    ).toEqual({ kind: "extension", namespace: "acme.notes" });
  });

  test("an unknown kind or a malformed value falls through", () => {
    expect(
      threadOriginOf(thread({ deerflow_origin: { kind: "browser" } })),
    ).toBeNull();
    expect(threadOriginOf(thread({ deerflow_origin: "schedule" }))).toBeNull();
    expect(
      threadOriginOf(
        thread({
          deerflow_origin: { kind: "im_channel" },
          channel_source: { type: "im_channel", provider: "slack" },
        }),
      ),
    ).toEqual({ kind: "im_channel", provider: "slack" });
    expect(threadOriginOf({ metadata: undefined })).toBeNull();
    expect(threadOriginOf(thread({}))).toBeNull();
  });
});

describe("origin labels", () => {
  test("each kind reads as its glossary label in English", () => {
    expect(labelOfThreadOrigin({ kind: "schedule" }, enUS)).toBe(
      "Scheduled run",
    );
    expect(
      labelOfThreadOrigin({ kind: "im_channel", provider: "feishu" }, enUS),
    ).toBe("From Feishu");
    expect(
      labelOfThreadOrigin({ kind: "github", provider: "github" }, enUS),
    ).toBe("From GitHub");
    expect(
      labelOfThreadOrigin({ kind: "extension", namespace: "x" }, enUS),
    ).toBe("From an extension");
    expect(labelOfThreadOrigin({ kind: "mcp_notification" }, enUS)).toBeNull();
    expect(labelOfThreadOrigin(null, enUS)).toBeNull();
  });

  test("Chinese labels use Chinese provider names, never the English ones", () => {
    const feishu = labelOfThreadOrigin(
      { kind: "im_channel", provider: "feishu" },
      zhCN,
    );
    const wecom = labelOfThreadOrigin(
      { kind: "im_channel", provider: "wecom" },
      zhCN,
    );
    expect(feishu).toBe("来自飞书");
    expect(wecom).toBe("来自企业微信");
    expect(feishu).not.toContain("Feishu");
    expect(wecom).not.toContain("WeCom");
    expect(
      labelOfThreadOrigin({ kind: "im_channel", provider: "slack" }, zhCN),
    ).toBe("来自 Slack");
    expect(labelOfThreadOrigin({ kind: "schedule" }, zhCN)).toBe("定时运行");
    expect(
      labelOfThreadOrigin({ kind: "github", provider: "github" }, zhCN),
    ).toBe("来自 GitHub");
    expect(
      labelOfThreadOrigin({ kind: "extension", namespace: null }, zhCN),
    ).toBe("来自扩展");
  });

  test("every known provider has a localized name in both locales", () => {
    const providers = Object.keys(enUS.threads.origin.providers);
    expect(Object.keys(zhCN.threads.origin.providers).sort()).toEqual(
      [...providers].sort(),
    );
    for (const provider of providers) {
      for (const t of [enUS, zhCN]) {
        const label = labelOfChannelProvider(provider, t);
        expect(label).not.toBe("");
        expectNoRawIdentifiers(label);
      }
    }
  });

  test("labelOfChannelProvider prefers translations, then English, then the id", () => {
    expect(labelOfChannelProvider("dingtalk", zhCN)).toBe("钉钉");
    expect(labelOfChannelProvider("dingtalk")).toBe("DingTalk");
    expect(labelOfChannelProvider("github")).toBe("GitHub");
    expect(labelOfChannelProvider("matrix", zhCN)).toBe("matrix");
    expect(labelOfChannelProvider("toString", zhCN)).toBe("toString");
  });

  test("channelSourceOfThread localizes its label when given translations", () => {
    const source = {
      channel_source: { type: "im_channel", provider: "wechat" },
    };
    expect(channelSourceOfThread(thread(source))?.label).toBe("WeChat");
    expect(channelSourceOfThread(thread(source), zhCN)?.label).toBe("微信");
  });
});
