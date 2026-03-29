#!/usr/bin/env bash
# minimax-docx Environment Setup & Initialization Script
# Supports: macOS (Homebrew), Linux (apt/dnf/pacman), WSL
# License: MIT
set -euo pipefail

# Force English output for dotnet CLI
export DOTNET_CLI_UI_LANGUAGE=en

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DOTNET_DIR="$SCRIPT_DIR/dotnet"
LOG_FILE="$PROJECT_DIR/.setup.log"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; }
info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
step()  { echo -e "\n${BLUE}=== $* ===${NC}"; }

# --- Detect OS & Package Manager ---
detect_platform() {
    OS="unknown"
    PKG_MGR="unknown"
    ARCH="$(uname -m)"

    case "$(uname -s)" in
        Darwin)
            OS="macos"
            if command -v brew &>/dev/null; then
                PKG_MGR="brew"
            else
                PKG_MGR="none"
            fi
            ;;
        Linux)
            OS="linux"
            if [ -f /etc/os-release ]; then
                . /etc/os-release
                case "$ID" in
                    ubuntu|debian|linuxmint|pop)
                        PKG_MGR="apt"
                        ;;
                    fedora|rhel|centos|rocky|alma)
                        PKG_MGR="dnf"
                        ;;
                    arch|manjaro|endeavouros)
                        PKG_MGR="pacman"
                        ;;
                    opensuse*|sles)
                        PKG_MGR="zypper"
                        ;;
                    alpine)
                        PKG_MGR="apk"
                        ;;
                    *)
                        PKG_MGR="unknown"
                        ;;
                esac
            fi
            # Detect WSL
            if grep -qi microsoft /proc/version 2>/dev/null; then
                OS="wsl"
            fi
            ;;
        MINGW*|MSYS*|CYGWIN*)
            OS="windows-git-bash"
            PKG_MGR="none"
            ;;
    esac

    echo "Platform: $OS ($ARCH), Package Manager: $PKG_MGR"
}

# --- .NET SDK Installation ---
install_dotnet() {
    step "Checking .NET SDK"

    if command -v dotnet &>/dev/null; then
        local ver
        ver=$(dotnet --version 2>/dev/null || echo "0")
        local major="${ver%%.*}"
        if [ "$major" -ge 8 ] 2>/dev/null; then
            log "dotnet $ver already installed (>= 8.0 OK)"
            return 0
        else
            warn "dotnet $ver found but < 8.0, upgrading..."
        fi
    fi

    info "Installing .NET SDK..."
    case "$PKG_MGR" in
        brew)
            brew install --cask dotnet-sdk
            ;;
        apt)
            # Microsoft package repo for Ubuntu/Debian
            if ! dpkg -l dotnet-sdk-8.0 &>/dev/null 2>&1; then
                info "Adding Microsoft package repository..."
                sudo apt-get update -qq
                sudo apt-get install -y -qq wget apt-transport-https
                wget -q "https://dot.net/v1/dotnet-install.sh" -O /tmp/dotnet-install.sh
                chmod +x /tmp/dotnet-install.sh
                /tmp/dotnet-install.sh --channel 8.0 --install-dir "$HOME/.dotnet"
                export PATH="$HOME/.dotnet:$PATH"
                echo 'export PATH="$HOME/.dotnet:$PATH"' >> "$HOME/.bashrc"
            fi
            ;;
        dnf)
            sudo dnf install -y dotnet-sdk-8.0
            ;;
        pacman)
            sudo pacman -S --noconfirm dotnet-sdk
            ;;
        zypper)
            sudo zypper install -y dotnet-sdk-8.0
            ;;
        apk)
            apk add --no-cache dotnet8-sdk
            ;;
        none)
            if [ "$OS" = "windows-git-bash" ]; then
                fail "On Windows, install .NET SDK from: https://dotnet.microsoft.com/download"
                fail "Then restart your terminal and re-run this script."
                return 1
            fi
            # Fallback: use Microsoft install script
            info "Using Microsoft install script..."
            wget -q "https://dot.net/v1/dotnet-install.sh" -O /tmp/dotnet-install.sh || \
                curl -sSL "https://dot.net/v1/dotnet-install.sh" -o /tmp/dotnet-install.sh
            chmod +x /tmp/dotnet-install.sh
            /tmp/dotnet-install.sh --channel 8.0 --install-dir "$HOME/.dotnet"
            export PATH="$HOME/.dotnet:$PATH"
            echo 'export PATH="$HOME/.dotnet:$PATH"' >> "$HOME/.bashrc"
            ;;
        *)
            warn "Unknown package manager. Install .NET SDK manually: https://dotnet.microsoft.com/download"
            return 1
            ;;
    esac

    # Verify
    if command -v dotnet &>/dev/null; then
        log "dotnet $(dotnet --version) installed"
    else
        fail "dotnet installation failed. Install manually: https://dotnet.microsoft.com/download"
        return 1
    fi
}

# --- Pandoc Installation (Optional) ---
install_pandoc() {
    step "Checking pandoc (optional: content preview)"

    if command -v pandoc &>/dev/null; then
        log "pandoc $(pandoc --version | head -1 | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?') already installed"
        return 0
    fi

    info "Installing pandoc..."
    case "$PKG_MGR" in
        brew)   brew install pandoc ;;
        apt)    sudo apt-get install -y -qq pandoc ;;
        dnf)    sudo dnf install -y pandoc ;;
        pacman) sudo pacman -S --noconfirm pandoc ;;
        zypper) sudo zypper install -y pandoc ;;
        apk)    apk add --no-cache pandoc ;;
        *)
            warn "Cannot auto-install pandoc. Install manually: https://pandoc.org/installing.html"
            return 0
            ;;
    esac

    if command -v pandoc &>/dev/null; then
        log "pandoc installed"
    else
        warn "pandoc installation failed (optional, will degrade gracefully)"
    fi
}

# --- LibreOffice Installation (Optional) ---
install_soffice() {
    step "Checking LibreOffice/soffice (optional: .doc conversion)"

    if command -v soffice &>/dev/null; then
        log "soffice already installed"
        return 0
    fi

    # Also check common install paths
    local soffice_paths=(
        "/usr/bin/soffice"
        "/usr/local/bin/soffice"
        "/opt/libreoffice/program/soffice"
        "/snap/bin/libreoffice"
        "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    )
    for p in "${soffice_paths[@]}"; do
        if [ -x "$p" ]; then
            log "soffice found at $p"
            if [ "$OS" = "macos" ] && [ "$p" = "/Applications/LibreOffice.app/Contents/MacOS/soffice" ]; then
                info "Tip: Add to PATH: ln -s '$p' /usr/local/bin/soffice"
            fi
            return 0
        fi
    done

    info "Installing LibreOffice (this may take a while)..."
    case "$PKG_MGR" in
        brew)   brew install --cask libreoffice ;;
        apt)    sudo apt-get install -y -qq libreoffice-core ;;
        dnf)    sudo dnf install -y libreoffice-core ;;
        pacman) sudo pacman -S --noconfirm libreoffice-still ;;
        zypper) sudo zypper install -y libreoffice ;;
        apk)    apk add --no-cache libreoffice ;;
        *)
            warn "Cannot auto-install LibreOffice. Install manually: https://www.libreoffice.org/download/"
            return 0
            ;;
    esac

    if command -v soffice &>/dev/null; then
        log "soffice installed"
    else
        warn "soffice not found after install (optional, .doc conversion unavailable)"
    fi
}

# --- zip/unzip ---
install_zip_tools() {
    step "Checking zip/unzip"

    local need_zip=false need_unzip=false
    command -v zip &>/dev/null   && log "zip already installed"   || need_zip=true
    command -v unzip &>/dev/null && log "unzip already installed" || need_unzip=true

    if ! $need_zip && ! $need_unzip; then
        return 0
    fi

    info "Installing zip/unzip..."
    case "$PKG_MGR" in
        brew)   brew install zip unzip 2>/dev/null || true ;;
        apt)    sudo apt-get install -y -qq zip unzip ;;
        dnf)    sudo dnf install -y zip unzip ;;
        pacman) sudo pacman -S --noconfirm zip unzip ;;
        zypper) sudo zypper install -y zip unzip ;;
        apk)    apk add --no-cache zip unzip ;;
        *)      warn "Install zip/unzip manually (optional, .NET handles DOCX natively)" ;;
    esac
}

# --- .NET Project Build ---
build_project() {
    step "Building minimax-docx .NET project"

    if [ ! -d "$DOTNET_DIR" ]; then
        fail "Dotnet project directory not found: $DOTNET_DIR"
        return 1
    fi

    cd "$DOTNET_DIR"

    info "Restoring NuGet packages..."
    if ! dotnet restore --verbosity quiet 2>>"$LOG_FILE"; then
        fail "NuGet restore failed. Check network and $LOG_FILE for details."
        fail "Common causes:"
        fail "  - No internet access (NuGet needs to download packages)"
        fail "  - Corporate proxy blocking nuget.org"
        fail "  - Disk space insufficient"
        echo ""
        fail "Try manually: cd $DOTNET_DIR && dotnet restore --verbosity detailed"
        return 1
    fi
    log "NuGet packages restored"

    info "Building project..."
    if ! dotnet build --verbosity quiet --no-restore 2>>"$LOG_FILE"; then
        fail "Build failed. Check $LOG_FILE for details."
        fail "Try manually: cd $DOTNET_DIR && dotnet build --verbosity normal"
        return 1
    fi
    log "Project built successfully"

    cd "$PROJECT_DIR"
}

# --- Shell Script Permissions ---
fix_permissions() {
    step "Setting script permissions"

    local scripts=(
        "$SCRIPT_DIR/env_check.sh"
        "$SCRIPT_DIR/docx_preview.sh"
        "$SCRIPT_DIR/doc_to_docx.sh"
        "$SCRIPT_DIR/setup.sh"
    )

    for s in "${scripts[@]}"; do
        if [ -f "$s" ]; then
            chmod +x "$s"
            log "chmod +x $(basename "$s")"
        fi
    done
}

# --- NuGet Proxy / Certificate Issues (Corporate Environments) ---
check_nuget_config() {
    step "Checking NuGet configuration"

    local nuget_config="$HOME/.nuget/NuGet/NuGet.Config"
    if [ -f "$nuget_config" ]; then
        log "NuGet config exists: $nuget_config"
    else
        info "No custom NuGet config found (using defaults)"
    fi

    # Test NuGet connectivity
    if dotnet nuget list source 2>/dev/null | grep -q "nuget.org"; then
        log "nuget.org source is configured"
    else
        warn "nuget.org not in sources. Adding..."
        dotnet nuget add source "https://api.nuget.org/v3/index.json" --name "nuget.org" 2>/dev/null || true
    fi
}

# --- Locale / Encoding Check ---
check_locale() {
    step "Checking locale and encoding"

    local current_lang="${LANG:-not set}"
    local current_lc="${LC_ALL:-not set}"

    if echo "$current_lang" | grep -qi "utf-8\|utf8"; then
        log "Locale supports UTF-8: LANG=$current_lang"
    else
        warn "Locale may not support UTF-8: LANG=$current_lang"
        warn "CJK document processing requires UTF-8. Set: export LANG=en_US.UTF-8"
        if [ "$OS" = "linux" ] || [ "$OS" = "wsl" ]; then
            info "To fix permanently: sudo locale-gen en_US.UTF-8 && sudo update-locale LANG=en_US.UTF-8"
        fi
    fi
}

# --- Font Check (for CJK and professional documents) ---
check_fonts() {
    step "Checking fonts for document rendering"

    if [ "$OS" = "macos" ]; then
        # macOS has good CJK support built-in
        log "macOS: built-in CJK font support (PingFang, Hiragino, Apple SD Gothic)"
        log "macOS: built-in Western fonts (Helvetica, Times, Calibri via Office)"
        if [ -d "/Applications/Microsoft Word.app" ] || [ -d "/Applications/Microsoft Office" ]; then
            log "Microsoft Office fonts available (Calibri, Cambria, etc.)"
        else
            warn "Microsoft Office not installed — Calibri/Cambria fonts may be missing"
            info "Documents will render with fallback fonts on this machine"
            info "Recipients with Office installed will see correct fonts"
        fi
    elif [ "$OS" = "linux" ] || [ "$OS" = "wsl" ]; then
        # Check for key font packages
        local missing_fonts=()

        if ! fc-list 2>/dev/null | grep -qi "liberation\|times new roman\|calibri"; then
            missing_fonts+=("Western: liberation-fonts or msttcorefonts")
        fi

        if ! fc-list 2>/dev/null | grep -qi "noto.*cjk\|wqy\|simsun\|pingfang"; then
            missing_fonts+=("CJK: noto-fonts-cjk or wqy-microhei")
        fi

        if [ ${#missing_fonts[@]} -eq 0 ]; then
            log "Font support looks good"
        else
            warn "Missing fonts may affect document rendering:"
            for f in "${missing_fonts[@]}"; do
                warn "  - $f"
            done
            info "Install fonts:"
            case "$PKG_MGR" in
                apt)
                    info "  sudo apt-get install -y fonts-liberation fonts-noto-cjk"
                    info "  # For MS core fonts: sudo apt-get install -y ttf-mscorefonts-installer"
                    ;;
                dnf)
                    info "  sudo dnf install -y liberation-fonts google-noto-sans-cjk-fonts"
                    ;;
                pacman)
                    info "  sudo pacman -S ttf-liberation noto-fonts-cjk"
                    ;;
                *)
                    info "  Install Liberation Fonts and Noto CJK fonts for your distribution"
                    ;;
            esac
        fi
    fi
}

# --- Verification Run ---
verify_installation() {
    step "Verification Test"

    local test_output="/tmp/minimax-docx-setup-test-$$.docx"

    info "Creating a test document..."
    if cd "$DOTNET_DIR" && dotnet run --project MiniMaxAIDocx.Cli -- create \
        --type report --output "$test_output" --title "Setup Test" 2>>"$LOG_FILE"; then
        log "Test document created: $test_output"

        # Try preview
        if command -v pandoc &>/dev/null; then
            local preview
            preview=$(pandoc -f docx -t plain "$test_output" 2>/dev/null | head -5)
            if [ -n "$preview" ]; then
                log "Preview working: \"$preview\""
            fi
        fi

        # Cleanup
        rm -f "$test_output"
        log "Test passed — minimax-docx is ready to use!"
    else
        fail "Test document creation failed. Check $LOG_FILE for details."
        return 1
    fi

    cd "$PROJECT_DIR"
}

# --- Summary ---
print_summary() {
    step "Setup Complete"

    echo ""
    echo "  Environment: $OS ($ARCH)"
    echo "  .NET SDK:    $(dotnet --version 2>/dev/null || echo 'NOT FOUND')"
    echo "  pandoc:      $(pandoc --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' || echo 'not installed (optional)')"
    echo "  soffice:     $(soffice --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' || echo 'not installed (optional)')"
    echo "  Project:     $DOTNET_DIR"
    echo ""
    echo "  Usage:"
    echo "    dotnet run --project $DOTNET_DIR/MiniMaxAIDocx.Cli -- create --type report --output my_report.docx"
    echo "    bash $SCRIPT_DIR/env_check.sh     # Quick environment check"
    echo ""
    echo "  Log file: $LOG_FILE"
}

# --- Main ---
main() {
    echo "============================================"
    echo "  minimax-docx Setup & Initialization"
    echo "  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================"

    : > "$LOG_FILE"  # Clear log

    detect_platform

    # Parse arguments
    local SKIP_OPTIONAL=false
    local SKIP_VERIFY=false
    for arg in "$@"; do
        case "$arg" in
            --minimal)      SKIP_OPTIONAL=true ;;
            --skip-verify)  SKIP_VERIFY=true ;;
            --help|-h)
                echo "Usage: setup.sh [options]"
                echo "  --minimal       Only install critical dependencies (skip pandoc, soffice, fonts)"
                echo "  --skip-verify   Skip the verification test at the end"
                echo "  --help          Show this help"
                exit 0
                ;;
        esac
    done

    install_dotnet
    install_zip_tools

    if ! $SKIP_OPTIONAL; then
        install_pandoc
        install_soffice
        check_fonts
    fi

    check_locale
    check_nuget_config
    fix_permissions
    build_project

    if ! $SKIP_VERIFY; then
        verify_installation
    fi

    print_summary
}

main "$@"
