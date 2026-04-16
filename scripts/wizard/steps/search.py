"""Step: Web search configuration."""

from __future__ import annotations

from dataclasses import dataclass

from wizard.providers import SEARCH_PROVIDERS, WEB_FETCH_PROVIDERS, SearchProvider, WebProvider
from wizard.ui import ask_choice, ask_secret, print_header, print_info, print_success


@dataclass
class SearchStepResult:
    search_provider: SearchProvider | None  # None = skip
    search_api_key: str | None
    fetch_provider: WebProvider | None  # None = skip
    fetch_api_key: str | None


def run_search_step(step_label: str = "Step 3/3") -> SearchStepResult:
    print_header(f"{step_label} · Web Search & Fetch (optional)")
    provided_keys: dict[str, str] = {}

    search_options = [f"{p.display_name}  —  {p.description}" for p in SEARCH_PROVIDERS]
    search_options.append("Skip for now  (agent still works without web search)")

    idx = ask_choice("Choose a web search provider", search_options, default=0)

    search_provider: SearchProvider | None = None
    search_api_key: str | None = None
    if idx >= len(SEARCH_PROVIDERS):
        search_provider = None
    else:
        search_provider = SEARCH_PROVIDERS[idx]
        if search_provider.env_var:
            print()
            search_api_key = ask_secret(f"{search_provider.env_var}")
            provided_keys[search_provider.env_var] = search_api_key
            print_success(f"Key will be saved to .env as {search_provider.env_var}")

    print()
    fetch_options = [f"{p.display_name}  —  {p.description}" for p in WEB_FETCH_PROVIDERS]
    fetch_options.append("Skip for now  (agent can still answer without web fetch)")

    idx = ask_choice("Choose a web fetch provider", fetch_options, default=0)

    fetch_provider: WebProvider | None = None
    fetch_api_key: str | None = None
    if idx < len(WEB_FETCH_PROVIDERS):
        fetch_provider = WEB_FETCH_PROVIDERS[idx]
        if fetch_provider.env_var:
            if fetch_provider.env_var in provided_keys:
                fetch_api_key = provided_keys[fetch_provider.env_var]
                print()
                print_info(f"Reusing {fetch_provider.env_var} from web search provider")
            else:
                print()
                fetch_api_key = ask_secret(f"{fetch_provider.env_var}")
                provided_keys[fetch_provider.env_var] = fetch_api_key
                print_success(f"Key will be saved to .env as {fetch_provider.env_var}")

    return SearchStepResult(
        search_provider=search_provider,
        search_api_key=search_api_key,
        fetch_provider=fetch_provider,
        fetch_api_key=fetch_api_key,
    )
