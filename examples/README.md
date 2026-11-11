# Develop an extension from an existing example

Start with the smallest example that covers your extension. Each directory is an
independent Python package using the public `deerflow-extension-api` contract.

| Start here                                                       | What it demonstrates                                                                                                           |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| [Extension example](deerflow-extension-example/README.md)        | Middleware, task lifecycle, model observations, services, and HTTP routes. Start here for backend extensions.                  |
| [Conversation bookmarks](deerflow-extension-bookmarks/README.md) | A browser page, conversation action, backend actions, packaged resources, and a model tool. Start here for full-stack plugins. |
| [Agent teams](deerflow-extension-agent-teams/README.md)          | Full Agent orchestration. Use this after the basic contribution and lifecycle patterns are familiar.                           |

Additional examples cover [Office file previews](deerflow-extension-office-preview/README.md),
[text-list classification](deerflow-extension-jev-classify/README.md),
[context pruning](deerflow-extension-jev-context/README.md),
[advisory screening of fetched content](deerflow-extension-jev-screening/README.md), and
[sectioned long-form report writing](deerflow-extension-report-sections/README.md).

## Describe the extension

Package `deerflow-extension.json` beside the entrypoint's Python module (beside
`__init__.py` for a package). Capability Center renders this public description
without requiring a browser module. Use the full-stack plugin namespace as `id`,
or a unique stable ID for a backend-only extension. A v1 document requires an ID,
at least one locale, and a nonempty **title**, **description** (purpose) and
**usage** list in every supplied locale. `requirements` and `docs_url` are optional;
omit requirements when none apply. Keep secrets and deployment configuration out
of this file. Names, purposes and instructions are authored by the package;
loaded/enabled state and registered tools come from the host.

```json
{
  "schema_version": 1,
  "id": "company.helper",
  "locales": {
    "en-US": {
      "title": "Task statistics",
      "description": "Collect tool-call statistics during tasks.",
      "usage": [
        {"title": "Run a task", "description": "Statistics are collected automatically after activation."}
      ]
    }
  }
}
```

The packaging checker validates this file when present and detects omitted wheel
resources. Older packages without it remain compatible. Invalid optional copy
produces a startup diagnostic while the working extension remains available.
Gateway reads copy at startup only, after successful registration. Disabled and
failed packages are not imported for documentation; a catalog entry alone does
not prove activation. A documented backend extension with actual registrations
appears in discovery even if it supplies no full-stack plugin.

For bundled examples, update their package files and run
`python scripts/sync_extension_documentation.py` from the repository root. The
generated frontend snapshot supplies descriptions before installation; installed
package copy takes precedence. Backend tests check that the snapshot is current.

## Edit, test, check, then install

1. Copy the selected example outside the DeerFlow checkout. Rename its Python
   package, distribution and `deerflow.extensions` entry point. For a full-stack
   plugin, also choose its own namespace and browser module name.
2. Follow the example's README to configure its dependencies and run its tests.
   Keep package behavior tests alongside the extension. For a bundled example
   with a `tests/` directory, CI installs the package with its `dev` extra next
   to this checkout's `deerflow-extension-api`, then runs `pytest`, `ruff check`
   and `ruff format --check`.
3. From the DeerFlow checkout root, prepare the backend environment with
   `make -C backend install`, then check the package:

   ```bash
   uv run --project backend --no-sync python scripts/check_extension.py /absolute/path/to/your-extension
   ```

   To try the checker on an unchanged example:

   ```bash
   uv run --project backend --no-sync python scripts/check_extension.py examples/deerflow-extension-bookmarks
   ```

4. Follow that example's deployment and try-it instructions. Restart Gateway,
   refresh the browser when applicable, and exercise the installed feature.
   Use `make extension-upgrade SOURCE=/absolute/path/to/your-extension` to apply
   later source edits: local installs are snapshots.

## What the checker covers

The script builds a wheel in a temporary directory, checks exactly one extension
entry point and its packaged Python module, parses packaged Python syntax, and
checks that the API dependency range accepts this checkout's contract version.
It validates conventional `ui_manifest.json` resources with the same validator
used by Gateway, including detecting manifests left out of the wheel in flat or
`src/` layouts. A custom manifest filename needs an explicit wheel-relative path:

```bash
uv run --project backend --no-sync python scripts/check_extension.py /absolute/path/to/your-extension --manifest your_package/resources.json
```

The build executes the package's build backend, so check trusted sources. The
checker does not import the extension, call `install()`, install the extension, or
change deployment configuration. Registration/configuration behavior and the
`@extension` version marker are verified when loading the plugin; continue to run
the package tests and the installed feature after packaging checks pass.
