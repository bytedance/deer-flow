---
name: smoke-test
description: End-to-end smoke test skill for DeerFlow. Guides through: 1) Pulling latest code, 2) Docker OR Local installation and deployment (user preference, default to Local if Docker network issues), 3) Service availability verification, 4) Health check, 5) Final test report. Use when the user says "run smoke test", "smoke test deployment", "verify installation", "test service availability", "end-to-end test", or similar.
---

# DeerFlow Smoke Test Skill

This skill guides the Agent through DeerFlow's full end-to-end smoke test workflow, including code updates, deployment (supporting both Docker and local installation modes), service availability verification, and health checks.

## Deployment Mode Selection

This skill supports two deployment modes:
- **Local installation mode** (recommended, especially when network issues occur) - Run all services directly on the local machine
- **Docker mode** - Run all services inside Docker containers

**Selection strategy**:
- If the user explicitly asks for Docker mode, use Docker
- If network issues occur (such as slow image pulls), automatically switch to local mode
- Default to local mode whenever possible

## Structure

```
smoke-test/
├── SKILL.md                          ← You are here - core workflow and logic
├── scripts/
│   ├── check_docker.sh               ← Check the Docker environment
│   ├── check_local_env.sh            ← Check local environment dependencies
│   ├── frontend_check.sh             ← Frontend page smoke check
│   ├── pull_code.sh                  ← Pull the latest code
│   ├── deploy_docker.sh              ← Docker deployment
│   ├── deploy_local.sh               ← Local deployment
│   └── health_check.sh               ← Service health check
├── references/
│   ├── SOP.md                        ← Standard operating procedure
│   └── troubleshooting.md            ← Troubleshooting guide
└── templates/
    ├── report.local.template.md      ← Local mode smoke test report template
    └── report.docker.template.md     ← Docker mode smoke test report template
```

## Standard Operating Procedure (SOP)

### Phase 1: Code Update Check

1. **Confirm current directory** - Verify that the current working directory is the DeerFlow project root
2. **Check Git status** - See whether there are uncommitted changes
3. **Pull the latest code** - Use `git pull origin main` to get the latest updates
4. **Confirm code update** - Verify that the latest code was pulled successfully

### Phase 2: Deployment Mode Selection and Environment Check

**Choose deployment mode**:
- Ask for user preference, or choose automatically based on network conditions
- Default to local installation mode

**Local mode environment check**:
1. **Check Node.js version** - Requires 22+
2. **Check pnpm** - Package manager
3. **Check uv** - Python package manager
4. **Check nginx** - Reverse proxy
5. **Check required ports** - Confirm that ports 2026, 3000, 8001, and 2024 are not occupied

**Docker mode environment check** (if Docker is selected):
1. **Check whether Docker is installed** - Run `docker --version`
2. **Check Docker daemon status** - Run `docker info`
3. **Check Docker Compose availability** - Run `docker compose version`
4. **Check required ports** - Confirm that port 2026 is not occupied

### Phase 3: Configuration Preparation

1. **Check whether config.yaml exists**
   - If it does not exist, run `make config` to generate it
   - If it already exists, check whether it needs an upgrade with `make config-upgrade`
2. **Check the .env file**
   - Verify that required environment variables are configured
   - Especially model API keys such as `OPENAI_API_KEY`

### Phase 4: Deployment Execution

**Local mode deployment**:
1. **Check dependencies** - Run `make check`
2. **Install dependencies** - Run `make install`
3. **(Optional) Pre-pull the sandbox image** - If needed, run `make setup-sandbox`
4. **Start services** - Run `make dev-daemon` (background mode, recommended) or `make dev` (foreground mode)
5. **Wait for startup** - Give all services enough time to start completely (90-120 seconds recommended)

**Docker mode deployment** (if Docker is selected):
1. **Initialize Docker environment** - Run `make docker-init`
2. **Start Docker services** - Run `make docker-start`
3. **Wait for startup** - Give all containers enough time to start completely (60 seconds recommended)

### Phase 5: Service Health Check

**Local mode health check**:
1. **Check process status** - Confirm that LangGraph, Gateway, Frontend, and Nginx processes are all running
2. **Check frontend service** - Visit `http://localhost:2026` and verify that the page loads
3. **Check API Gateway** - Verify the `http://localhost:2026/health` endpoint
4. **Check LangGraph service** - Verify the availability of relevant endpoints
5. **Frontend route smoke check** - Run `bash .agent/skills/smoke-test/scripts/frontend_check.sh` to verify key routes under `/workspace`

**Docker mode health check** (when using Docker):
1. **Check container status** - Run `docker ps` and confirm that all containers are running
2. **Check frontend service** - Visit `http://localhost:2026` and verify that the page loads
3. **Check API Gateway** - Verify the `http://localhost:2026/health` endpoint
4. **Check LangGraph service** - Verify the availability of relevant endpoints
5. **Frontend route smoke check** - Run `bash .agent/skills/smoke-test/scripts/frontend_check.sh` to verify key routes under `/workspace`

### Optional Functional Verification

1. **List available models** - Verify that model configuration loads correctly
2. **List available skills** - Verify that the skill directory is mounted correctly
3. **Simple chat test** - Send a simple message to verify the end-to-end flow

### Phase 6: Generate Test Report

1. **Collect all test results** - Summarize execution status for each phase
2. **Record encountered issues** - If anything fails, record the error details
3. **Generate the final report** - Use the template that matches the selected deployment mode to create the complete test report, including overall conclusion, detailed key test cases, and explicit frontend page / route results
4. **Provide follow-up recommendations** - Offer suggestions based on the test results

## Execution Rules

- **Follow the sequence** - Execute strictly in the order described above
- **Idempotency** - Every step should be safe to repeat
- **Error handling** - If a step fails, stop and report the issue, then provide troubleshooting suggestions
- **Detailed logging** - Record the execution result and status of each step
- **User confirmation** - Ask for confirmation before potentially risky operations such as overwriting config
- **Mode preference** - Prefer local mode to avoid network-related issues
- **Template requirement** - The final report must use the matching template under `templates/`; do not output a free-form summary instead of the template-based report
- **Report clarity** - The execution summary must include the overall pass/fail conclusion plus per-case result explanations, and frontend smoke check results must be listed explicitly in the report
- **Optional phase handling** - If functional verification is not executed, do not present it as a separate skipped phase in the final report

## Known Acceptable Warnings

The following warnings can appear during smoke testing and do not block a successful result:
- Feishu/Lark SSL errors in Gateway logs (certificate verification failure) can be ignored if that channel is not enabled
- Warnings in LangGraph logs about missing methods in the custom checkpointer, such as `adelete_for_runs` or `aprune`, do not affect the core functionality

## Key Tools

Use the following tools during execution:

1. **bash** - Run shell commands
2. **present_file** - Show generated reports and important files
3. **task_tool** - Organize complex steps with subtasks when needed

## Success Criteria

Smoke test pass criteria (local mode):
- [x] Latest code is pulled successfully
- [x] Local environment check passes (Node.js 22+, pnpm, uv, nginx)
- [x] Configuration files are set up correctly
- [x] `make check` passes
- [x] `make install` completes successfully
- [x] `make dev` starts successfully
- [x] All service processes run normally
- [x] Frontend page is accessible
- [x] Frontend route smoke check passes (`/workspace` key routes)
- [x] API Gateway health check passes
- [x] Test report is generated completely

Smoke test pass criteria (Docker mode):
- [x] Latest code is pulled successfully
- [x] Docker environment check passes
- [x] Configuration files are set up correctly
- [x] `make docker-init` completes successfully
- [x] `make docker-start` completes successfully
- [x] All Docker containers run normally
- [x] Frontend page is accessible
- [x] Frontend route smoke check passes (`/workspace` key routes)
- [x] API Gateway health check passes
- [x] Test report is generated completely

## Read Reference Files

Before starting execution, read the following reference files:
1. `references/SOP.md` - Detailed step-by-step operating instructions
2. `references/troubleshooting.md` - Common issues and solutions
3. `templates/report.local.template.md` - Local mode test report template
4. `templates/report.docker.template.md` - Docker mode test report template
