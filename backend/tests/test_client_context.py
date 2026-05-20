from deerflow.runtime.client_context import (
    render_client_context_for_prompt,
    sanitize_client_context,
)


def test_sanitize_client_context_keeps_only_prompt_relevant_fields():
    client = sanitize_client_context(
        {
            "name": "custom-analytics-frontend",
            "access_token": "secret",
            "capabilities": {
                "artifacts": True,
                "csv_download": True,
                "charts": False,
                "bad key": True,
                "string_bool": "true",
            },
            "preferences": {
                "csv": "present",
                "chart": "present",
                "nested": {"drop": True},
                "empty": "",
            },
        }
    )

    assert client == {
        "name": "custom-analytics-frontend",
        "capabilities": {
            "artifacts": True,
            "charts": False,
            "csv_download": True,
        },
        "preferences": {
            "chart": "present",
            "csv": "present",
        },
    }


def test_render_client_context_for_prompt_escapes_and_formats():
    rendered = render_client_context_for_prompt(
        {
            "name": "analytics <frontend>",
            "capabilities": {
                "artifacts": True,
                "images": False,
            },
            "preferences": {
                "csv": "present <download>",
                "concise": True,
            },
        }
    )

    assert rendered == "\n".join(
        [
            "<client_context>",
            "name: analytics &lt;frontend&gt;",
            "capabilities: artifacts",
            "unsupported_capabilities: images",
            "preferences: concise=true; csv=present &lt;download&gt;",
            "</client_context>",
        ]
    )


def test_render_client_context_for_prompt_returns_none_when_no_safe_fields():
    assert render_client_context_for_prompt({"access_token": "secret"}) is None
    assert render_client_context_for_prompt("bad-client-context") is None
