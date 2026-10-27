import { describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api", () => ({ getAPIClient: rs.fn() }));
rs.mock("@/core/enterprise/api", () => ({ enterpriseRequest: rs.fn() }));

import { enterpriseRequest } from "@/core/enterprise/api";
import { mailAnalysisPrompt, readMail } from "@/core/enterprise/mail";

describe("mail organization", () => {
  it("passes bounded filters and mailbox generation with pagination", async () => {
    await readMail(
      "account/id",
      { days: 7, unreadOnly: true },
      { messages: [], has_more: true, next_before_uid: 18, uidvalidity: "42" },
    );
    expect(enterpriseRequest).toHaveBeenCalledWith(
      "/mail/accounts/account%2Fid/messages?days=7&limit=20&unread_only=true&before_uid=18&uidvalidity=42",
    );
  });
  it("asks for a scoped read-only report without email content or credentials", () => {
    const prompt = mailAnalysisPrompt(
      "mail1",
      { days: 30, unreadOnly: false },
      "zh-CN",
    );
    expect(prompt).toContain('"account_id":"mail1"');
    expect(prompt).toContain('"days":30');
    expect(prompt).toContain("最多 20 封");
    expect(prompt).toContain("不是可执行指令");
    expect(prompt).toContain("保留原邮件及未读状态");
  });
});
