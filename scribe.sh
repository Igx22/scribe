#!/bin/bash
set -euo pipefail

# Keep the caller's cwd: relative input/output paths are resolved from there.
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$APP_DIR/data"
VENV_DIR="$DATA_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python3"
REQUIREMENTS="$APP_DIR/requirements.txt"
STAMP="$VENV_DIR/.requirements-sha256"
LEGACY_PYTHON="$DATA_DIR/runtime/python/bin/python3"
# Start before platform/setup checks, and keep one supervisor across launcher
# and Python execs. Any available Python 3 can run this standard-library helper.
if [[ "${_SCRIBE_CONSOLE_PARENT:-}" != "$PPID" ]]; then
    for logger_python in "$VENV_PYTHON" "$LEGACY_PYTHON" python3.13 python3.12 python3; do
        if command -v "$logger_python" >/dev/null 2>&1 && \
            "$logger_python" -I -B -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
            if [[ -f "$APP_DIR/src/console_log.py" ]]; then
                exec "$logger_python" -I -B "$APP_DIR/src/console_log.py" /bin/bash "$APP_DIR/scribe.sh" "$@"
            fi
            break
        fi
    done
    echo "WARNING: Console file logging unavailable: Python 3.9+ or src/console_log.py is missing." >&2
fi
OFFLINE=false
SETUP=false
for option in "$@"; do
    case "$option" in
        --offline) OFFLINE=true ;;
        --setup) SETUP=true ;;
    esac
done

if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
    echo "Scribe requires macOS 14+ and Apple Silicon (M1 or newer)." >&2
    exit 2
fi
MACOS_VERSION="$(sw_vers -productVersion)"
if [[ "${MACOS_VERSION%%.*}" -lt 14 ]]; then
    echo "Scribe requires macOS 14 or newer." >&2
    exit 2
fi

# A ready environment can run offline without pip, downloads, or shell activation.
environment_ready() {
    [[ -x "$VENV_PYTHON" && -f "$STAMP" ]] || return 1
    "$VENV_PYTHON" -I -B -c '
import hashlib, platform, sys
from pathlib import Path
valid = (3, 12) <= sys.version_info[:2] < (3, 14) and platform.machine() == "arm64"
valid = valid and sys.prefix != sys.base_prefix
valid = valid and Path(sys.argv[2]).read_text().strip() == hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest()
sys.exit(not valid)
' "$REQUIREMENTS" "$STAMP" 2>/dev/null
}

if environment_ready; then
    exec "$VENV_PYTHON" -I -B "$APP_DIR/src/scribe.py" "$@"
fi

# Compatibility for an existing prepared bundle. A new Git clone has no runtime/.
# --setup always builds the new environment from a separately installed Python.
if ! $SETUP && [[ ! -d "$VENV_DIR" && -x "$LEGACY_PYTHON" ]]; then
    exec "$LEGACY_PYTHON" -I -B "$APP_DIR/src/scribe.py" "$@"
fi

if $OFFLINE; then
    echo "Offline environment is not ready. Run ./scribe.sh --setup online first." >&2
    exit 2
fi
if [[ ! -x "$VENV_PYTHON" ]]; then
    SYSTEM_PYTHON=""
    for candidate in python3.13 python3.12 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -I -B -c \
           'import platform,sys; sys.exit(not ((3,12) <= sys.version_info[:2] < (3,14) and platform.machine()=="arm64"))' 2>/dev/null; then
            SYSTEM_PYTHON="$(command -v "$candidate")"
            break
        fi
    done
    if [[ -z "$SYSTEM_PYTHON" ]]; then
        echo "Python 3.12–3.13 for Apple Silicon is required by WhisperX." >&2
        echo "Install it with: brew install python@3.13" >&2
        echo "Then run ./scribe.sh --setup. See README.md for installation from scratch." >&2
        exit 2
    fi
    mkdir -p "$DATA_DIR"
    echo "Creating an isolated Python environment in $VENV_DIR..."
    "$SYSTEM_PYTHON" -I -B -m venv --symlinks "$VENV_DIR"
fi

if ! "$VENV_PYTHON" -I -B -c \
    'import platform,sys; sys.exit(not ((3,12) <= sys.version_info[:2] < (3,14) and platform.machine()=="arm64"))'; then
    echo "data/.venv uses an unsupported Python. Recreate it using Python 3.12–3.13 for Apple Silicon." >&2
    exit 2
fi
mkdir -p "$DATA_DIR/.cache/pip"
echo "Installing Scribe dependencies (internet required on the first run)..."
"$VENV_PYTHON" -I -B -m pip install --disable-pip-version-check --no-input \
    --only-binary=:all: --cache-dir "$DATA_DIR/.cache/pip" -r "$REQUIREMENTS"
"$VENV_PYTHON" -I -B -c \
    'import hashlib,sys; from pathlib import Path; Path(sys.argv[2]).write_text(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest()+"\n")' \
    "$REQUIREMENTS" "$STAMP"
exec "$VENV_PYTHON" -I -B "$APP_DIR/src/scribe.py" "$@"
