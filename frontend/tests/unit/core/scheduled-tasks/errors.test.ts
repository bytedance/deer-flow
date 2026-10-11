import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "@rstest/core";

import {
  parseGatewayApiError,
  UnauthorizedError,
  type GatewayApiError,
} from "@/core/api/errors";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import {
  describeScheduledTaskError,
  SCHEDULED_TASK_ERROR_KEYS,
  shouldReportScheduledTaskError,
} from "@/core/scheduled-tasks/errors";

type ErrorsContract = { ui_codes: string[]; agent_only_codes: string[] };

const CONTRACT = JSON.parse(
  readFileSync(
    resolve(
      __dirname,
      "../../../../../contracts/scheduled_task_errors_contract.json",
    ),
    "utf-8",
  ),
) as ErrorsContract;

const CJK = /[一-鿿]/;

function coded(
  code: string,
  params: Record<string, unknown> = {},
  status = 422,
  message = `server text for ${code}`,
): GatewayApiError {
  return parseGatewayApiError(
    { detail: { code, message, params } },
    status,
    "fallback",
  );
}

describe("scheduled-task error copy", () => {
  it("maps every UI contract code, and only those", () => {
    expect(Object.keys(SCHEDULED_TASK_ERROR_KEYS).sort()).toEqual(
      [...CONTRACT.ui_codes].sort(),
    );
    for (const code of CONTRACT.agent_only_codes) {
      expect(SCHEDULED_TASK_ERROR_KEYS[code]).toBeUndefined();
    }
  });

  it.each([
    ["en-US", enUS],
    ["zh-CN", zhCN],
  ] as const)("every UI code has non-empty %s copy", (locale, translations) => {
    for (const code of CONTRACT.ui_codes) {
      const params =
        code === "limits_exhausted"
          ? { limit: "max_runs", used: 5, max_runs: 5, end_at: null }
          : {};
      const { message } = describeScheduledTaskError(
        coded(code, params),
        translations,
        { locale, timeZone: "Asia/Shanghai" },
      );
      expect(message.length).toBeGreaterThan(0);
      expect(message).not.toBe(translations.scheduledTasks.apiErrors.generic);
      expect(message).not.toContain(`server text for ${code}`);
      if (locale === "zh-CN") {
        expect(message).toMatch(CJK);
      }
    }
  });

  it("fills params into the localized text", () => {
    expect(
      describeScheduledTaskError(
        coded("interval_too_short", { min_seconds: 60 }),
        enUS,
      ).message,
    ).toBe("Choose an interval of at least 60 seconds.");
    expect(
      describeScheduledTaskError(
        coded("task_quota_exceeded", { limit: 20 }, 409),
        zhCN,
      ).message,
    ).toBe(
      "你已有 20 个在对话中创建的任务（含已暂停的），删除一些后才能继续创建。",
    );
    expect(
      describeScheduledTaskError(
        coded("max_runs_not_above_used", { used: 4 }),
        enUS,
      ).message,
    ).toBe("The run limit must be more than the 4 runs already used.");
  });

  it("picks the limits_exhausted copy by limit and formats the end time", () => {
    expect(
      describeScheduledTaskError(
        coded(
          "limits_exhausted",
          { limit: "max_runs", used: 5, max_runs: 5, end_at: null },
          409,
        ),
        enUS,
      ).message,
    ).toBe("All 5 automatic runs are used. Raise the limit to resume.");
    const end = describeScheduledTaskError(
      coded(
        "limits_exhausted",
        {
          limit: "end_at",
          used: 2,
          max_runs: null,
          end_at: "2026-10-05T10:00:00+00:00",
        },
        409,
      ),
      zhCN,
      {
        locale: "zh-CN",
        timeZone: "Asia/Shanghai",
        now: new Date("2026-10-06T04:00:00Z"),
      },
    ).message;
    expect(end).toBe(
      "结束时间 昨天 18:00 已过，设置更晚的结束时间后才能恢复。",
    );
    expect(end).not.toContain("2026-10-05T");
  });

  it("shows the generic copy with details for an unknown code", () => {
    expect(
      describeScheduledTaskError(
        coded("future_code", {}, 409, "Something new"),
        enUS,
      ),
    ).toEqual({ message: "Something went wrong.", details: "Something new" });
  });

  it("maps FastAPI's list detail to invalidRequest", () => {
    const error = parseGatewayApiError(
      { detail: [{ msg: "Input should be a valid integer" }] },
      422,
      "fallback",
    );
    expect(describeScheduledTaskError(error, enUS)).toEqual({
      message: "Some fields are invalid.",
      details: "Input should be a valid integer",
    });
  });

  it("maps a 403 string detail from the permission decorator to permissionDenied", () => {
    const error = parseGatewayApiError(
      { detail: "Permission denied: threads:write" },
      403,
      "fallback",
    );
    expect(describeScheduledTaskError(error, zhCN).message).toBe(
      "你没有执行此操作的权限。",
    );
    expect(describeScheduledTaskError(error, enUS).message).toBe(
      "You don't have permission to do this.",
    );
  });

  it("keeps a network failure generic with its text as details", () => {
    expect(
      describeScheduledTaskError(new TypeError("Failed to fetch"), enUS),
    ).toEqual({ message: "Something went wrong.", details: "Failed to fetch" });
  });

  it("does not report a 401 that already redirected to login", () => {
    expect(shouldReportScheduledTaskError(new UnauthorizedError())).toBe(false);
    expect(shouldReportScheduledTaskError(coded("task_running"))).toBe(true);
  });
});
