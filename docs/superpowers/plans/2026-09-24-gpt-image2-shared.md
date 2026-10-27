# GPT Image 2 shared-company integration implementation plan

**Approved:** User selected option 2: authorized users share the existing Hermes OpenAI key and company billing. This explicitly permits this integration to use an operator credential; other personal MCP credentials remain isolated.

**Goal:** Native gpt_image2 tool plus managed public:gpt-image2 Skill, user/thread-private image artifacts, company key held only under Gateway security directory.

**Architecture:** `community/gpt_image2/service.py` validates authenticated identity and current exact tool grant before reading the fixed private credential file, calls the fixed OpenAI images endpoint once using async HTTP and bounded response/input sizes. `files.py` confines reference reads/output writes to current-thread user-data using descriptor-relative non-symlink traversal on POSIX. `tools.py` exposes a typed tool returning a Command with artifact paths. Existing config registration and permission catalog discover it automatically. No frontend rebuild or additional MCP service.

## Tasks
- [x] Add failing tests for grant/deny/admin/context mismatch; JSON generation/multipart edit, path traversal and symlinks, response/error redaction, output ownership and no retry; run to prove missing implementation.
- [x] Implement the three small modules and test with httpx.MockTransport. Use one PNG result per call, standard square/portrait/landscape sizes, low/medium/high quality; optional up to four references and mask. Bounded concurrency (2) and 300-second total timeout. Never expose API key or raw remote errors.
- [x] Add `skills/public/gpt-image2/SKILL.md` with allowed-tools: gpt_image2, read_file, present_files, view_image. Describe grant requirements and explicitly use the native tool (no CLI or credential inspection). Add commented config.example registration and README/module-guide notes.
- [x] Copy the approved company key without printing it into the ignored Gateway private security directory, mode 0600; it is not in environment/sandbox mounts. Back up current config/security state first. Add tool group+registration to ignored config.yaml; do not modify Hermes.
- [x] Run targeted policy/API/runtime tests plus strict blocking test; compare existing full-suite baseline as documented in previous deployment. Restart only Gateway and reload nginx.
- [x] Verify actual catalog, denied/group-granted accounts and default skills, generate one low-quality small image through the authorized native tool, verify dimensions and user-owned artifact preview/download, and clean disposable auth fixtures. Report API access failures honestly.

**Validation commands:** Linux Gateway `.venv/bin/python -m pytest tests/test_gpt_image2.py -q`; related existing security/router/projection tests; ruff check/format --check on changed Python files. Runtime uses the existing bound backend source and package environment.

## Verified result

- Initial tests failed because the integration module did not exist. After implementation: 20 targeted tests plus strict async gate and related permission regressions: 43 passed. An additional real LangGraph ToolNode injection/artifact test passed (44 total). Ruff check and format check passed.
- Live production catalog exposes tool:gpt_image2 and skill:public:gpt-image2. Ordinary account denied, temporary group grants enabled access and Skill visibility; member removal revoked it. Temporary group/account removed; existing company groups preserved.
- One real low-quality API request returned a 1024x1024 PNG (958767 bytes). Owner artifact API returned 200, another user returned 404. Image visually inspected and saved in administrator conversation 55d41ca5-552a-4239-bf28-85848743b3fc. Reference-image/mask editing is covered by mocked multipart tests; no second paid edit request was made.
- Gateway restarted and healthy; nginx configuration checked/reloaded. Frontend remains in production mode. Private ignored config/state backup: logs/bootstrap/pre-image2-20260924-113616.
- Existing unrelated full-suite collection/memory-timeout baseline is unchanged; only relevant suites were rerun.
