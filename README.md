# Laya Auto File Organizer

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/whysooraj/laya-file-organizer/actions/workflows/ci.yml/badge.svg)](https://github.com/whysooraj/laya-file-organizer/actions/workflows/ci.yml)
[![Laya Engine](https://img.shields.io/badge/Powered%20By-Laya-orange.svg)](https://github.com/NandhaKishorM/laya)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)

An ultra-fast, local-first intelligent file organization system powered by a dual decision engine: the non-autoregressive **Laya System 1** neural model and a high-throughput deterministic heuristic classifier. Every file move is planned, previewed, collision-proof, and fully reversible via transaction rollback.

---

## Architecture

Laya divides file management into six distinct decoupled stages:

1. **Scanner**: Discovers files, resolves compound extensions (`.tar.gz`, `.tar.bz2`, `.d.ts`), and tracks relative and absolute symlinks so moved links remain intact.
2. **Extractor**: Enforces 1KB extraction limits on text files and extracts metadata/text stream operators from PDFs using pure Python.
3. **Classifier**: Dual inference — uses upstream neural Laya Router when available; falls back to deterministic rule-based classifier when unavailable. Uses explicit prefix and extension rules to prevent false-positive junk flagging.
4. **Planner**: Constructs immutable `PlannedMove` records with confidence score, decision reason, and engine attribution before disk changes occur.
5. **Executor**: Executes atomic file operations with collision suffixing (`_dup1`, `_dup2`) and writes transaction journals.
6. **History & Rollback**: Records every operation in `~/.config/laya/history.json`. Reverses operations completely on demand with `laya undo`.

---

## Quickstart

### 1. One-Line Install (macOS & Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/whysooraj/laya-file-organizer/master/install.sh | bash
```

### 2. Manual Clone & Setup

```bash
# Clone the repository
git clone https://github.com/whysooraj/laya-file-organizer.git
cd laya-file-organizer

# Optional: Install neural Laya engine (Requires Python 3.10+)
python3 -m pip install -r requirements.txt
```

> **macOS Note**: 
> - Modern macOS does not include a `python` command; always run with `python3`.
> - The default macOS system Python (`/usr/bin/python3`) is Python 3.9. Laya runs out-of-the-box on Python 3.9 using the built-in fast classifier with zero external dependencies.
> - To enable the optional neural engine on macOS: `brew install python@3.12 && python3.12 -m pip install -r requirements.txt`.

---

## Command Reference

### Interactive Menu

Running `laya` with no arguments in a terminal launches the interactive dashboard:

```bash
laya
```

Allows selecting from detected top folders (`~/Downloads`, `~/Desktop`, `~/Documents`, `~/Pictures`, etc.), previewing changes, configuring custom folder names, and running one-click rollbacks.

### Non-Interactive CLI Subcommands

```bash
# 1. Scan directory and view classification breakdown (no disk changes)
laya scan ~/Downloads
laya scan ~/Downloads --json

# 2. Preview organization plan (Dry Run)
laya organize ~/Downloads --dry-run
laya organize ~/Downloads --dry-run --json

# 3. Apply organization (prompts for confirmation; pass -y to auto-confirm)
laya organize ~/Downloads --apply
laya organize ~/Downloads --apply -y
laya organize ~/Downloads -o ~/SortedDownloads --apply

# 4. Undo and roll back last sorting operation
laya undo
laya undo --batch-id 20261122_120000

# 5. Inspect directory statistics (size distribution, top extensions)
laya inspect ~/Downloads
laya inspect ~/Downloads --json

# 6. Find duplicate files using SHA-256 chunked hashing
laya duplicates ~/Downloads
laya duplicates ~/Downloads --min-size 1024 --json

# 7. View sorting transaction history
laya history
laya history --limit 20 --json

# 8. Manage configuration and folder mappings
laya config
laya config --set-naming short
laya config --add-rule .torrent Torrents
laya config --set-confidence 0.70
```

---

## Benchmark Suite

Laya includes a reproducible benchmarking harness across synthetic and real file samples:

```bash
python3 benchmarks/benchmark.py
```

### Measured Performance (540 Sample Files)

| Engine | Latency (P50) | Latency (P95) | Latency (P99) | Throughput |
|---|---|---|---|---|
| Extension-Only Baseline | 0.0005 ms | 0.0007 ms | 0.0014 ms | 1,600,000 files/sec |
| Laya Heuristic Classifier | 0.0044 ms | 0.0098 ms | 0.0195 ms | 222,000 files/sec |
| Laya Neural Engine | ~22.0 ms | ~34.0 ms | ~45.0 ms | Sub-35ms forward pass |

---

## Testing

```bash
pytest -v
```

Includes 29 unit and integration tests covering:
- Compound extension parsing (`.tar.gz`, `.tar.bz2`, `.d.ts`)
- Relative and absolute symlink safety
- Pure Python PDF text extraction
- Substring false-positive prevention (`template.py` not marked as junk)
- Offline fallback engine execution
- Confidence threshold bounds checking
- Atomic collision resolution (`_dup1`)
- Full and partial transaction batch rollback
- CLI subcommands and JSON outputs

---

## License

Licensed under the [Apache 2.0 License](LICENSE).
