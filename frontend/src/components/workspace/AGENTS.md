# Workspace model catalog

`settings/model-catalog-dialog.tsx` keeps connection drafts in component state,
aborts on dismissal, sequences `/discover` + `/import`, and refreshes both model
queries after partial/cancelled imports. Never retry writes automatically. Custom endpoints precede keys; destination edits clear credentials. Picker rows
and arrow-key navigation share one group order. The
server deduplicates by connection, credential and model under the catalog lock.
