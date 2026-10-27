export const mailOutboxMessages = {
  "zh-CN": {
    title: "写邮件与发送记录",
    hint: "使用已绑定的阿里邮箱发送。AI 起草的邮件也会在这里等待确认。",
    compose: "写邮件",
    from: "发件邮箱",
    sender: "发件人",
    to: "收件人",
    cc: "抄送（可选）",
    recipientHint: "多个邮箱用逗号分隔，收件人与抄送合计最多 20 个。",
    subject: "主题",
    body: "正文",
    preview: "保存并预览",
    previewTitle: "邮件预览",
    close: "关闭",
    cancel: "取消",
    edit: "重新编辑",
    discard: "放弃草稿",
    confirm: "我已核对收件人和邮件内容",
    send: "确认发送",
    sending: "正在提交…",
    refresh: "刷新状态",
    loading: "加载中…",
    empty: "还没有草稿或发送记录。",
    history: "最近 50 条草稿与发送记录",
    accepted: "已接受的收件人",
    refused: "被拒绝的收件人",
    pending: "邮件尚未发送。请核对以下内容后确认。",
    sentHint:
      "阿里邮箱服务器已接受邮件，不代表收件人已收到。已发送副本是否保存取决于邮箱设置。",
    unknownHint: "发送结果尚未确认。请先核对邮箱或联系收件人，避免重复发送。",
    plainText: "当前支持纯文本邮件，暂不支持附件。",
    statuses: {
      draft: "待确认",
      sending: "提交中／待核实",
      sent: "已提交",
      partial: "部分接受",
      failed: "发送失败",
      unknown: "结果待核实",
      discarded: "已放弃",
    },
    errors: {
      access_denied:
        "发信权限尚未开通，请管理员授权 enterprise_mail_compose。收信与整理权限保持独立。",
      not_configured: "发信功能尚未配置，请联系管理员。",
      invalid_mail_message:
        "请检查收件人、主题和正文。请填写完整邮箱地址，主题最多 200 字，正文最多 20000 字。",
      mail_auth_failed:
        "发信认证失败，请检查 SMTP 权限和绑定密码。已启用客户端安全密码时需使用对应密码。",
      mail_smtp_unavailable:
        "无法连接阿里邮箱发信服务，请检查网络及 SMTP 权限。",
      mail_recipient_rejected: "阿里邮箱拒绝了所有收件人，请核对邮箱地址。",
      mail_send_rejected:
        "阿里邮箱拒绝了此次发信，请检查账号发信限制或邮件内容。",
      mail_partial: "只有部分收件人被接受，请查看下方明细，不要整封重复发送。",
      mail_send_unknown:
        "连接中断，无法确认是否已发送。请先核对，系统不会自动重发。",
      mail_request_uncertain:
        "未取得发送结果，请刷新状态后核对。系统不会自动重发。",
      mail_busy: "发信连接繁忙，本次未发送。",
      rate_limited: "操作过于频繁，请稍后再试。",
      mail_drafts_full: "待确认草稿已达上限，请先处理或放弃旧草稿。",
      draft_not_found: "草稿不存在或不属于当前账号。",
      target_not_found: "关联邮箱已断开，请重新绑定后创建新草稿。",
      credential_unavailable: "邮箱凭证不可用，请联系管理员。",
      request_failed: "操作失败，请稍后重试。",
    },
  },
  "en-US": {
    title: "Compose and sending history",
    hint: "Send through a connected Alibaba mailbox. AI drafts also wait here for confirmation.",
    compose: "Compose email",
    from: "From mailbox",
    sender: "Sender",
    to: "To",
    cc: "Cc (optional)",
    recipientHint:
      "Separate addresses with commas. Up to 20 To/Cc recipients combined.",
    subject: "Subject",
    body: "Body",
    preview: "Save and preview",
    previewTitle: "Email preview",
    close: "Close",
    cancel: "Cancel",
    edit: "Edit as new draft",
    discard: "Discard draft",
    confirm: "I have checked the recipients and content",
    send: "Confirm and send",
    sending: "Submitting…",
    refresh: "Refresh status",
    loading: "Loading…",
    empty: "No drafts or sending records yet.",
    history: "Latest 50 drafts and submissions",
    accepted: "Accepted recipients",
    refused: "Rejected recipients",
    pending: "This email has not been sent. Review it before confirming.",
    sentHint:
      "Alibaba Mail accepted the email; recipient delivery is not guaranteed. Sent-copy storage depends on mailbox settings.",
    unknownHint:
      "Submission is not confirmed. Check your mailbox or with the recipients before sending again.",
    plainText: "Plain-text email only; attachments are not supported yet.",
    statuses: {
      draft: "Awaiting confirmation",
      sending: "Submitting / verify status",
      sent: "Submitted",
      partial: "Partially accepted",
      failed: "Failed",
      unknown: "Verify delivery",
      discarded: "Discarded",
    },
    errors: {
      access_denied:
        "Ask an administrator to grant enterprise_mail_compose. Inbox access is a separate permission.",
      not_configured:
        "Email sending is not configured. Contact an administrator.",
      invalid_mail_message:
        "Check recipients, subject and body. Use complete email addresses; subject limit 200, body limit 20000 characters.",
      mail_auth_failed:
        "SMTP authentication failed. Check access permissions and the saved password; use the client password when required.",
      mail_smtp_unavailable:
        "Cannot connect to Alibaba SMTP. Check network and SMTP access.",
      mail_recipient_rejected:
        "Alibaba Mail rejected every recipient. Check their addresses.",
      mail_send_rejected:
        "Alibaba Mail rejected this submission. Check sending limits or message content.",
      mail_partial:
        "Only some recipients were accepted. Review the details; do not resend to everyone.",
      mail_send_unknown:
        "Connection interrupted. Delivery is unknown and will not be retried automatically.",
      mail_request_uncertain:
        "No submission result received. Refresh and verify status; no automatic retry.",
      mail_busy: "SMTP connections are busy. This email was not sent.",
      rate_limited: "Too many requests. Try again later.",
      mail_drafts_full:
        "Too many pending drafts. Send or discard existing drafts first.",
      draft_not_found: "Draft not found for this account.",
      target_not_found:
        "Mailbox disconnected. Reconnect and create a new draft.",
      credential_unavailable:
        "Mailbox credential unavailable. Contact an administrator.",
      request_failed: "Request failed. Please try again.",
    },
  },
};
