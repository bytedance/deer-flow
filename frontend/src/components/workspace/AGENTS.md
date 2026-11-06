# Workspace model catalog

`settings/model-catalog-dialog.tsx` keeps connection drafts in component state,
aborts on dismissal, sequences `/discover` + `/import`, and refreshes both model
queries after partial/cancelled imports. Never retry writes automatically. Custom endpoints precede keys; destination edits clear credentials. Picker rows
and arrow-key navigation share one group order; catalog refresh clears absent
provider filters; active filters always remain clearable, including YAML models. The
server deduplicates by connection, credential and model under the catalog lock.

`settings/model-connection-fields.tsx` owns provider, endpoint and key fields for
single-model editing and catalog imports. Destination edits drop draft keys and
saved-source references; blank keys retain, explicit removal sends an empty key.
Parents own their model capabilities, revisions and independent draft lifetimes.
