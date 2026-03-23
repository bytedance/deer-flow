# DeerFlow Desktop (Electron Wrapper)

A minimal Electron desktop wrapper for DeerFlow. This is a thin wrapper that loads the DeerFlow web UI from `http://localhost:2026` - it does not bundle or modify DeerFlow core code.

## License

**MIT License** - Same as DeerFlow. See [LICENSE](../LICENSE) for details.

## Prerequisites

1. **DeerFlow backend must be running:**
   ```bash
   cd /path/to/deer-flow
   make docker-start
   ```

2. **Node.js 18+ and npm**

## Installation

From the project root:

```bash
make desktop-install
```

Or manually:

```bash
cd electron
npm install
```

## Usage

### Development Mode

```bash
# Terminal 1: Start backend
make docker-start

# Terminal 2: Start desktop wrapper
make desktop-dev
```

### Production Build

```bash
# Build for current platform
make desktop-build

# Build for specific platforms
make desktop-build-mac      # macOS DMG + zip
make desktop-build-win      # Windows NSIS installer
make desktop-build-linux    # Linux AppImage + deb
```

Built apps will be in `electron/dist/`.

## How It Works

```
┌─────────────────────────────────────┐
│        DeerFlow Desktop             │
│    (Electron BrowserWindow)         │
│         ~100 lines of code          │
└──────────────────┬──────────────────┘
                   │ loads
                   ▼
        http://localhost:2026
                   │
┌──────────────────┴──────────────────┐
│         DeerFlow Backend            │
│   (Docker: nginx + gateway +        │
│    langgraph + frontend)            │
│        ~100k+ lines of code         │
└─────────────────────────────────────┘
```

This wrapper is intentionally minimal:

- **No backend spawning** - User runs `make docker-start` separately
- **No code modification** - Zero changes to DeerFlow core
- **Single window** - No complex multi-window management
- **No IPC surface** - Just a browser shell with native feel

## Features

- Native desktop window (macOS, Windows, Linux)
- Backend auto-detection with waiting screen
- External links open in system browser
- Clean title bar (macOS hiddenInset style)
- MIT licensed (free forever)

## Troubleshooting

### "Waiting for DeerFlow backend..."

The backend isn't running. Start it with:

```bash
make docker-start
```

### Blank screen

Check that DeerFlow is accessible:

```bash
curl http://localhost:2026/health
```

Should return `{"status":"healthy"}`.

## Architecture Notes

This is a **thin wrapper** pattern, contrasting with AetherArena's **thick client** approach:

| Aspect | DeerFlow Wrapper | AetherArena |
|--------|------------------|-------------|
| Backend | External (Docker) | Spawned by Electron |
| IPC | None (pure browser) | Rich IPC layer |
| Windows | Single | Multiple (chat, artifacts, etc.) |
| Bundle size | ~150MB | ~500MB+ |
| Lines of code | ~100 | ~15,000 |

The thin wrapper trades "native feel" for "simplicity and maintainability."
