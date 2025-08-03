# DeerFlow Port Configuration Changes

## Why We Started This Exercise

The motivation for this project came from a common frustration with open source repositories: **hardcoded ports that cause deployment conflicts**. 

### The Problem
- Most GitHub open source projects default to frontend port 3000 and backend port 8000
- This creates conflicts when:
  - Running multiple applications simultaneously
  - Deploying in environments with port restrictions
  - Working in development teams where ports are already allocated
  - Integrating with existing infrastructure that uses these common ports

### The Goal
Transform DeerFlow from using hardcoded ports to a flexible, environment-variable-driven port configuration system that:
- Maintains backward compatibility
- Works across all deployment methods (development, Docker, Docker Compose)
- Provides a template for other open source projects to follow

## Summary of All Changes Made

### 1. Environment Variable Infrastructure

**Files Modified:**
- `.env.example`
- `web/.env.example`

**Changes:**
```bash
# Added port configuration variables
BACKEND_PORT=8000
FRONTEND_PORT=3000

# Updated dependent variables to use port variables
NEXT_PUBLIC_API_URL="http://localhost:${BACKEND_PORT}/api"
ALLOWED_ORIGINS=http://localhost:${FRONTEND_PORT}
```

**Why:** Centralized port configuration that all other components can reference.

### 2. Backend Server Configuration

**File Modified:** `server.py`

**Changes:**
- Added `import os` for environment variable access
- Modified port argument default: `default=int(os.getenv("BACKEND_PORT", "8000"))`
- Updated help text to indicate environment variable usage

**Before:**
```python
parser.add_argument(
    "--port",
    type=int,
    default=8000,  # Hardcoded
    help="Port to bind the server to (default: 8000)",
)
```

**After:**
```python
parser.add_argument(
    "--port",
    type=int,
    default=int(os.getenv("BACKEND_PORT", "8000")),  # Environment-driven
    help="Port to bind the server to (default: from BACKEND_PORT env var or 8000)",
)
```

**Why:** Allows the backend to respect environment variables while maintaining command-line override capability.

### 3. Frontend Configuration

**File Modified:** `web/package.json`

**Changes:**
Updated all npm scripts to use environment variables:

**Before:**
```json
{
  "dev": "dotenv -f ../.env -- next dev --turbo",
  "start": "next start",
  "scan": "next dev & npx react-scan@latest localhost:3000"
}
```

**After:**
```json
{
  "dev": "dotenv -f ../.env -- next dev --turbo --port ${FRONTEND_PORT:-3000}",
  "start": "next start --port ${FRONTEND_PORT:-3000}",
  "scan": "next dev --port ${FRONTEND_PORT:-3000} & npx react-scan@latest localhost:${FRONTEND_PORT:-3000}"
}
```

**Why:** Ensures the frontend respects the configured port in all execution modes.

### 4. Docker Configuration

**Files Modified:**
- `Dockerfile` (backend)
- `web/Dockerfile` (frontend)
- `docker-compose.yml`
- `web/docker-compose.yml`

**Backend Dockerfile Changes:**
```dockerfile
# Before
EXPOSE 8000
CMD ["uv", "run", "python", "server.py", "--host", "0.0.0.0", "--port", "8000"]

# After
ARG BACKEND_PORT=8000
EXPOSE ${BACKEND_PORT}
CMD ["sh", "-c", "uv run python server.py --host 0.0.0.0 --port ${BACKEND_PORT:-8000}"]
```

**Frontend Dockerfile Changes:**
```dockerfile
# Before
EXPOSE 3000
ENV PORT=3000

# After
ARG FRONTEND_PORT=3000
EXPOSE ${FRONTEND_PORT}
ENV PORT=${FRONTEND_PORT}
```

**Docker Compose Changes:**
```yaml
# Before
services:
  backend:
    ports:
      - "8000:8000"
  frontend:
    ports:
      - "3000:3000"

# After
services:
  backend:
    build:
      args:
        - BACKEND_PORT=${BACKEND_PORT:-8000}
    ports:
      - "${BACKEND_PORT:-8000}:${BACKEND_PORT:-8000}"
  frontend:
    build:
      args:
        - FRONTEND_PORT=${FRONTEND_PORT:-3000}
    ports:
      - "${FRONTEND_PORT:-3000}:${FRONTEND_PORT:-3000}"
```

**Why:** Ensures Docker deployments respect environment variables and can run on custom ports.

### 5. Documentation Updates

**File Modified:** `README.md`

**Added Section:**
```markdown
### Port Configuration

DeerFlow allows you to customize the ports used by both the backend and frontend services through environment variables:

```bash
# In your .env file
BACKEND_PORT=8080    # Default: 8000
FRONTEND_PORT=3001   # Default: 3000
```

This is particularly useful when:
- You have port conflicts with other services
- You want to run multiple instances of DeerFlow
- You need to deploy on specific ports for your infrastructure
```

**Why:** Users need clear documentation on how to use the new port configuration features.

### 6. Quality Assurance

**Files Created:**
- `test_port_config.py` - Comprehensive test suite
- `PORT_CONFIGURATION_CHANGES.md` - Technical documentation
- `df_changes.md` - This summary document

**Test Coverage:**
- Environment file structure validation
- Docker configuration validation
- Package.json configuration validation
- Backend environment variable integration
- All tests pass ✅

## Implementation Highlights

### Backward Compatibility
- **Zero Breaking Changes:** Existing deployments continue to work without modification
- **Default Values Preserved:** Ports 8000 and 3000 remain the defaults
- **Command Line Override:** Existing command-line arguments still work and take precedence

### Flexibility Achieved
- **Environment Variable Control:** Set ports via `.env` file
- **Docker Support:** Full Docker and Docker Compose integration
- **Multi-Instance Ready:** Run multiple DeerFlow instances on different ports
- **Infrastructure Friendly:** Deploy in environments with port restrictions

### Best Practices Followed
- **DRY Principle:** Port configuration centralized in environment variables
- **Fail-Safe Defaults:** Sensible fallbacks if environment variables aren't set
- **Comprehensive Testing:** Automated validation of all changes
- **Clear Documentation:** User-friendly instructions and examples

## Usage Examples

### Development with Custom Ports
```bash
# .env file
BACKEND_PORT=8080
FRONTEND_PORT=3001
NEXT_PUBLIC_API_URL="http://localhost:8080/api"
ALLOWED_ORIGINS=http://localhost:3001

# Start development servers
./bootstrap.sh -d
# Backend runs on :8080, Frontend on :3001
```

### Docker Deployment
```bash
# Same .env file works with Docker
docker compose up
# Automatically uses ports from environment variables
```

### Multiple Instances
```bash
# Instance 1 (.env)
BACKEND_PORT=8000
FRONTEND_PORT=3000

# Instance 2 (.env.instance2)
BACKEND_PORT=8080
FRONTEND_PORT=3001

# Run both simultaneously without conflicts
```

## Impact and Benefits

### For Users
- **No More Port Conflicts:** Run DeerFlow alongside other applications
- **Flexible Deployment:** Deploy in any environment with custom port requirements
- **Multi-Instance Support:** Run multiple instances for different projects
- **Zero Migration Effort:** Existing setups continue to work unchanged

### For the Project
- **Professional Standards:** Follows industry best practices for configuration management
- **Deployment Friendly:** Easier adoption in enterprise and cloud environments
- **Community Contribution:** Provides a template for other open source projects
- **Maintainability:** Centralized configuration reduces maintenance overhead

### For the Open Source Community
- **Best Practice Example:** Demonstrates how to implement flexible port configuration
- **Contribution Template:** Shows how to make infrastructure improvements
- **Documentation Standard:** Comprehensive change documentation and testing

## Conclusion

This exercise successfully transformed DeerFlow from a hardcoded-port application to a flexible, environment-driven system. The changes address a common pain point in open source deployments while maintaining full backward compatibility.

The implementation serves as both a practical improvement to DeerFlow and a template for how other open source projects can eliminate hardcoded infrastructure assumptions.

**Result:** DeerFlow is now deployment-ready for any environment, from local development to enterprise production systems, without the common frustration of port conflicts that plague many open source projects.