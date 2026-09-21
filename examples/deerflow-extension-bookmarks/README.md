# Conversation bookmarks — independent plugin example

A Pi-inspired example of a complete feature in one package: save the last visible
assistant answer from a conversation menu, then search, rename, read or delete
bookmarks in its own **My bookmarks** page, reached from the workspace sidebar.
Capability Center only displays the plugin's information and deployment status.
The read-only `search_bookmarks`
model tool searches the authenticated user's saved excerpts. Each user sees only
their own data, including when the Agent calls the tool.

**Requires a host with the full-stack plugin contract and extension-api 0.2.2.** Pi's original labels session entries; this web
adaptation is independently implemented. See [attribution](THIRD_PARTY_NOTICES.md).

## Deployment

Install this directory using the existing trusted Python extension manager, or
build and install its wheel into the Gateway environment. Install the matching
local extension-api/harness packages first. From `backend/`:

```sh
uv run deerflow extensions install ../examples/deerflow-extension-bookmarks --yes
```

Then set the deployment-owned `config` on the registered plugin entry before
restarting Gateway. Example configuration:

```yaml
plugins:
  - use: deerflow_extension_bookmarks:install
    enabled: true
    config:
      enabled: true
      storage_path: /var/lib/deerflow/bookmarks.sqlite
```

The outer `enabled` controls package loading; `config.enabled` controls its
contribution. Installation, changes to either switch, code upgrades and deployment
configuration require Gateway restart. Mount a persistent writable directory for
`storage_path`. The browser module is packaged in the wheel and served by the
Gateway; no plugin-specific frontend or Docker image compilation is needed when
the compatible host and dependencies are already installed. Python packages must
still be present in the actual Gateway environment.

The extension catalog is **read-only for everyone**, including administrators.
It contains the card and plugin details. There is no online plugin configuration write API or override database. The SQLite
file above stores user bookmarks, not deployment settings.

## Try it

1. Enable the package at deployment, restart Gateway, then refresh the browser.
2. Open a conversation with a visible answer. Select **Bookmarks → Save last answer**
   in the conversation menu (also available in the sidebar conversation menu).
3. Open **My bookmarks** from the sidebar. Its direct URL is
   `/workspace/extensions/community.bookmarks/library`, and survives refresh.
4. Search text or labels, edit a name, open the source conversation, or confirm deletion.
5. Ask the Agent to find a saved answer. Its normal tool assembly contains a
   namespace-qualified `search_bookmarks` tool; the existing tool/group/skill policy
   still applies. Agents restricted to other tool groups do not receive it.

## Boundaries

- Answers are user-submitted saved copies, not server-certified transcript records.
  Hidden messages, tool output and reasoning are excluded by the host's existing
  export sanitizer before the UI submits the visible answer. No remote model or
  external service is called while saving/managing bookmarks.
- Original conversation links do not grant access. Normal thread authorization
  still applies; deletion of an original thread does not delete a saved copy.
- Up to 200 bookmarks per user, 12,000 characters per answer; searches return at
  most 10 excerpts (1,000 characters each) and a total count. Narrow the query for
  more matches; the page can load the full saved answer. Duplicate saves are
  idempotent and do not overwrite an existing label.
- Storage uses SQLite and blocking I/O is offloaded from the event loop. This is a
  single-host example, not a multi-node storage contract or tenant administration UI.
- Plugin browser/Python code is trusted deployment code. Shadow DOM scopes CSS,
  not security privileges. Model search is read-only and never accepts a user ID.
- This example does not implement hot unloading or retaining old Python code across
  service restarts.

## Host contract exercised

`PluginContribution` packages one `BrowserModule`, five `BackendAction`s and one
`ModelTool`. The module contributes a conversation action and a `page` DOM surface.
The page declares `navigation: { label: "My bookmarks", labelZh: "我的书签", icon: "bookmark" }`.
The host builds the route from the namespace and surface ID and adds the optional
sidebar entry; the plugin cannot claim arbitrary host URLs. Disabled/unloaded pages
have no navigation entry and show an unavailable state on direct visits after reload.
The host loads generic descriptors, supplies the sanitized visible-answer service,
binds authenticated backend calls, and mounts/disposes the page. There is no
bookmark-specific page, router, database table or business branch in host code.

Automated coverage: `backend/tests/test_bookmark_plugin.py`,
`frontend/tests/e2e/bookmark-plugin.spec.ts`, plus shared API and lifecycle tests.
Browser E2E uses a real Python plugin/router and SQLite with synthetic authentication;
its model-call fixture uses real LangGraph ToolNode dispatch with a scripted call,
not a live language model or the complete production Gateway.

Returning to a conversation uses the host's `openConversation(threadId)` helper,
which resolves its current agent from authenticated thread metadata. This also
repairs navigation for existing bookmarks without migrating the SQLite schema.
A missing/inaccessible conversation shows an error instead of opening the default
agent. Hosts without this optional navigation helper cannot reopen conversations
from this version of the example.
