# Browser E2E tests

Virtualized lists do not keep every fetched row mounted. Assert the pagination
request, then filter or scroll the loaded row into the rendered window before
checking its content. Preserve the real scroll trigger and search-mode guard.

For message ordering across compaction/refetch, poll an atomic DOM comparison
until both nodes settle. Missing or reversed nodes must still fail; keep history,
refresh and hidden-summary assertions. Avoid fixed sleeps and whole-test retries
as substitutes for synchronization.

Extension catalog counts follow extensionCatalog.length; the unit completeness
check independently enumerates packages. Keep localized management discovery
assertions so adding a package cannot silently remove its visible entry.
