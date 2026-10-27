# DDFW-Agent enterprise adaptation

Goal: apply the requested DDFW-Agent identity, enable custom agents in this deployment, and remove upstream support/about entries from the workspace.

Implementation uses the existing Next.js components and translations. Branding is a text wordmark with matching SVG assets. The existing `agents_api.enabled` switch remains the source of truth for agent availability. Auth, model configuration, internal identifiers, and third-party license notices keep their existing behavior.

- [x] Add failing DOM coverage for expanded/collapsed branding, the settings menu, and the settings section list; cover old About deep links.
- [x] Replace visible brand text in application components and both UI locales; replace the deer background and browser icon with DDFW-Agent assets.
- [x] Remove external support entries and About from the workspace menu/settings, including deep-link registration.
- [x] Enable `agents_api.enabled` in the ignored deployment configuration and verify runtime feature discovery.
- [x] Run focused frontend tests, lint/type checking, and browser checks against an isolated test instance plus the live login page; update README and frontend guidance.

Acceptance: DDFW-Agent appears on login, workspace, mobile/collapsed navigation, and browser tabs. Settings remains usable and the five requested entries are absent. The authenticated Agents route can list and create agents through the existing backend API.

Validation: 19 focused unit/DOM tests passed; `pnpm check` passed. Browser checks passed for workspace branding, menu actions, settings content, Agents navigation, About deep links, mobile sidebar, live login, and favicon. Workspace browser checks used existing mocked APIs in an isolated frontend with test-only auth bypass; the running Gateway independently reported `agents_api.enabled=true` and accepted the agent-management feature gate. No real user agent was created.
