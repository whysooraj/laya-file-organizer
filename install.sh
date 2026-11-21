#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${HOME}/.local/bin"
mkdir -p "${INSTALL_DIR}"

TARGET="${INSTALL_DIR}/laya"
curl -fsSL https://raw.githubusercontent.com/whysooraj/laya-file-organizer/master/laya_organizer.py -o "${TARGET}"
chmod +x "${TARGET}"

echo "Installed laya to ${TARGET}"
case ":${PATH}:" in
  *":${INSTALL_DIR}:"*) ;;
  *) echo "Add ${INSTALL_DIR} to your PATH (e.g. export PATH=\"\$HOME/.local/bin:\$PATH\")" ;;
esac
