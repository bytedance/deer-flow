# DeerFlow Android

The `android/` module is the native Android workspace client for a self-hosted
DeerFlow Gateway. It uses Kotlin, Jetpack Compose Material 3, Navigation
Compose, Room, Retrofit, and OkHttp while reusing the same public `/api/*`
contracts as the web workspace.

## Current capabilities

- Local-account sign-in, Gateway-configured OIDC SSO in a secured WebView, and
  auth-disabled Gateway sessions
- Phone and tablet use a persistent conversation drawer; Agents, Tasks, Memory,
  and Profile open as child pages with top-bar/system-back return and Hero-style
  transitions
- Conversation search, create, rename, delete, pin, cached history, and drafts
- Launcher shortcuts for starting a new conversation and reopening the most recent cached conversations for the active server
- Incremental `messages-tuple` SSE rendering with monotonic snapshot merging,
  run cancellation, and reconnect; the composer exposes visible connecting,
  running, reconnecting, and stopping state while keeping stop available for a
  restored active run. On Android 16, eligible devices use promoted Live
  Updates with system progress styling, status chips, current-step summaries,
  launcher-icon-matched colors, and phase-aware tracker icons. If promotion is
  unavailable, dismissed, or running on an older release, the client keeps a
  standard foreground progress notification instead
- SSE ownership lives in an application-level coordinator; active run markers
  are persisted and either a restarted foreground service or a freshly
  authenticated app process reattaches to and opens a resumable Gateway run
- Model, Agent, thinking/plan/subagent mode, and enabled-skill run options
- Model capabilities filter unsupported run modes and reasoning controls
- Camera, photo picker, and document uploads with visible upload state
- CommonMark content, grouped citation sources, fenced code, quotes,
  grouped/collapsible tool calls,
  structured Web source links, image-result tiles, file and shell output,
  human-input cards, explicit approval cards, collapsible subtask cards,
  attachments, and error blocks
- Regenerate the latest assistant response from a Gateway checkpoint and branch
  an assistant turn into a new conversation
- Export visible conversations as Markdown or plain text; failed uploads retain
  retryable state across process recreation
- Gateway Todo state appears as an expandable progress summary with item status
- Artifact references are clickable; text/Markdown files preview in-app, while
  fetched files can be saved or opened through Android `ACTION_VIEW`
- Common source artifacts show an inferred language label with monospace code
  presentation
- Custom Agent list/create/edit/delete, dedicated detail views, chat entry
  points, and server-filtered execution history with run details and linked
  conversation navigation when enabled by the Gateway, with a server-scoped
  default Agent used for new conversations
- Scheduled-task list/create/edit for repeating `cron` and one-time `once`
  schedules, pause/resume, run-now, failure, delete, per-task execution
  history/detail, and conversation-output navigation
- Memory summaries and searchable facts with create, edit, delete, and clear
  controls
- Composer capability panel showing automatic Memory status and the authenticated
  Gateway MCP tool catalog grouped by source server
- Administrator MCP server browser with transport, description, configured tool
  overrides, persistent enable/disable controls, and a full masked JSON
  configuration editor that preserves secret values unless they are replaced
- Channels provider browser with user binding codes and administrator runtime
  credential configuration, updates, and per-provider disable controls
- Offline cached conversation/message browsing with tool groups, Human Input,
  approval, subtask, Todo, Artifact, and attachment structure preserved, without
  automatic send queues
- Profile settings include explicit System/English/Simplified Chinese locale
  selection, terminal run-alert preference, cache size/count statistics,
  retention policy and confirmed clearing, plus an About screen with app
  version/build/package/source details, the bundled MIT license, and generated
  third-party license notices
- Material 3 Expressive theme, floating toolbar, morphing loading indicators,
  shapes and motion, dynamic color on Android 12+,
  DeerFlow fallback colors, system light/dark mode, English/Chinese resources,
  and TalkBack labels

Full syntax highlighting is not part of the current native client. Unsupported
formats continue to rely on Android system apps or the web workspace.

## Requirements

- Android Studio Ladybug or newer, or JDK 17 and the included Gradle wrapper
- Android SDK 36
- An accessible DeerFlow public endpoint (`make dev` serves one on port `2026`)
- Android 8.0 (API 26) or newer

## Build and verify

From the repository root:

```bash
cd android
./gradlew testDebugUnitTest lintDebug assembleDebug assembleDebugAndroidTest
```

The debug APK is written to `android/app/build/outputs/apk/debug/app-debug.apk`.
Release builds generate the complete third-party license resources consumed by
the native About screen; the Google OSS Licenses Gradle plugin intentionally
uses a diagnostic placeholder for debug variants because AGP does not publish
their dependency report. The app does not include the Google Play services OSS
Licenses runtime SDK. Build a release variant when validating the generated
dependency list.
For a signed release, provide all four `DEERFLOW_RELEASE_*` values as Gradle
properties, environment variables, or `android/keystore.properties`:
`DEERFLOW_RELEASE_STORE_FILE`, `DEERFLOW_RELEASE_STORE_PASSWORD`,
`DEERFLOW_RELEASE_KEY_ALIAS`, and `DEERFLOW_RELEASE_KEY_PASSWORD`. Without
them, `assembleRelease` signs a local validation-only Release APK with the AGP
debug certificate so `apksigner` can verify it. It must not be distributed:
provide all four values before publishing a Release artifact.
Run connected tests only against an emulator and select its serial explicitly:

```bash
ANDROID_SERIAL=emulator-5554 ./gradlew connectedDebugAndroidTest
```

For a self-contained emulator smoke test, start the local fixture and connect
the app to `http://10.0.2.2:2027` with any non-empty credentials:

```bash
python3 tools/mock_gateway.py --port 2027
```

The fixture also exposes Agent execution history and stateful cron/once tasks.
After signing in, open **Agents** > **researcher** > **Execution history** to
inspect a filtered run list, or open **Tasks** to create and edit a one-time
task against the same Gateway contract.

## Connect to a server

For the Android emulator, the default `http://10.0.2.2:2026` reaches port
`2026` on the development host. Enter the deployment origin only, without
`/api` or `/api/langgraph`.

Debug builds permit cleartext HTTP so they can reach LAN development servers.
Release builds require HTTPS except for `localhost` and the emulator's
`10.0.2.2` alias. Use TLS and DeerFlow authentication outside a trusted local
network. Session and CSRF cookies are kept in Android's system cookie store;
credentials and tokens are not written to the Room cache.

Agent execution history calls `GET /api/console/runs?assistant_id=...`. The
Gateway applies that filter before pagination; its observability queries require
a SQLite or PostgreSQL persistence backend. A memory-backed Gateway reports an
unavailable history view that the user can retry after the server is configured.

When the Gateway enables `auth.oidc` and publishes one or more providers, the
login screen keeps the local email/password form and adds one button per
provider. The selected flow runs in the embedded WebView, which permits only
HTTP(S), disables file/content access and mixed content, and returns to the
native workspace only after `/api/v1/auth/me` confirms the shared session
cookie. Configure each provider callback in the Gateway as
`/api/v1/auth/callback/<provider-id>`; the Android client never receives or
stores an OIDC token.

Room stores server-scoped conversation metadata, message text, versioned
structured message payloads, drafts, run resume markers, and workspace metadata
snapshots. Legacy text-only message rows remain readable. Models, Agents,
Skills, feature flags, scheduled Tasks, Memory, and the safe MCP tool catalog
fall back to their last complete server-scoped snapshot when the Gateway is
unavailable. Offline mode never queues prompts for later transmission, so a
network recovery cannot unexpectedly start an Agent run. A successful run is
exposed as complete only after its final messages and active-run marker cleanup
are committed together.

Versioned Room schemas are checked in under `app/schemas/`. The Android
instrumentation suite uses `MigrationTestHelper` to validate the production
version 1-to-2, 2-to-3, 3-to-4, and complete 1-to-4 migration paths, including
preservation of existing workspace data and legacy messages.

Preferences DataStore stores the server URL, theme, dynamic-color setting,
terminal run-alert preference, cache-retention policy, server-scoped pinned
conversations, and each server's default Agent. A missing or deleted saved Agent
falls back to `lead_agent`. AppCompat per-app locale storage owns the explicit
System/English/Simplified Chinese selection. Existing installs migrate the
legacy `deerflow_settings` SharedPreferences values once before the first
DataStore read; migration and subsequent read/write consistency are covered by
instrumentation tests.
