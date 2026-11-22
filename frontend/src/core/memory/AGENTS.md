# Memory queries (`core/memory/`)

A successful mutation cancels the exact `["memory"]` query before it caches its
response, so an older read cannot undo a confirmed edit. Failed mutations and
later refreshes keep their normal behavior. Test it with a real `QueryClient`.
