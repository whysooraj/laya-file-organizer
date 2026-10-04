# ⚡ Laya Auto File Organizer

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Laya Engine](https://img.shields.io/badge/Powered%20By-Laya-orange.svg)](https://github.com/NandhaKishorM/laya)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)

An ultra-fast, intelligent file organizer powered by **[Laya](https://github.com/NandhaKishorM/laya)** — a non-autoregressive System 1 decision engine. Categorizes and organizes files in **sub-35ms forward passes** locally without calling heavy LLM APIs or paying token costs.

---

## ✨ Features

- **⚡ Sub-35ms Local Decision Speed**: Evaluates file names, extensions, and snippets in a single forward pass.
- **🎯 Typed Classification**: Categorizes files into `Financial`, `Documents`, `Code_and_Logs`, `Media`, `Archives_and_Installers`, or `Other`.
- **🗑️ Junk Detection**: Identifies temporary scrap files and moves them to `Junk_Candidates/`.
- **🛡️ Confidence Thresholding**: Low-confidence predictions (`< 0.50`) fall back safely to `Uncertain/`.
- **🔍 Dry-Run Mode**: Preview sorting actions without moving any files.
- **🔒 100% Privacy & Offline**: Runs entirely on your CPU/GPU with zero cloud data transmission.

---

## 🚀 Quickstart

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/whysooraj/laya-file-organizer.git
cd laya-file-organizer

# Install dependencies
pip install -r requirements.txt
```

### 2. Usage Examples

```bash
# Preview organization (Dry Run)
python3 laya_organizer.py ~/Downloads --dry-run

# Organize directory in-place
python3 laya_organizer.py ~/Downloads

# Organize to a separate destination folder
python3 laya_organizer.py ~/Downloads -o ~/Organized

# Set custom min-confidence threshold (e.g. 0.70)
python3 laya_organizer.py ~/Downloads --confidence 0.70

# Run internal self-check test
python3 laya_organizer.py --check
```

---

## 🏗️ How It Works

1. **Context Extraction**: Reads filename, extension, file size, and the first 1KB text snippet.
2. **Laya System 1 Pass**: Executes a single non-autoregressive forward pass querying:
   - `category` (`choice` decision)
   - `is_temporary_junk` (`noul` decision)
3. **Safe Move**: Moves files into designated target folders. Prevents overwriting duplicates by adding `_dup` suffixes.

---

## 📄 License

Licensed under the [Apache 2.0 License](LICENSE).
