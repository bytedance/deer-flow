# Custom skill YAML diagnostics: local integration check

Captured from the production-built frontend connected to the real Gateway,
with a locally initialized administrator and on-disk custom skill. Browser
requests were not intercepted and API responses were not mocked. This is a
local contribution validation, not an official hosted deployment.

1. Start Gateway with an isolated local data directory and sign in as its admin.
2. Under that user's custom skill root, create `weekly-project-summary/SKILL.md`:

   ```markdown
   ---
   name: weekly-project-summary
   description: Summarize project activity: commits and open issues
   ---

   # Weekly project summary

   Summarize the project's recent commits and open issues for a weekly update.
   ```

3. Open Capability Center → Skills → My skills. The real diagnostic endpoint
   reports `invalid_frontmatter`, `quote_colon_value`, line 3, column 40. The
   normal skill list excludes `weekly-project-summary`.
4. Quote the entire description value on disk and use **Reload skills**.
   The real POST `/api/skills/reload` returns 200, diagnostics become empty,
   and the normal skill list includes `weekly-project-summary`.

Screenshots: [malformed file](skill-yaml-diagnostics.png) and
[corrected file after reload](skill-yaml-recovered.png).

Environment: Windows frontend/Chromium, WSL Python 3.12 Gateway, local SQLite.
No model was configured or called; this check validates skill management only.
