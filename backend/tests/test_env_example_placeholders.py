"""The environment template must not ship live placeholder credentials.

``make config`` / ``make setup`` copy ``.env.example`` verbatim into ``.env``, and
``make dev`` exports that file. A live line such as
``JINA_API_KEY=your-jina-api-key`` therefore reaches the provider as a real
credential: the keyless Jina Reader answers 401 instead of the intended
unauthenticated request (#8094).
"""

from pathlib import Path

ENV_TEMPLATE = Path(__file__).resolve().parents[2] / ".env.example"


def test_env_example_ships_no_live_placeholder_values() -> None:
    live = [line for line in ENV_TEMPLATE.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#") and "=your-" in line]
    assert live == [], f"Uncommented placeholder credentials are copied into .env and sent to providers: {live}"
