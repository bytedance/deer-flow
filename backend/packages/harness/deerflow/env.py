"""Explicit backend dotenv selection, independent of configuration imports."""

import os
from io import StringIO
from pathlib import Path

from dotenv import load_dotenv


def load_selected_env_file() -> bool:
    """Load DEER_FLOW_ENV_FILE; return False only when the option is unset.

    Relative paths use the process working directory. Callers retain their
    original load_dotenv() call for default discovery when this returns False.
    Existing process variables (including empty values) always take precedence.
    """
    selected = os.environ.get("DEER_FLOW_ENV_FILE")
    if selected is None:
        return False
    # Match python-dotenv's switch without silently ignoring explicit selection.
    if os.environ.get("PYTHON_DOTENV_DISABLED", "").casefold() in {"1", "true", "t", "yes", "y"}:
        raise ValueError("DEER_FLOW_ENV_FILE cannot be used while PYTHON_DOTENV_DISABLED disables dotenv loading. Unset PYTHON_DOTENV_DISABLED or DEER_FLOW_ENV_FILE.")

    try:
        path = Path(selected)
        if not selected or not path.is_file():
            raise ValueError("Expected a regular file")
        # Read fully before parsing so decode failures cannot partially load env.
        contents = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        raise ValueError("DEER_FLOW_ENV_FILE must point to a readable UTF-8 regular file. Check the path and permissions; relative paths use the backend process working directory.") from None

    load_dotenv(stream=StringIO(contents), override=False)
    return True
