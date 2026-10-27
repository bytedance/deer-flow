import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import { OutboxEditor } from "@/app/workspace/enterprise/mail-outbox";
import {
  createMailDraft,
  getMailDraft,
  listMailDrafts,
  sendMailDraft,
  type MailDraft,
} from "@/core/enterprise/mail-outbox";
import { I18nProvider } from "@/core/i18n/context";

rs.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));
rs.mock("@/core/enterprise/mail-outbox", () => ({
  createMailDraft: rs.fn(),
  getMailDraft: rs.fn(),
  listMailDrafts: rs.fn(),
  sendMailDraft: rs.fn(),
  discardMailDraft: rs.fn(),
  parseMailRecipients: (value: string) =>
    value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
}));

const draft: MailDraft = {
  id: "draft1",
  account_id: "mail1",
  sender: "alice@example.com",
  to: ["bob@example.com"],
  cc: [],
  subject: "Project update",
  body: "Please review <img src=x onerror=alert(1)>",
  status: "draft",
  message_id: "<draft1@example.com>",
  created_at: "2026-10-20 01:00:00",
  result: null,
};
beforeEach(() => {
  rs.resetAllMocks();
  document.cookie = "locale=en-US; path=/";
  rs.mocked(listMailDrafts).mockResolvedValue({ drafts: [] });
  rs.mocked(getMailDraft).mockResolvedValue(draft);
  rs.mocked(createMailDraft).mockResolvedValue(draft);
});
afterEach(cleanup);
function mount(initialId = "") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale="en-US">
        <OutboxEditor
          userId="alice"
          accountId="mail1"
          accounts={[
            { id: "mail1", name: "Office", provider: "alimail", enabled: true },
          ]}
          initialId={initialId}
        />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("mail outbox", () => {
  it("saves a preview without sending, then confirms the exact draft only once", async () => {
    let finish!: (value: MailDraft) => void;
    rs.mocked(sendMailDraft).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    mount();
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", {
            name: "Compose email",
          })
          .hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Compose email" }));
    fireEvent.change(screen.getByLabelText("To", { exact: true }), {
      target: { value: "bob@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Subject"), {
      target: { value: "Project update" },
    });
    fireEvent.change(screen.getByLabelText("Body"), {
      target: { value: draft.body },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save and preview" }));
    const preview = await screen.findByRole("region", {
      name: "Email preview",
    });
    expect(sendMailDraft).not.toHaveBeenCalled();
    expect(preview.querySelector("img")).toBeNull();
    const send = within(preview).getByRole("button", {
      name: "Confirm and send",
    });
    expect(send.hasAttribute("disabled")).toBe(true);
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "I have checked the recipients and content",
      }),
    );
    fireEvent.click(send);
    fireEvent.click(send);
    await waitFor(() => expect(sendMailDraft).toHaveBeenCalledTimes(1));
    expect(sendMailDraft).toHaveBeenCalledWith("draft1");
    finish({
      ...draft,
      status: "sent",
      result: { error: null, accepted: draft.to, refused: [] },
    });
    await screen.findByText("Submitted", { exact: true });
  });

  it("does not retry an ambiguous submission and permits read-only status refresh", async () => {
    rs.mocked(sendMailDraft).mockRejectedValue(
      new Error("network disconnected"),
    );
    mount("draft1");
    await screen.findByRole("region", { name: "Email preview" });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Confirm and send" }));
    await screen.findByText(/No submission result received/);
    expect(sendMailDraft).toHaveBeenCalledTimes(1);
    expect(
      screen
        .getByRole("button", {
          name: "Confirm and send",
        })
        .hasAttribute("disabled"),
    ).toBe(true);
    rs.mocked(getMailDraft).mockResolvedValue({ ...draft, status: "sent" });
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    await screen.findByText("Submitted", { exact: true });
    expect(sendMailDraft).toHaveBeenCalledTimes(1);
  });

  it("keeps sending disabled without the separate compose grant", async () => {
    rs.mocked(listMailDrafts).mockRejectedValue(new Error("access_denied"));
    mount();
    await screen.findByText(/grant enterprise_mail_compose/);
    expect(
      screen
        .getByRole("button", {
          name: "Compose email",
        })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(createMailDraft).not.toHaveBeenCalled();
    expect(sendMailDraft).not.toHaveBeenCalled();
  });
});
