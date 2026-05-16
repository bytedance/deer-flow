# DeerFlow Smoke Test Standard Operating Procedure (SOP)

This document describes the detailed operating steps for each phase of the DeerFlow smoke test.

## Phase 1: Code Update Check

### 1.1 Confirm Current Directory

**Objective**: Verify that the current working directory is the DeerFlow project root.

**Steps**:
1. Run `pwd` to view the current working directory
2. Check whether the directory contains the following files/directories:
   - `Makefile`
   - `backend/`
   - `frontend/`
   - `config.example.yaml`

**Success Criteria**: The current directory contains all of the files/directories listed above.

---

### 1.2 Check Git Status

**Objective**: Check whether there are uncommitted changes.

**Steps**:
1. Run `git status`
2. Check whether the output includes "Changes not staged for commit" or "Untracked files"

**Notes**:
- If there are uncommitted changes, recommend that the user commit or stash them first to avoid conflicts while pulling
- If the user confirms that they want to continue, this step can be skipped

---

### 1.3 Pull the Latest Code

**Objective**: Fetch the latest code updates.

**Steps**:
1. Run `git fetch origin main`
2. Run `git pull origin main`

**Success Criteria**:
- The commands succeed without errors
- The output shows "Already up to date" or indicates that new commits were pulled successfully

---

### 1.4 Confirm Code Update

**Objective**: Verify that the latest code was pulled successfully.

**Steps**:
1. Run `git log -1 --oneline` to view the latest commit
2. Record the commit hash and message

---

## Phase 2: Deployment Mode Selection and Environment Check

### 2.1 Choose Deployment Mode

**Objective**: Decide whether to use local mode or Docker mode.

**Decision Flow**:
1. Prefer local mode first to avoid network-related issues
2. If the user explicitly requests Docker, use Docker
3. If Docker network issues occur, switch to local mode automatically

---

### 2.2 Local Mode Environment Check

**Objective**: Verify that local development environment dependencies are satisfied.

#### 2.2.1 Check Node.js Version

**Steps**:
1. If nvm is used, run `nvm use 22` to switch to Node 22+
2. Run `node --version`

**Success Criteria**: Version >= 22.x

**Failure Handling**:
- If the version is too low, ask the user to install/switch Node.js with nvm:
  ```bash
  nvm install 22
  nvm use 22
  ```
- Or install it from the official website: https://nodejs.org/

---

#### 2.2.2 Check pnpm

**Steps**:
1. Run `pnpm --version`

**Success Criteria**: The command returns pnpm version information.

**Failure Handling**:
- If pnpm is not installed, ask the user to install it with `npm install -g pnpm`

---

#### 2.2.3 Check uv

**Steps**:
1. Run `uv --version`

**Success Criteria**: The command returns uv version information.

**Failure Handling**:
- If uv is not installed, ask the user to install uv

---

#### 2.2.4 Check nginx

**Steps**:
1. Run `nginx -v`

**Success Criteria**: The command returns nginx version information.

**Failure Handling**:
- macOS: install with Homebrew using `brew install nginx`
- Linux: install using the system package manager

---

#### 2.2.5 Check Required Ports

**Steps**:
1. Run the following commands to check ports:
   ```bash
   lsof -i :2026  # Main port
   lsof -i :3000  # Frontend
   lsof -i :8001  # Gateway
   lsof -i :2024  # LangGraph
   ```

**Success Criteria**: All ports are free, or they are occupied only by DeerFlow-related processes.

**Failure Handling**:
- If a port is occupied, ask the user to stop the related process

---

### 2.3 Docker Mode Environment Check (If Docker Is Selected)

#### 2.3.1 Check Whether Docker Is Installed

**Steps**:
1. Run `docker --version`

**Success Criteria**: The command returns Docker version information, such as "Docker version 24.x.x".

---

#### 2.3.2 Check Docker Daemon Status

**Steps**:
1. Run `docker info`

**Success Criteria**: The command runs successfully and shows Docker system information.

**Failure Handling**:
- If it fails, ask the user to start Docker Desktop or the Docker service

---

#### 2.3.3 Check Docker Compose Availability

**Steps**:
1. Run `docker compose version`

**Success Criteria**: The command returns Docker Compose version information.

---

#### 2.3.4 Check Required Ports

**Steps**:
1. Run `lsof -i :2026` (macOS/Linux) or `netstat -ano | findstr :2026` (Windows)

**Success Criteria**: Port 2026 is free, or it is occupied only by a DeerFlow-related process.

**Failure Handling**:
- If the port is occupied by another process, ask the user to stop that process or change the configuration

---

## Phase 3: Configuration Preparation

### 3.1 Check config.yaml

**Steps**:
1. Check whether `config.yaml` exists
2. If it does not exist, run `make config`
3. If it already exists, consider running `make config-upgrade` to merge new fields

**Validation**:
- Check whether at least one model is configured in config.yaml
- Check whether the model configuration references the correct environment variables

---

### 3.2 Check the .env File

**Steps**:
1. Check whether the `.env` file exists
2. If it does not exist, copy it from `.env.example`
3. Check whether the following environment variables are configured:
   - `OPENAI_API_KEY` (or other model API keys)
   - Other required settings

---

## Phase 4: Deployment Execution

### 4.1 Local Mode Deployment

#### 4.1.1 Check Dependencies

**Steps**:
1. Run `make check`

**Description**: This command validates all required tools (Node.js 22+, pnpm, uv, nginx).

---

#### 4.1.2 Install Dependencies

**Steps**:
1. Run `make install`

**Description**: This command installs both backend and frontend dependencies.

**Notes**:
- This step may take some time
- If network issues cause failures, try using a closer or mirrored package registry

---

#### 4.1.3 (Optional) Pre-pull the Sandbox Image

**Steps**:
1. If Docker / Container sandbox is used, run `make setup-sandbox`

**Description**: This step is optional and not needed for local sandbox mode.

---

#### 4.1.4 Start Services

**Steps**:
1. Run `make dev-daemon` (background mode)

**Description**: This command starts all services (LangGraph, Gateway, Frontend, Nginx).

**Notes**:
- `make dev` runs in the foreground and stops with Ctrl+C
- `make dev-daemon` runs in the background
- Use `make stop` to stop services

---

#### 4.1.5 Wait for Services to Start

**Steps**:
1. Wait 90-120 seconds for all services to start completely
2. You can monitor startup progress by checking these log files:
   - `logs/langgraph.log`
   - `logs/gateway.log`
   - `logs/frontend.log`
   - `logs/nginx.log`

---

### 4.2 Docker Mode Deployment (If Docker Is Selected)

#### 4.2.1 Initialize the Docker Environment

**Steps**:
1. Run `make docker-init`

**Description**: This command pulls the sandbox image if needed.

---

#### 4.2.2 Start Docker Services

**Steps**:
1. Run `make docker-start`

**Description**: This command builds and starts all required Docker containers.

---

#### 4.2.3 Wait for Services to Start

**Steps**:
1. Wait 60-90 seconds for all services to start completely
2. You can run `make docker-logs` to monitor startup progress

---

## Phase 5: Service Health Check

### 5.1 Local Mode Health Check

#### 5.1.1 Check Process Status

**Steps**:
1. Run the following command to check processes:
   ```bash
   ps aux | grep -E "(langgraph|uvicorn|next|nginx)" | grep -v grep
   ```

**Success Criteria**: Confirm that the following processes are running:
- LangGraph (`langgraph dev`)
- Gateway (`uvicorn app.gateway.app:app`)
- Frontend (`next dev` or `next start`)
- Nginx (`nginx`)

---

#### 5.1.2 Check Frontend Service

**Steps**:
1. Use curl or a browser to visit `http://localhost:2026`
2. Verify that the page loads normally

**Example curl command**:
```bash
curl -I http://localhost:2026
```

**Success Criteria**: Returns an HTTP 200 status code.

---

#### 5.1.3 Check API Gateway

**Steps**:
1. Visit `http://localhost:2026/health`

**Example curl command**:
```bash
curl http://localhost:2026/health
```

**Success Criteria**: Returns health status JSON.

---

#### 5.1.4 Check LangGraph Service

**Steps**:
1. Visit relevant LangGraph endpoints to verify availability

---

### 5.2 Docker Mode Health Check (When Using Docker)

#### 5.2.1 Check Container Status

**Steps**:
1. Run `docker ps`
2. Confirm that the following containers are running:
   - `deer-flow-nginx`
   - `deer-flow-frontend`
   - `deer-flow-gateway`
   - `deer-flow-langgraph` (if not in gateway mode)

---

#### 5.2.2 Check Frontend Service

**Steps**:
1. Use curl or a browser to visit `http://localhost:2026`
2. Verify that the page loads normally

**Example curl command**:
```bash
curl -I http://localhost:2026
```

**Success Criteria**: Returns an HTTP 200 status code.

---

#### 5.2.3 Check API Gateway

**Steps**:
1. Visit `http://localhost:2026/health`

**Example curl command**:
```bash
curl http://localhost:2026/health
```

**Success Criteria**: Returns health status JSON.

---

#### 5.2.4 Check LangGraph Service

**Steps**:
1. Visit relevant LangGraph endpoints to verify availability

---

## Optional Functional Verification

### 6.1 List Available Models

**Steps**: Verify the model list through the API or UI.

---

### 6.2 List Available Skills

**Steps**: Verify the skill list through the API or UI.

---

### 6.3 Simple Chat Test

**Steps**: Send a simple message to test the complete workflow.

---

## Phase 6: Generate the Test Report

### 6.1 Collect Test Results

Summarize the execution status of each phase and record successful and failed items.

### 6.2 Record Issues

If anything fails, record detailed error information.

### 6.3 Generate the Report

Use the template to create a complete test report.

### 6.4 Provide Recommendations

Provide follow-up recommendations based on the test results.
