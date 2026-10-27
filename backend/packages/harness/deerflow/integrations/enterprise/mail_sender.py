"""Bounded SMTP submission to Alibaba's official TLS endpoints."""

import smtplib
import ssl
import threading
from contextlib import suppress
from email.message import EmailMessage
from email.utils import formatdate

from email_validator import EmailNotValidError, validate_email

from .mail import validate_account
from .providers import EnterpriseError

SMTP_HOSTS = {"imap.qiye.aliyun.com": "smtp.qiye.aliyun.com", "imaphk.qiye.aliyun.com": "smtphk.qiye.aliyun.com", "imap.mxhichina.com": "smtp.mxhichina.com"}
_SLOTS = threading.BoundedSemaphore(2)


def _address(value):
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise EnterpriseError("invalid_mail_message")
    try:
        return validate_email(value.strip(), check_deliverability=False, allow_smtputf8=False).ascii_email
    except EmailNotValidError:
        raise EnterpriseError("invalid_mail_message") from None


def normalize_message(sender, value):
    if not isinstance(value, dict) or set(value) - {"to", "cc", "subject", "body"}:
        raise EnterpriseError("invalid_mail_message")
    to, cc = value.get("to"), value.get("cc", [])
    subject, body = value.get("subject"), value.get("body")
    if not isinstance(to, list) or not to or not isinstance(cc, list) or len(to) + len(cc) > 20:
        raise EnterpriseError("invalid_mail_message")
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in subject):
        raise EnterpriseError("invalid_mail_message")
    if not isinstance(body, str) or not body.strip() or len(body) > 20000 or any(ord(c) < 32 and c not in "\r\n\t" for c in body):
        raise EnterpriseError("invalid_mail_message")
    recipients = list(dict.fromkeys(_address(item) for item in to))
    copies = [item for item in dict.fromkeys(_address(item) for item in cc) if item not in recipients]
    return {"sender": _address(sender), "to": recipients, "cc": copies, "subject": subject.strip(), "body": body}


class AliMailSender:
    def send(self, credentials, envelope, message_id):
        validate_account(credentials)
        if envelope["sender"] != _address(credentials["email"]):
            raise EnterpriseError("invalid_mail_message")
        recipients = envelope["to"] + envelope["cc"]

        def failure(status, error):
            return {"status": status, "error": error, "accepted": [], "refused": []}

        if not _SLOTS.acquire(blocking=False):
            return failure("failed", "mail_busy")
        connection = None
        submitting = False
        try:
            message = EmailMessage()
            message["From"] = envelope["sender"]
            message["To"] = ", ".join(envelope["to"])
            if envelope["cc"]:
                message["Cc"] = ", ".join(envelope["cc"])
            message["Subject"] = envelope["subject"]
            message["Message-ID"] = message_id
            message["Date"] = formatdate(usegmt=True)
            message.set_content(envelope["body"])
            connection = smtplib.SMTP_SSL(SMTP_HOSTS[credentials["host"]], 465, context=ssl.create_default_context(), timeout=15)
            connection.set_debuglevel(0)
            connection.login(credentials["email"], credentials["password"])
            submitting = True
            refused = connection.send_message(message, from_addr=envelope["sender"], to_addrs=recipients)
            accepted = [address for address in recipients if address not in refused]
            return {
                "status": "partial" if refused else "sent",
                "error": "mail_partial" if refused else None,
                "accepted": accepted,
                "refused": [address for address in recipients if address in refused],
            }
        except smtplib.SMTPAuthenticationError:
            return failure("failed", "mail_auth_failed")
        except smtplib.SMTPRecipientsRefused:
            return {"status": "failed", "error": "mail_recipient_rejected", "accepted": [], "refused": recipients}
        except (smtplib.SMTPDataError, smtplib.SMTPSenderRefused):
            return failure("failed", "mail_send_rejected")
        except (OSError, smtplib.SMTPException, ValueError, UnicodeError):
            return failure("unknown" if submitting else "failed", "mail_send_unknown" if submitting else "mail_smtp_unavailable")
        finally:
            if connection is not None:
                with suppress(Exception):
                    connection.quit()
                with suppress(Exception):
                    connection.close()
            _SLOTS.release()
