# Enterprise connections

`/workspace/enterprise` contains two sections: **WeCom groups** and **Alibaba
enterprise mail**. WeCom uses a group robot webhook for outbound text messages.
The existing WeCom intelligent-bot channel remains the conversational entry point;
its Bot ID/Secret and the group webhook are different credentials.

## Setup and use

1. Configure the tool in root `config.yaml`:

   ```yaml
   tools:
     - name: enterprise_messaging
       group: enterprise
       use: deerflow.integrations.enterprise.tools:enterprise_messaging
   ```

2. Enable `scheduler.enabled` to use scheduled messages. Restart Gateway after
   installing this module. It reuses the normal Gateway agent-run lifecycle.
3. With the enterprise authorization provider, grant users/groups the exact
   `tool:enterprise_messaging` permission in Settings → Tools. Administrators
   have access. This integration is not added to the default tool allowlist.
4. Open **Enterprise connections → Bind group** and enter a name and the WeCom
   group robot webhook URL. Connections are private to the signed-in user.
5. Send or schedule messages in chat, for example:
   “Every weekday at 9am, send Please submit your report to Operations.”
   The agent lists your targets and uses the returned ID; ambiguous names/times
   must be clarified. Manage/pause/delete the resulting job under Scheduled tasks.

The chat tool supports immediate delivery, one-time delivery and five-field cron
with an explicit IANA timezone. Messages are fixed text, at most 2048 UTF-8 bytes. The server must
remain running and have outbound access to `qyapi.weixin.qq.com`.

## Delivery semantics

- `sent` means WeCom returned `errcode=0`; it is not a read receipt.
- `failed` means the provider rejected the request. `unknown` means acceptance
  could not be established (including timeout). Neither is automatically retried.
- A process crash during sending can leave `sending`: verify the group before
  making a new request. A repeated request never resends the same receipt.
- The chat tool derives its idempotency key from the server run ID and message payload.
  Identical calls in a run are deduplicated. A new run is a new send request.
- The local guard allows at most 20 attempts per destination per minute. WeCom
  also enforces its own limits, including when a webhook is used elsewhere.
- Scheduled messages run through the regular agent using the authorized tool;
  model availability and permission changes can prevent delivery. Task execution
  status is not a delivery receipt: check the tool's returned delivery status and
  verify the group when the result is unknown.
- Unbinding a group removes its credential. Existing schedules remain visible
  and will fail to send until replaced; stop them on the Scheduled tasks page.

## Storage and extension boundary

The single-node store uses `enterprise_targets` and `enterprise_deliveries` inside
the existing Gateway-private security `users.db`; the same `master.key` encrypts
credentials, with user and target IDs bound into the ciphertext. Back up both.
Neither file belongs in sandbox mounts. This private store follows the existing
security-store schema initialization, not the application ORM/Alembic database.
All storage and crypto operations run in worker threads. Multi-instance scheduler
deployments are rejected until this store has a shared database implementation.

`integrations/enterprise/providers.py` owns the provider registry and transport
contract; `store.py` owns identities, encrypted credentials and durable receipts;
`service.py` owns sending and schedule construction. The session-only REST router
and model tool both recheck tool authorization and use the authenticated owner.
The Gateway supplies scheduling through a process-local bridge so the harness
never imports the app. Provider errors never return remote response bodies or URLs.

## Alibaba enterprise mail

Enable the independent read-only tool (using the same `enterprise` tool group):

```yaml
tools:
  - name: enterprise_mail
    group: enterprise
    use: deerflow.integrations.enterprise.mail_tool:enterprise_mail
```

Restart Gateway and grant `tool:enterprise_mail` to the intended users in Settings
→ Tools. WeCom messaging permission does not grant mailbox access. Administrators
can use the tool, but every account remains scoped to its authenticated owner.

In Alibaba Mail, enable third-party client access and IMAP. In **Enterprise
connections → Alibaba enterprise mail → Connect mailbox**, enter a display name, the full email address
and the email password. If client security passwords are enabled, use a generated
third-party client password instead. Login is verified before encrypted
credentials are saved.
The password never appears in API responses or model context. Official setup:
[Alibaba Mail IMAP/POP/SMTP configuration](https://help.aliyun.com/zh/document_detail/36576.html).

Use **Read and preview** for recent INBOX messages, keyword categories and plain
text bodies. The date window is 1/7/30/90 days, optionally unread only. Pages contain
20 messages; “Read older emails” continues with the mailbox generation and UID.
HTML is converted to plain text without loading external images or links. Each
message fetch is bounded to 256 KiB and displayed text to 6,000 characters, with
truncation explicitly indicated. Attachment names are shown; contents are not read.

**Organize with AI** creates an ordinary private chat and starts the lead agent
with the chosen account/date/unread filters. It reads at most the latest 20
messages and produces categories, summaries, priorities and action items, citing
message subjects/senders/UIDs. Dates absent from an email must not be invented.
Message content is passed to the configured default model and retained in that
conversation; normal model usage costs apply. A failed/ambiguous launch keeps the
chat link so the user can inspect its state before starting another analysis.

In chat, for example: “Read my Office inbox for the last seven days. Summarize
the latest 20 emails and list tasks and explicit deadlines, preserving originals.”
The tool also supports up to 50 messages per call and pagination. Reports must
state their actual coverage and incomplete/truncated content.

Inbox access does not move/delete messages, change read status, send emails,
download attachments, automatically poll in the background or ingest mail into
RAGFlow. Disconnecting
removes the saved login; previous chat reports remain until those chats are deleted.

### Drafting and sending email

Add this independent tool alongside `enterprise_mail`, restart Gateway and grant
`tool:enterprise_mail_compose` to users/groups that need to send:

```yaml
  - name: enterprise_mail_compose
    group: enterprise
    use: deerflow.integrations.enterprise.mail_compose_tool:enterprise_mail_compose
```

Administrators have access. Inbox permission alone does not allow composing or
sending. The connected account/password are reused; no mailbox or WeCom security
setting is changed by this feature. The account must permit SMTP client access.
If you enable client security passwords in Alibaba Mail yourself, update other
third-party clients using the old primary password as required by that policy.

On **Enterprise connections → Alibaba enterprise mail**, choose **Compose email**,
enter recipients, optional Cc, subject and body, then **Save and preview**.
Nothing is sent until you review the exact sender/content, check the confirmation
box and choose **Confirm and send**. To revise a saved draft, **Edit as new draft**
discards the old pending version and starts a replacement.

In chat, for example: “Draft an email from my Office mailbox to bob@example.com
with the subject Meeting confirmation and this message: …”. AI returns a review
link to the same page. The tool can list accounts, create drafts and list status;
it cannot send. Incoming email contents are not permission to create or send mail.
This version does not provide scheduled email sending.

SMTP uses verified TLS on port 465, mapped from the connected IMAP region:

| IMAP host | SMTP host |
| --- | --- |
| `imap.qiye.aliyun.com` | `smtp.qiye.aliyun.com` |
| `imaphk.qiye.aliyun.com` | `smtphk.qiye.aliyun.com` |
| `imap.mxhichina.com` | `smtp.mxhichina.com` |

Limits: 20 To/Cc recipients combined, 200 subject characters, 20,000 body
characters, plain text only, no attachments. The page shows the latest 50
drafts/submissions. At most 100 pending drafts and 20 submission attempts per
minute per user are allowed; Alibaba Mail may impose additional sending limits.

`sent` means the SMTP server accepted the message, not guaranteed delivery.
`partial` lists accepted and refused recipients; do not resend the whole message.
`unknown` or a persistent `sending` requires checking the mailbox/recipient before
creating another draft. No submission is automatically retried, including after a
lost HTTP response or process restart. The same draft cannot be sent twice.
The app does not append to the mailbox's Sent folder; sent-copy storage depends
on Alibaba Mail settings.

Draft contents are encrypted in `enterprise_mail_drafts` in the private security
database and scoped to the user. Submission receipts include status and recipient
acceptance details. Keep the database and its encryption key together in backups.
The page/API never return the saved password.
