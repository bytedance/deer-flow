# Port Configuration Changes Summary

This document summarizes all the changes made to make DeerFlow's frontend and backend ports configurable through environment variables.

## Overview

Previously, DeerFlow used hardcoded ports:
- Backend: 8000
- Frontend: 3000

Now, these ports are configurable through environment variables while maintaining backward compatibility with the original defaults.

## Changes Made

### 1. Environment Configuration Files

#### `.env.example`
- Added `BACKEND_PORT=8000` and `FRONTEND_PORT=3000` variables
- Updated `NEXT_PUBLIC_API_URL` to use `${BACKEND_PORT}` variable
- Updated `ALLOWED_ORIGINS` to use `${FRONTEND_PORT}` variable

#### `web/.env.example`
- Added port configuration variables
- Updated `NEXT_PUBLIC_API_URL` to use `${BACKEND_PORT}` variable

### 2. Backend Changes

#### `server.py`
- Added `import os` for environment variable access
- Modified `--port` argument default to use `int(os.getenv("BACKEND_PORT", "8000"))`
- Updated help text to indicate environment variable usage

#### `src/server/app.py`
- Already correctly used `ALLOWED_ORIGINS` environment variable (no changes needed)

### 3. Frontend Changes

#### `web/package.json`
- Updated `dev` script to use `--port ${FRONTEND_PORT:-3000}`
- Updated `start` script to use `--port ${FRONTEND_PORT:-3000}`
- Updated `scan` script to use `${FRONTEND_PORT:-3000}` for both Next.js and react-scan

### 4. Docker Configuration

#### `Dockerfile` (Backend)
- Added `ARG BACKEND_PORT=8000`
- Updated `EXPOSE` to use `${BACKEND_PORT}`
- Modified `CMD` to use environment variable for port

#### `web/Dockerfile` (Frontend)
- Added `ARG FRONTEND_PORT=3000`
- Updated `EXPOSE` and `ENV PORT` to use `${FRONTEND_PORT}`

#### `docker-compose.yml`
- Updated backend service:
  - Added build arg: `BACKEND_PORT=${BACKEND_PORT:-8000}`
  - Updated ports mapping: `"${BACKEND_PORT:-8000}:${BACKEND_PORT:-8000}"`
- Updated frontend service:
  - Added build arg: `FRONTEND_PORT=${FRONTEND_PORT:-3000}`
  - Updated ports mapping: `"${FRONTEND_PORT:-3000}:${FRONTEND_PORT:-3000}"`

#### `web/docker-compose.yml`
- Added `FRONTEND_PORT: ${FRONTEND_PORT:-3000}` build arg
- Updated ports mapping to use `${FRONTEND_PORT:-3000}`

### 5. Documentation

#### `README.md`
- Added "Port Configuration" section explaining how to customize ports
- Provided examples of environment variable usage
- Explained use cases for custom ports

## Usage

### Development Mode

Set environment variables in your `.env` file:

```bash
BACKEND_PORT=8080
FRONTEND_PORT=3001
NEXT_PUBLIC_API_URL="http://localhost:8080/api"
ALLOWED_ORIGINS=http://localhost:3001
```

### Docker Compose

The same `.env` file works with Docker Compose:

```bash
# Set custom ports in .env
BACKEND_PORT=8080
FRONTEND_PORT=3001

# Run with custom ports
docker compose up
```

### Command Line Override

You can still override ports via command line:

```bash
# Backend
python server.py --port 8080

# Frontend (in web directory)
npm run dev -- --port 3001
```

## Backward Compatibility

All changes maintain backward compatibility:
- Default ports remain 8000 (backend) and 3000 (frontend)
- Existing deployments without environment variables will continue to work
- Command line arguments still work and take precedence over environment variables

## Testing

A comprehensive test script `test_port_config.py` was created to verify:
- Environment file structure
- Docker configuration
- Package.json configuration
- Backend port environment variable support

All tests pass, confirming the implementation works correctly.

## Files Modified

1. `.env.example`
2. `web/.env.example`
3. `server.py`
4. `web/package.json`
5. `Dockerfile`
6. `web/Dockerfile`
7. `docker-compose.yml`
8. `web/docker-compose.yml`
9. `README.md`

## Files Created

1. `test_port_config.py` - Test script to verify changes
2. `PORT_CONFIGURATION_CHANGES.md` - This summary document

## Benefits

1. **Flexibility**: Users can now run DeerFlow on any available ports
2. **Multi-instance Support**: Multiple DeerFlow instances can run simultaneously
3. **Infrastructure Compatibility**: Easier deployment in environments with specific port requirements
4. **Development Convenience**: Avoids port conflicts during development
5. **Backward Compatibility**: Existing setups continue to work without changes