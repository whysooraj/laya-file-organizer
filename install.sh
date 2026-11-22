#!/usr/bin/env bash
# ==============================================================================
# Laya Auto File Organizer — Interactive Installer
# Supports macOS (Darwin) & Linux. Piped curl compatible (curl -fsSL ... | bash)
# ==============================================================================
set -euo pipefail

INTERACTIVE=false
if [ "${INTERACTIVE}" = true ]; then
  INTERACTIVE=true
elif [ -e /dev/tty ] && [ -z "${CI:-}" ] && [ -z "${NONINTERACTIVE:-}" ]; then
  if exec < /dev/tty 2>/dev/null; then
    INTERACTIVE=true
  fi
fi

CLEAR_SCREEN=""
BOLD="\033[1m"
DIM="\033[2m"
GREEN="\033[32m"
CYAN="\033[36m"
YELLOW="\033[33m"
RESET="\033[0m"

echo -e "${BOLD}"
echo "============================================================"
echo "          LAYA AUTO FILE ORGANIZER — INSTALLER"
echo "      Sub-35ms Local Decision Engine & Rollback CLI"
echo "============================================================"
echo -e "${RESET}"

# 1. Check Python 3
if ! command -v python3 >/dev/null 2>&1; then
  echo -e "${YELLOW}Warning: python3 not found.${RESET}"
  echo "On macOS, run: xcode-select --install or brew install python@3.12"
  echo "On Linux, run: sudo apt install python3 or sudo dnf install python3"
  exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "${GREEN}✓${RESET} Detected Python ${BOLD}${PY_VER}${RESET}"

# 2. Interactive Prompts (with non-interactive defaults)
INSTALL_DIR="${HOME}/.local/bin"
NAMING_STYLE="1"

if [ "${INTERACTIVE}" = true ]; then
  # Target directory prompt
  echo ""
  echo -e "${CYAN}1. Choose Install Location:${RESET}"
  echo -e "   [1] ${HOME}/.local/bin ${DIM}(Default, recommended)${RESET}"
  echo -e "   [2] /usr/local/bin ${DIM}(System-wide, requires sudo)${RESET}"
  echo -e "   [3] Custom directory"
  read -r -p "Select option [1-3, default 1]: " dir_choice
  dir_choice="${dir_choice:-1}"

  case "${dir_choice}" in
    2) INSTALL_DIR="/usr/local/bin" ;;
    3)
       read -r -p "Enter full path: " custom_dir
       INSTALL_DIR="${custom_dir:-$HOME/.local/bin}"
       ;;
    *) INSTALL_DIR="${HOME}/.local/bin" ;;
  esac

  # Folder naming preference
  echo ""
  echo -e "${CYAN}2. Preferred Folder Naming Style:${RESET}"
  echo -e "   [1] Standard ${DIM}(Financial/, Code_and_Scripts/, Documents/, Audio_and_Music/)${RESET}"
  echo -e "   [2] Clean & Short ${DIM}(Finance/, Code/, Docs/, Media/, Data/)${RESET}"
  read -r -p "Select naming style [1-2, default 1]: " naming_choice
  NAMING_STYLE="${naming_choice:-1}"
fi

# 3. Create install directory
mkdir -p "${INSTALL_DIR}"
TARGET="${INSTALL_DIR}/laya"

echo ""
echo -e "Fetching latest Laya CLI executable..."
curl -fsSL "https://raw.githubusercontent.com/whysooraj/laya-file-organizer/master/laya_organizer.py" -o "${TARGET}"
chmod +x "${TARGET}"
echo -e "${GREEN}✓${RESET} Installed binary to ${BOLD}${TARGET}${RESET}"

# 4. Generate user configuration (~/.config/laya/config.json)
CONFIG_DIR="${HOME}/.config/laya"
CONFIG_FILE="${CONFIG_DIR}/config.json"
mkdir -p "${CONFIG_DIR}"

if [ ! -f "${CONFIG_FILE}" ] || [ "${NAMING_STYLE}" = "2" ]; then
  if [ "${NAMING_STYLE}" = "2" ]; then
    cat > "${CONFIG_FILE}" << 'EOF'
{
  "folder_names": {
    "Financial": "Finance",
    "Documents": "Docs",
    "Code_and_Scripts": "Code",
    "Data_and_Configs": "Data",
    "Logs_and_Diagnostics": "Logs",
    "Images_and_Graphics": "Images",
    "Audio_and_Music": "Audio",
    "Video_and_Movies": "Videos",
    "Archives_and_Installers": "Archives",
    "Books_and_Manuals": "Books",
    "Design_and_3D": "3D_Design",
    "Other": "Other",
    "Junk_Candidates": "Trash_Candidates",
    "Uncertain": "Unsorted"
  },
  "ignored_extensions": [".crdownload", ".part", ".tmp", ".download", ".partial"],
  "custom_rules": {},
  "default_confidence": 0.50,
  "auto_confirm": false
}
EOF
  else
    cat > "${CONFIG_FILE}" << 'EOF'
{
  "folder_names": {
    "Financial": "Financial",
    "Documents": "Documents",
    "Code_and_Scripts": "Code_and_Scripts",
    "Data_and_Configs": "Data_and_Configs",
    "Logs_and_Diagnostics": "Logs_and_Diagnostics",
    "Images_and_Graphics": "Images_and_Graphics",
    "Audio_and_Music": "Audio_and_Music",
    "Video_and_Movies": "Video_and_Movies",
    "Archives_and_Installers": "Archives_and_Installers",
    "Books_and_Manuals": "Books_and_Manuals",
    "Design_and_3D": "Design_and_3D",
    "Other": "Other",
    "Junk_Candidates": "Junk_Candidates",
    "Uncertain": "Uncertain"
  },
  "ignored_extensions": [".crdownload", ".part", ".tmp", ".download", ".partial"],
  "custom_rules": {},
  "default_confidence": 0.50,
  "auto_confirm": false
}
EOF
  fi
  echo -e "${GREEN}✓${RESET} Initialized config at ${BOLD}${CONFIG_FILE}${RESET}"
fi

# 5. Check PATH & offer auto-export
PATH_RESOLVED=false
case ":${PATH}:" in
  *":${INSTALL_DIR}:"*) PATH_RESOLVED=true ;;
esac

if [ "${PATH_RESOLVED}" = false ]; then
  SHELL_RC=""
  if [ -n "${ZSH_VERSION:-}" ] || [ -f "${HOME}/.zshrc" ]; then
    SHELL_RC="${HOME}/.zshrc"
  elif [ -f "${HOME}/.bashrc" ]; then
    SHELL_RC="${HOME}/.bashrc"
  fi

  if [ -t 0 ] && [ -n "${SHELL_RC}" ]; then
    echo ""
    echo -e "${YELLOW}!${RESET} ${INSTALL_DIR} is not currently in your system PATH."
    read -r -p "Add '${INSTALL_DIR}' to ${SHELL_RC}? [Y/n]: " add_path_choice
    add_path_choice="${add_path_choice:-Y}"
    if [[ "${add_path_choice}" =~ ^[Yy]$ ]]; then
      echo "export PATH=\"${INSTALL_DIR}:\$PATH\"" >> "${SHELL_RC}"
      echo -e "${GREEN}✓${RESET} Appended export PATH to ${BOLD}${SHELL_RC}${RESET}"
      echo -e "  Run ${DIM}source ${SHELL_RC}${RESET} to reload your shell environment."
    fi
  else
    echo ""
    echo -e "${YELLOW}!${RESET} Please add ${INSTALL_DIR} to your PATH:"
    echo -e "    export PATH=\"${INSTALL_DIR}:\$PATH\""
  fi
fi

# 6. Python engine advisory
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null || {
  echo ""
  echo -e "${DIM}Note: Detected Python < 3.10. Running with built-in fast fallback classifier.${RESET}"
  echo -e "${DIM}To enable the optional upstream neural model on macOS:${RESET}"
  echo -e "${DIM}  brew install python@3.12 && python3.12 -m pip install 'laya>=0.3.26'${RESET}"
}

echo ""
echo -e "${BOLD}${GREEN}============================================================${RESET}"
echo -e "${BOLD}${GREEN}          LAYA SUCCESSFULLY INSTALLED & READY!              ${RESET}"
echo -e "${BOLD}${GREEN}============================================================${RESET}"
echo ""
echo -e "${BOLD}Getting Started:${RESET}"
echo -e "  ${CYAN}laya${RESET}                    Launch friendly interactive CLI menu"
echo -e "  ${CYAN}laya ~/Downloads${RESET}        Sort downloads folder directly"
echo -e "  ${CYAN}laya ~/Downloads --dry-run${RESET}  Preview organization without moving files"
echo -e "  ${CYAN}laya --undo${RESET}             Roll back & restore last moved files"
echo -e "  ${CYAN}laya --config${RESET}           Customize folder names & custom extension rules"
echo -e "  ${CYAN}laya --history${RESET}          View recent organization audit log"
echo ""
