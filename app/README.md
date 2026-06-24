# DeerFlow Desktop App

A [Tauri](https://tauri.app/) wrapper that packages DeerFlow into a native desktop application for macOS, Linux, and Windows. The app window loads the DeerFlow workspace directly — no browser required.

## How It Works

```
┌──────────────────────────────────────┐
│  Tauri Window (native desktop app)   │
│  └── WebView → localhost:2026        │
└──────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────┐
│  DeerFlow services (local)           │
│  ├── nginx          :2026 (unified)  │
│  ├── Next.js        :3000            │
│  ├── Gateway API    :8001            │
│  └── LangGraph      :2024            │
└──────────────────────────────────────┘
```

The Tauri shell is intentionally thin — it provides a native window, titlebar, and OS integration while all application logic remains in the existing DeerFlow stack. No code duplication, and every DeerFlow update is automatically reflected in the desktop app.

## Directory Structure

```
app/
├── src/
│   └── index.html        # WebView entry: loads localhost:2026/workspace
├── src-tauri/
│   ├── Cargo.toml
│   ├── tauri.conf.json   # productName, window size, devUrl
│   └── src/
│       ├── main.rs
│       └── lib.rs
├── init.sh               # Start / restart all DeerFlow backend services
└── README.md
```

## Prerequisites

- [Rust](https://rustup.rs/) 1.77.2+
- All DeerFlow prerequisites: Node.js 22+, pnpm, uv, nginx (see root [README](../README.md))

## Getting Started

### 1. Start the backend services

From the `app/` directory:

```bash
./init.sh
```

This starts LangGraph, Gateway API, Frontend, and nginx (or restarts them if already running). Wait until you see the services ready message before launching the desktop window.

### 2. Development mode (hot-reload)

```bash
cd app/src-tauri
source "$HOME/.cargo/env"
cargo tauri dev
```

The Tauri window opens and loads `http://localhost:2026/workspace` directly. Changes to the frontend are reflected live.

### 3. Build a release bundle

```bash
cd app/src-tauri
source "$HOME/.cargo/env"
cargo tauri build
```

Output locations:

| Platform | Path |
|----------|------|
| macOS    | `src-tauri/target/release/bundle/macos/Asuka.app` |
| Linux    | `src-tauri/target/release/bundle/appimage/asuka_*.AppImage` |
| Windows  | `src-tauri/target/release/bundle/msi/Asuka_*.msi` |

> The app bundles only the Tauri shell. DeerFlow backend services still need to be running locally when you launch the app.

## Updating DeerFlow

Pull the latest code and rebuild:

```bash
git pull
make install          # reinstall frontend + backend deps if needed
cd app/src-tauri
cargo tauri build
```

## Troubleshooting

**Blank window** — Backend services are not running. Run `./init.sh` first.

**Build fails** — Make sure the full Rust toolchain is installed:
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
# Linux also needs:
sudo apt-get install -y build-essential libwebkit2gtk-4.1-dev libssl-dev
```

**Port conflict** — If any of the ports (2024, 2026, 3000, 8001) are in use, stop existing services with `make stop` from the project root.

**Chinese text or emoji not rendering correctly on Linux** — The WebView relies on system fonts. Install the required CJK and emoji fonts:
```bash
sudo apt-get install -y fonts-noto-cjk
sudo apt-get install -y fonts-noto-color-emoji fonts-symbola
```

## Acknowledgements

This desktop wrapper is built on top of [DeerFlow](https://github.com/bytedance/deer-flow) by [ByteDance](https://github.com/bytedance), an open-source super agent harness licensed under MIT. All core agent logic, frontend, and backend code belong to the DeerFlow project and its contributors.

## Author

[Anders Hsueh](https://github.com/andershsueh)
