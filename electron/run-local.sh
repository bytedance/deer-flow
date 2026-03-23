#!/bin/bash
#
# DeerFlow Desktop - Local/Isolated Electron Runner
# 
# Downloads and runs Electron locally without system npm install
# Uses portable Electron binary in electron/.local/
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DIR="$SCRIPT_DIR/.local"
ELECTRON_VERSION="33.2.1"

# Detect platform
PLATFORM=""
ARCH="$(uname -m)"
case "$(uname -s)" in
    Darwin*) PLATFORM="darwin" ;;
    Linux*)  PLATFORM="linux" ;;
    CYGWIN*|MINGW*|MSYS*) PLATFORM="win32" ;;
    *) echo "Unsupported platform: $(uname -s)"; exit 1 ;;
esac

# Map arch names
if [ "$ARCH" = "x86_64" ]; then
    ARCH="x64"
elif [ "$ARCH" = "arm64" ]; then
    ARCH="arm64"
fi

echo "Platform: $PLATFORM, Arch: $ARCH"

# Create local directory
mkdir -p "$LOCAL_DIR"

# Download Electron if not exists
ELECTRON_DIR="$LOCAL_DIR/electron-$ELECTRON_VERSION-$PLATFORM-$ARCH"
if [ ! -d "$ELECTRON_DIR" ]; then
    echo "Downloading Electron $ELECTRON_VERSION for $PLATFORM-$ARCH..."
    
    cd "$LOCAL_DIR"
    
    FILENAME="electron-v${ELECTRON_VERSION}-${PLATFORM}-${ARCH}.zip"
    URL="https://github.com/electron/electron/releases/download/v${ELECTRON_VERSION}/${FILENAME}"
    
    if command -v curl >/dev/null 2>&1; then
        curl -L -o "$FILENAME" "$URL" --progress-bar
    elif command -v wget >/dev/null 2>&1; then
        wget -q --show-progress -O "$FILENAME" "$URL"
    else
        echo "Need curl or wget to download Electron"
        exit 1
    fi
    
    echo "Extracting..."
    unzip -q "$FILENAME" -d "$ELECTRON_DIR"
    rm "$FILENAME"
    
    echo "✓ Electron downloaded to $ELECTRON_DIR"
fi

# Find Electron binary
if [ "$PLATFORM" = "win32" ]; then
    ELECTRON_BIN="$ELECTRON_DIR/electron.exe"
else
    ELECTRON_BIN="$ELECTRON_DIR/Electron.app/Contents/MacOS/Electron"
    if [ ! -f "$ELECTRON_BIN" ]; then
        # Linux or other
        ELECTRON_BIN="$ELECTRON_DIR/electron"
    fi
fi

if [ ! -f "$ELECTRON_BIN" ]; then
    echo "Error: Electron binary not found at $ELECTRON_BIN"
    exit 1
fi

echo "Starting DeerFlow Desktop..."
echo ""

# Run Electron with our app
cd "$SCRIPT_DIR"
exec "$ELECTRON_BIN" . "$@"
