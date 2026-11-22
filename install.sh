#!/usr/bin/env bash
set -euo pipefail

# Verify Python 3 presence (modern macOS lacks 'python')
if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is not installed or not in PATH."
  echo "On macOS, install Xcode Command Line Tools ('xcode-select --install') or Homebrew Python ('brew install python@3.12')."
  exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Detected Python ${PY_VER}"

INSTALL_DIR="${HOME}/.local/bin"
mkdir -p "${INSTALL_DIR}"

TARGET="${INSTALL_DIR}/laya"
curl -fsSL https://raw.githubusercontent.com/whysooraj/laya-file-organizer/master/laya_organizer.py -o "${TARGET}"
chmod +x "${TARGET}"

echo "Installed laya to ${TARGET}"

python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null || {
  echo "Notice: Detected Python < 3.10 (macOS system default). Laya will run out-of-the-box using the built-in fast classifier."
  echo "To enable the optional upstream neural decision engine: brew install python@3.12 && python3.12 -m pip install 'laya>=0.3.26'"
}

case ":${PATH}:" in
  *":${INSTALL_DIR}:"*) ;;
  *) echo "Add ${INSTALL_DIR} to your PATH (e.g. export PATH=\"\$HOME/.local/bin:\$PATH\")" ;;
esac
