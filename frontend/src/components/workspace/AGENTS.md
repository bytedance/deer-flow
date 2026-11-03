# Workspace model catalog

`settings/model-catalog-dialog.tsx` keeps connection drafts in component state,
aborts on dismissal, sequences `/discover` + `/import`, and refreshes both model
queries after partial/cancelled imports. Never retry writes automatically. The
server deduplicates by connection, credential and model under the catalog lock.
