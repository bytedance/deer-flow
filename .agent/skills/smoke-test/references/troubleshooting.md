# Troubleshooting Guide

This document lists common issues encountered during DeerFlow smoke testing and how to resolve them.

## Code Update Issues

### Issue: `git pull` Fails with a Merge Conflict Warning

**Symptoms**:
```
error: Your local changes to the following files would be overwritten by merge
```

**Solutions**:
1. Option A: Commit local changes first
   ```bash
   git add .
   git commit -m "Save local changes"
   git pull origin main
   ```

2. Option B: Stash local changes
   ```bash
   git stash
   git pull origin main
   git stash pop  # Restore changes later if needed
   ```

3. Option C: Discard local changes (use with caution)
   ```bash
   git reset --hard HEAD
   git pull origin main
   ```

---

## Local Mode Environment Issues

### Issue: Node.js Version Is Too Old

**Symptoms**:
```
Node.js version is too old. Requires 22+, got x.x.x
```

**Solutions**:
1. Install or upgrade Node.js with nvm:
   ```bash
   nvm install 22
   nvm use 22
   ```

2. Or download and install it from the official website: https://nodejs.org/

3. Verify the version:
   ```bash
   node --version
   ```

---

### Issue: pnpm Is Not Installed

**Symptoms**:
```
command not found: pnpm
```

**Solutions**:
1. Install pnpm with npm:
   ```bash
   npm install -g pnpm
   ```

2. Or use the official installation script:
   ```bash
   curl -fsSL https://get.pnpm.io/install.sh | sh -
   ```

3. Verify the installation:
   ```bash
   pnpm --version
   ```

---

### Issue: uv Is Not Installed

**Symptoms**:
```
command not found: uv
```

**Solutions**:
1. Use the official installation script:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. macOS users can also install it with Homebrew:
   ```bash
   brew install uv
   ```

3. Verify the installation:
   ```bash
   uv --version
   ```

---

### Issue: Port Is Already in Use

**Symptoms**:
```
Error: listen EADDRINUSE: address already in use :::3000
```

**Solutions**:
1. Find the process using the port:
   ```bash
   lsof -i :3000  # macOS/Linux
   netstat -ano | findstr :3000  # Windows
   ```

2. Stop that process:
   ```bash
   kill -9 <PID>  # macOS/Linux
   taskkill /PID <PID> /F  # Windows
   ```

3. Or stop DeerFlow services first:
   ```bash
   make stop
   ```

---

## Local Mode Dependency Installation Issues

### Issue: `make install` Fails Due to Network Timeout

**Symptoms**:
Network timeouts or connection failures occur during dependency installation.

**Solutions**:
1. Configure pnpm to use a mirror registry:
   ```bash
   pnpm config set registry https://registry.npmmirror.com
   ```

2. Configure uv to use a mirror registry:
   ```bash
   uv pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
   ```

3. Retry the installation:
   ```bash
   make install
   ```

---

### Issue: Python Dependency Installation Fails

**Symptoms**:
Errors occur during `uv sync`.

**Solutions**:
1. Clean the uv cache:
   ```bash
   cd backend
   uv cache clean
   ```

2. Resync dependencies:
   ```bash
   cd backend
   uv sync
   ```

3. View detailed error logs:
   ```bash
   cd backend
   uv sync --verbose
   ```

---

### Issue: Frontend Dependency Installation Fails

**Symptoms**:
Errors occur during `pnpm install`.

**Solutions**:
1. Clean the pnpm cache:
   ```bash
   cd frontend
   pnpm store prune
   ```

2. Remove node_modules and the lock file:
   ```bash
   cd frontend
   rm -rf node_modules pnpm-lock.yaml
   ```

3. Reinstall:
   ```bash
   cd frontend
   pnpm install
   ```

---

## Local Mode Service Startup Issues

### Issue: Frontend Compilation Fails

**Symptoms**:
Compilation errors appear in `frontend.log`.

**Solutions**:
1. Check frontend logs:
   ```bash
   tail -f logs/frontend.log
   ```

2. Check whether Node.js version is 22+
3. Reinstall frontend dependencies:
   ```bash
   cd frontend
   rm -rf node_modules .next
   pnpm install
   ```

4. Restart services:
   ```bash
   make stop
   make dev-daemon
   ```

---

### Issue: Gateway Fails to Start

**Symptoms**:
Errors appear in `gateway.log`.

**Solutions**:
1. Check gateway logs:
   ```bash
   tail -f logs/gateway.log
   ```

2. Check whether config.yaml exists and has valid formatting
3. Check whether Python dependencies are complete:
   ```bash
   cd backend
   uv sync
   ```

4. Confirm that the Gateway process is running normally.

---

## Docker-Related Issues

### Issue: Docker Commands Cannot Run

**Symptoms**:
```
Cannot connect to the Docker daemon
```

**Solutions**:
1. Confirm that Docker Desktop is running
2. macOS: check whether the Docker icon appears in the top menu bar
3. Linux: run `sudo systemctl start docker`
4. Run `docker info` again to verify

---

### Issue: `make docker-init` Fails to Pull the Image

**Symptoms**:
```
Error pulling image: connection refused
```

**Solutions**:
1. Check network connectivity
2. Configure a Docker image mirror if needed
3. Check whether a proxy is required
4. Switch to local installation mode if necessary (recommended)

---

## Configuration File Issues

### Issue: config.yaml Is Missing or Invalid

**Symptoms**:
```
Error: could not read config.yaml
```

**Solutions**:
1. Regenerate the configuration file:
   ```bash
   make config
   ```

2. Check YAML syntax:
   - Make sure indentation is correct (use 2 spaces)
   - Make sure there are no tab characters
   - Check that there is a space after each colon

3. Use a YAML validation tool to check the format

---

### Issue: Model API Key Is Not Configured

**Symptoms**:
After services start, API requests fail with authentication errors.

**Solutions**:
1. Edit the .env file and add the API key:
   ```bash
   OPENAI_API_KEY=your-actual-api-key-here
   ```

2. Restart services (local mode):
   ```bash
   make stop
   make dev-daemon
   ```

3. Restart services (Docker mode):
   ```bash
   make docker-stop
   make docker-start
   ```

4. Confirm that the model configuration in config.yaml references the environment variable correctly

---

## Service Health Check Issues

