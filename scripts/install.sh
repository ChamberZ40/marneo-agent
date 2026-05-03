#!/usr/bin/env bash
# Marneo Agent Installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ChamberZ40/marneo-agent/main/scripts/install.sh | bash
#
# Options:
#   --skip-setup       Install only; do not launch marneo setup
#   --branch NAME      Git branch to install (default: main)
#   --dir PATH         Installation directory (default: ~/.marneo/marneo-agent)
#   --marneo-home PATH Data/config directory (default: ~/.marneo)
#
# Environment:
#   MARNEO_HOME              Override data/config directory
#   MARNEO_INSTALL_DIR       Override checkout directory
#   MARNEO_INSTALL_DRY_RUN=1 Print actions without changing the machine

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

REPO_URL_SSH="git@github.com:ChamberZ40/marneo-agent.git"
REPO_URL_HTTPS="https://github.com/ChamberZ40/marneo-agent.git"
MARNEO_HOME="${MARNEO_HOME:-$HOME/.marneo}"
MARNEO_INSTALL_DIR="${MARNEO_INSTALL_DIR:-$MARNEO_HOME/marneo-agent}"
PYTHON_VERSION="3.11"
BRANCH="main"
RUN_SETUP=true
DRY_RUN="${MARNEO_INSTALL_DRY_RUN:-0}"
INSTALL_DIR_SET=false

if [ -t 0 ]; then
    IS_INTERACTIVE=true
else
    IS_INTERACTIVE=false
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-setup)
            RUN_SETUP=false
            shift
            ;;
        --branch)
            BRANCH="${2:?--branch requires a value}"
            shift 2
            ;;
        --dir)
            MARNEO_INSTALL_DIR="${2:?--dir requires a value}"
            INSTALL_DIR_SET=true
            shift 2
            ;;
        --marneo-home)
            MARNEO_HOME="${2:?--marneo-home requires a value}"
            if [ "$INSTALL_DIR_SET" = false ]; then
                MARNEO_INSTALL_DIR="$MARNEO_HOME/marneo-agent"
            fi
            shift 2
            ;;
        -h|--help)
            cat <<'HELP'
Marneo Agent Installer

Usage:
  install.sh [OPTIONS]

Options:
  --skip-setup          Install only; do not launch marneo setup
  --branch NAME         Git branch to install (default: main)
  --dir PATH            Installation directory (default: ~/.marneo/marneo-agent)
  --marneo-home PATH    Data/config directory (default: ~/.marneo)
  -h, --help            Show this help

Examples:
  curl -fsSL https://raw.githubusercontent.com/ChamberZ40/marneo-agent/main/scripts/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/ChamberZ40/marneo-agent/main/scripts/install.sh | bash -s -- --skip-setup
HELP
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

log_info() { echo -e "${CYAN}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

run() {
    if [ "$DRY_RUN" = "1" ]; then
        echo "+ $*"
    else
        "$@"
    fi
}

print_banner() {
    echo ""
    echo -e "${CYAN}${BOLD}"
    echo "┌──────────────────────────────────────────────┐"
    echo "│            Marneo Agent Installer            │"
    echo "│   Feishu-first digital employees for work    │"
    echo "└──────────────────────────────────────────────┘"
    echo -e "${NC}"
}

install_uv() {
    log_info "Checking uv package manager..."
    if command -v uv >/dev/null 2>&1; then
        UV_CMD="uv"
        log_success "uv found: $(uv --version 2>/dev/null)"
        return 0
    fi
    if [ -x "$HOME/.local/bin/uv" ]; then
        UV_CMD="$HOME/.local/bin/uv"
        log_success "uv found: $($UV_CMD --version 2>/dev/null)"
        return 0
    fi
    if [ -x "$HOME/.cargo/bin/uv" ]; then
        UV_CMD="$HOME/.cargo/bin/uv"
        log_success "uv found: $($UV_CMD --version 2>/dev/null)"
        return 0
    fi

    log_info "Installing uv..."
    if [ "$DRY_RUN" = "1" ]; then
        UV_CMD="$HOME/.local/bin/uv"
        echo "+ curl -LsSf https://astral.sh/uv/install.sh | sh"
        return 0
    fi
    curl -LsSf https://astral.sh/uv/install.sh | sh
    if [ -x "$HOME/.local/bin/uv" ]; then
        UV_CMD="$HOME/.local/bin/uv"
    elif [ -x "$HOME/.cargo/bin/uv" ]; then
        UV_CMD="$HOME/.cargo/bin/uv"
    elif command -v uv >/dev/null 2>&1; then
        UV_CMD="uv"
    else
        log_error "uv installed but was not found. Add ~/.local/bin to PATH and rerun."
        exit 1
    fi
    log_success "uv installed: $($UV_CMD --version 2>/dev/null)"
}

check_git() {
    log_info "Checking Git..."
    if command -v git >/dev/null 2>&1; then
        log_success "Git found: $(git --version)"
        return 0
    fi
    log_error "Git not found. Install Git first, then rerun this installer."
    case "$(uname -s)" in
        Darwin) log_info "macOS: xcode-select --install  or  brew install git" ;;
        Linux) log_info "Linux: use apt/dnf/pacman to install git" ;;
    esac
    exit 1
}

check_python() {
    log_info "Checking Python $PYTHON_VERSION..."
    if [ "$DRY_RUN" = "1" ]; then
        echo "+ $UV_CMD python find $PYTHON_VERSION || $UV_CMD python install $PYTHON_VERSION"
        return 0
    fi
    if PYTHON_PATH="$($UV_CMD python find "$PYTHON_VERSION" 2>/dev/null)"; then
        log_success "Python found: $($PYTHON_PATH --version 2>/dev/null)"
        return 0
    fi
    log_info "Python $PYTHON_VERSION not found, installing with uv..."
    $UV_CMD python install "$PYTHON_VERSION"
    PYTHON_PATH="$($UV_CMD python find "$PYTHON_VERSION")"
    log_success "Python ready: $($PYTHON_PATH --version 2>/dev/null)"
}

clone_or_update_repo() {
    log_info "Preparing repository at $MARNEO_INSTALL_DIR..."
    run mkdir -p "$(dirname "$MARNEO_INSTALL_DIR")"

    if [ -d "$MARNEO_INSTALL_DIR/.git" ]; then
        log_info "Existing Marneo checkout found, updating..."
        if [ "$DRY_RUN" = "1" ]; then
            echo "+ cd $MARNEO_INSTALL_DIR && git fetch origin && git checkout $BRANCH && git pull --ff-only origin $BRANCH"
        else
            cd "$MARNEO_INSTALL_DIR"
            if [ -n "$(git status --porcelain)" ]; then
                local stash_name
                stash_name="marneo-install-autostash-$(date -u +%Y%m%d-%H%M%S)"
                log_warn "Local changes detected; stashing before update as $stash_name"
                git stash push --include-untracked -m "$stash_name"
            fi
            git fetch origin
            git checkout "$BRANCH"
            git pull --ff-only origin "$BRANCH"
        fi
    elif [ -e "$MARNEO_INSTALL_DIR" ]; then
        log_error "$MARNEO_INSTALL_DIR exists but is not a git repository."
        log_info "Remove it or pass --dir PATH."
        exit 1
    else
        log_info "Trying SSH clone first..."
        if [ "$DRY_RUN" = "1" ]; then
            echo "+ git clone --branch $BRANCH $REPO_URL_HTTPS $MARNEO_INSTALL_DIR"
        elif GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=5" git clone --branch "$BRANCH" "$REPO_URL_SSH" "$MARNEO_INSTALL_DIR" 2>/dev/null; then
            log_success "Cloned via SSH"
        else
            rm -rf "$MARNEO_INSTALL_DIR" 2>/dev/null || true
            log_info "SSH clone failed, trying HTTPS..."
            git clone --branch "$BRANCH" "$REPO_URL_HTTPS" "$MARNEO_INSTALL_DIR"
            log_success "Cloned via HTTPS"
        fi
    fi
}

setup_venv_and_install() {
    log_info "Creating virtual environment..."
    if [ "$DRY_RUN" = "1" ]; then
        echo "+ cd $MARNEO_INSTALL_DIR && uv venv venv --python $PYTHON_VERSION"
        echo "+ cd $MARNEO_INSTALL_DIR && uv pip install -e ."
        return 0
    fi
    cd "$MARNEO_INSTALL_DIR"
    $UV_CMD venv venv --python "$PYTHON_VERSION"
    export VIRTUAL_ENV="$MARNEO_INSTALL_DIR/venv"
    $UV_CMD pip install -e .
    log_success "Marneo package installed"
}

command_link_dir() {
    if [ "$(id -u)" -eq 0 ] && [ "$(uname -s)" = "Linux" ]; then
        echo "/usr/local/bin"
    else
        echo "$HOME/.local/bin"
    fi
}

setup_path() {
    local bin_path="$MARNEO_INSTALL_DIR/venv/bin/marneo"
    local link_dir
    link_dir="$(command_link_dir)"

    log_info "Setting up marneo command..."
    run mkdir -p "$link_dir"
    run ln -sf "$bin_path" "$link_dir/marneo"

    export PATH="$link_dir:$PATH"
    if ! echo "$PATH" | tr ':' '\n' | grep -q "^$link_dir$"; then
        log_warn "$link_dir is not on PATH"
    fi

    if [ "$link_dir" = "$HOME/.local/bin" ]; then
        for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
            [ -f "$rc" ] || continue
            if ! grep -q '.local/bin' "$rc" 2>/dev/null; then
                if [ "$DRY_RUN" = "1" ]; then
                    echo "+ append PATH setup to $rc"
                else
                    {
                        echo ""
                        echo "# Marneo Agent — ensure ~/.local/bin is on PATH"
                        echo 'export PATH="$HOME/.local/bin:$PATH"'
                    } >> "$rc"
                    log_success "Added ~/.local/bin to PATH in $rc"
                fi
            fi
        done
    fi

    log_success "marneo command linked at $link_dir/marneo"
}

prepare_marneo_home() {
    log_info "Preparing Marneo home at $MARNEO_HOME..."
    run mkdir -p "$MARNEO_HOME/employees" "$MARNEO_HOME/projects" "$MARNEO_HOME/logs"
    if [ "$DRY_RUN" != "1" ] && [ ! -f "$MARNEO_HOME/README.txt" ]; then
        cat > "$MARNEO_HOME/README.txt" <<'EOF'
Marneo local data directory.

Typical files:
- config.yaml: provider configuration
- employees/: digital employee profiles and channel configs
- projects/: project workspaces
- gateway.log / gateway.pid: gateway runtime state
EOF
    fi
    log_success "Marneo home ready"
}

verify_install() {
    log_info "Verifying installation..."
    if [ "$DRY_RUN" = "1" ]; then
        echo "+ marneo --version"
        return 0
    fi
    if command -v marneo >/dev/null 2>&1; then
        marneo --version
        log_success "Marneo is installed"
    else
        log_warn "marneo is installed but not visible on PATH in this shell."
        log_info "Try: export PATH=\"$(command_link_dir):\$PATH\""
    fi
}

next_steps() {
    echo ""
    echo -e "${GREEN}${BOLD}Marneo installation complete.${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Configure provider:       marneo setup"
    echo "  2. Hire first employee:      marneo hire"
    echo "  3. Local-only usage:         marneo work"
    echo "  4. Feishu usage:             marneo setup feishu"
    echo "                               marneo gateway start"
    echo ""
    echo "Useful paths:"
    echo "  Data/config: $MARNEO_HOME"
    echo "  Code:        $MARNEO_INSTALL_DIR"
    echo ""
}

main() {
    print_banner
    log_info "Install directory: $MARNEO_INSTALL_DIR"
    log_info "Data directory:    $MARNEO_HOME"
    [ "$IS_INTERACTIVE" = true ] || log_info "Running in non-interactive mode"

    check_git
    install_uv
    check_python
    clone_or_update_repo
    setup_venv_and_install
    setup_path
    prepare_marneo_home
    verify_install
    next_steps

    if [ "$RUN_SETUP" = true ]; then
        if [ "$DRY_RUN" = "1" ]; then
            echo "+ marneo setup"
        elif command -v marneo >/dev/null 2>&1; then
            log_info "Launching marneo setup. Use --skip-setup to skip next time."
            marneo setup || log_warn "Setup exited; you can rerun it with: marneo setup"
        else
            log_info "Run setup after refreshing PATH: marneo setup"
        fi
    fi
}

main "$@"
