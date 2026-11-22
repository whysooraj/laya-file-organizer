# Laya Auto File Organizer

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
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
5. **Executor**: Executes file operations with per-file intent journaling (`planned` -> `completed`), collision resolution (`_dup1`, `_dup2`), cross-process advisory locking (`file_lock`), and atomic journal replacement with parent directory `fsync` to eliminate crash windows.
6. **History & Rollback**: Records every operation in `~/.config/laya/history.json` with lifecycle tracking (`in_progress`, `completed`, `partial_rollback`). Reverses operations completely on demand with `laya undo`, featuring idempotent retries, incremental per-file persistence, and lossless retention of unresolved records. Provides `laya recover` for automated and interactive crash recovery.

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

# 3. Apply organization (requires --apply or -y in all environments)
# In non-interactive terminals (scripts, CI), omitting --apply defaults to preview only
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

# 9. Transaction recovery for interrupted batches
laya recover --inspect
laya recover --rollback
laya recover --resume
laya recover --dismiss
```

---

## Benchmark Suite

Laya includes a comprehensive benchmarking and evaluation harness measuring model inference, end-to-end pipeline throughput across disk operations, memory allocations, and classification accuracy:

```bash
# 1. Model and heuristic inference latency benchmark
python3 benchmarks/benchmark.py

# 2. Full end-to-end pipeline benchmark (scanning, extraction, planning, disk moves, rollback, memory)
python3 benchmarks/benchmark.py --pipeline --pipeline-files 200 --skip-neural

# 3. Curated ground-truth classification evaluation (100 verified samples, 12 categories)
python3 benchmarks/benchmark.py --accuracy --heuristic
python3 benchmarks/benchmark.py --accuracy --neural

# 4. Run full suite and export structured JSON
python3 benchmarks/benchmark.py --all --json
```

### Measured Inference Performance (540 Files)

| Engine | Latency (P50) | Latency (P95) | Latency (P99) | Throughput |
|---|---|---|---|---|
| Extension-Only Baseline | 0.0005 ms | 0.0007 ms | 0.0014 ms | 1,600,000 files/sec |
| Laya Heuristic Classifier | 0.0044 ms | 0.0098 ms | 0.0195 ms | 222,000 files/sec |
| Laya Neural Engine | ~22.0 ms | ~34.0 ms | ~45.0 ms | Sub-35ms forward pass |

### Measured End-to-End Pipeline Performance (200 Real Files on Disk)

| Pipeline Stage | Total Time | Throughput | Latency per File |
|---|---|---|---|
| 1) Directory Scanning | 0.004s | 47,404 files/sec | 0.021 ms |
| 2) Content & PDF Extraction | 0.005s | 42,995 files/sec | 0.023 ms |
| 3) Planning & Classification | 0.015s | 13,152 files/sec | 0.076 ms |
| 4) Atomic File Moves & Journal | 0.609s | 328 files/sec | 3.042 ms |
| 5) Lossless Full Rollback | 0.016s | 12,735 files/sec | 0.079 ms |
| **Total End-to-End Pipeline** | **0.655s** | **305 files/sec** | **3.275 ms** |

Peak Memory Allocation: **1.54 MB** (zero memory bloat during batch operations).

### Curated Classification Evaluation (100 Verified Samples)

- Deterministic rule coverage: **100.0%** across exactly 100 curated multi-category files covering Financial, Code, Data, Logs, Graphics, Media, Archives, Manuals, 3D, Documents, and Junk candidates.
- Evaluates challenging edge-cases: misleading compound extensions (`.pdf.py`), hidden dotfiles (`.env`, `.env.production`), build artifacts (`.d.ts`, `.spec.ts`), and ambiguous files.
- Note: 100% test accuracy confirms complete rule coverage for defined extensions and keywords; it does not imply 100% open-world generalization. Synthetic latency benchmarks are measured separately from real-world classification evaluation.

---

## Testing

```bash
pytest -v
```

Includes 38 unit, reliability, and crash-recovery tests covering:
- Compound extension parsing (`.tar.gz`, `.tar.bz2`, `.d.ts`, `.spec.ts`)
- Relative and absolute symlink safety
- Pure Python PDF text extraction
- Substring false-positive prevention (`template.py` not marked as junk)
- Offline fallback engine execution
- Confidence threshold bounds checking
- Atomic collision resolution (`_dup1`)
- Non-interactive execution consent enforcement (preview-only without `--apply`)
- Full and partial transaction batch rollback
- Recovery history retention for missing or failed file rollbacks
- Advisory file locking (`fcntl.flock`) and crash-safe transaction journaling
- Per-file intent journaling (`planned` -> `completed` transition)
- Idempotent rollback retries with distinct rollback transaction IDs
- Startup crash inspection and interactive/non-interactive recovery (`laya recover`)
- CLI subcommands and JSON outputs

---

## License

Licensed under the [Apache 2.0 License](LICENSE).
