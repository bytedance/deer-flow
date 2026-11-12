# Browser E2E tests (`frontend/tests/e2e/`)

- **Install the Office fixture dependencies before collecting tests.** Run
  `npm ci --ignore-scripts` in `examples/deerflow-extension-office-preview`.
  Playwright loads the resource suite before it selects a shard.

- **A virtualized list does not keep every fetched row mounted.** Assert the
  pagination request, then filter or scroll the row into the rendered window
  before you check its content. Keep the real scroll trigger.
- **For message order across compaction or refetch, poll one atomic DOM
  comparison** until both nodes settle. A missing or reversed node must still
  fail. Fixed sleeps and whole-test retries do not replace synchronization.
- **Extension catalog counts follow `extensionCatalog.length`.** Keep the
  localized discovery assertions, so adding a package cannot silently remove a
  visible entry.
