import { enterpriseRequest } from "./api";

export type MailDraftInput = {
  account_id: string;
  to: string[];
  cc: string[];
  subject: string;
  body: string;
};
export type MailDraft = MailDraftInput & {
  id: string;
  sender: string;
  status:
    | "draft"
    | "sending"
    | "sent"
    | "partial"
    | "failed"
    | "unknown"
    | "discarded";
  message_id: string;
  created_at: string;
  result: {
    error: string | null;
    accepted: string[];
    refused: string[];
  } | null;
};
export const listMailDrafts = () =>
  enterpriseRequest<{ drafts: MailDraft[] }>("/mail/drafts");
export const getMailDraft = (id: string) =>
  enterpriseRequest<MailDraft>(`/mail/drafts/${encodeURIComponent(id)}`);
export const createMailDraft = (input: MailDraftInput) =>
  enterpriseRequest<MailDraft>("/mail/drafts", input);
export const sendMailDraft = (id: string) =>
  enterpriseRequest<MailDraft>(`/mail/drafts/${encodeURIComponent(id)}/send`, {
    confirmed: true,
  });
export const discardMailDraft = (id: string) =>
  enterpriseRequest<MailDraft>(
    `/mail/drafts/${encodeURIComponent(id)}`,
    undefined,
    "DELETE",
  );
export function parseMailRecipients(value: string) {
  return value
    .split(/[,;，；\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}
