"""Single owner for the credential rules the bundled retrieval providers share.

``community/lightrag`` and ``community/ragflow`` are two read-only retrieval
providers that each carried a byte-identical copy of three rules: how a
configured API key is unwrapped from a ``SecretStr`` and normalized, how that
key is scrubbed out of text before it reaches a log line or a tool error, and
why a configured base URL must not carry userinfo. Two owners for one rule means
a fix to one provider can silently leave the other one leaking.

Search and fetch providers that read a key from config or the environment
resolve it through ``resolve_api_key`` too. A key read from a file keeps its
trailing newline, and putting that raw value into a header makes the HTTP
transport refuse it with an error that quotes the whole header, key included
(``tests/test_provider_api_key_whitespace.py``).

``is_template_placeholder`` is the one definition of an ``.env.example`` example
value. ``scripts/doctor.py`` asks it for every web provider key, so the diagnosis
and the runtime agree on which keys count as configured. Model credentials do not
pass through here: their clients send whatever is set, so doctor's model check
flags likely sample values with its own, broader rule.

The marker and the message are module constants because the strings are part of
the contract: provider tests and operators' log grep patterns assert on them.
"""

from __future__ import annotations

from pydantic import AnyHttpUrl, SecretStr

REDACTION_MARKER = "[REDACTED]"
URL_USERINFO_ERROR = "base_url must not contain username or password information"

# Every ``your-...`` example value ``.env.example`` ships, matched exactly. A rule
# that guesses at the shape would also drop a token an operator chose, such as a
# self-hosted Browserless ``TOKEN`` named ``your-review-team-token``.
# ``tests/test_provider_credentials_single_owner.py`` keeps this set equal to the
# template's values.
ENV_TEMPLATE_PLACEHOLDERS = frozenset(
    {
        "your-anthropic-auth-token",
        "your-claude-code-oauth-token",
        "your-deepseek-api-key",
        "your-dingtalk-client-id",
        "your-dingtalk-client-secret",
        "your-discord-bot-token",
        "your-e2b-api-key",
        "your-exa-api-key",
        "your-feishu-app-id",
        "your-feishu-app-secret",
        "your-fernet-key",
        "your-firecrawl-api-key",
        "your-gemini-api-key",
        "your-github-token",
        "your-image-generation-api-key",
        "your-infoquest-api-key",
        "your-jina-api-key",
        "your-langsmith-api-key",
        "your-langsmith-project",
        "your-minimax-api-key",
        "your-novita-api-key",
        "your-openai-api-key",
        "your-openviking-user-api-key",
        "your-opper-api-key",
        "your-provisioner-api-key",
        "your-serper-api-key",
        "your-serply-api-key",
        "your-shared-internal-token",
        "your-slack-app-token",
        "your-slack-bot-token",
        "your-sofya-api-key",
        "your-specstream-api-key",
        "your-stepfun-api-key",
        "your-tavily-api-key",
        "your-telegram-bot-token",
        "your-unbrowse-api-key",
        "your-vllm-api-key",
        "your-volcengine-api-key",
        "your-webz-api-key",
        "your-wecom-bot-id",
        "your-wecom-bot-secret",
    }
)


def is_template_placeholder(value: str) -> bool:
    """Whether ``value`` is an ``.env.example`` example value rather than a credential.

    Only the exact shipped value matches, ignoring surrounding whitespace: a key
    that merely resembles one (``sk-your-jina-api-key``) is a key.
    """
    return value.strip() in ENV_TEMPLATE_PLACEHOLDERS


def resolve_api_key(raw: str | SecretStr | None) -> str | None:
    """Return the configured or environment key with surrounding whitespace removed.

    Blank or absent reads as ``None``: a missing key is not an error, it is an
    unconfigured provider. Unwrapping happens only here, so no provider can end
    up comparing (or printing) the repr of a ``SecretStr`` instead of its value.

    An ``.env.example`` placeholder also reads as ``None``. ``make config`` copies
    that template verbatim, and sending ``your-jina-api-key`` as a key made the
    keyless Jina Reader fail every fetch with 401 instead of using its free tier.
    """
    value = raw.get_secret_value() if isinstance(raw, SecretStr) else raw
    if isinstance(value, str) and value.strip():
        return None if is_template_placeholder(value) else value.strip()
    return None


def redact_secret(value: object, secret: str | None) -> str:
    """Stringify ``value`` and replace every occurrence of ``secret``.

    Applied to error text, provider payloads and configured base URLs alike, so
    a key embedded in a URL or an exception message cannot reach a log. A
    ``None`` secret leaves the text untouched rather than raising.
    """
    text = str(value)
    if secret:
        text = text.replace(secret, REDACTION_MARKER)
    return text


def reject_url_userinfo(value: AnyHttpUrl) -> AnyHttpUrl:
    """Reject a configured base URL that smuggles credentials in userinfo."""
    if value.username is not None or value.password is not None:
        raise ValueError(URL_USERINFO_ERROR)
    return value
