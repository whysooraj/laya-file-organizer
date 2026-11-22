#!/usr/bin/env python3
"""
Laya Auto File Organizer
Sub-35ms local intelligent file organization engine.
Categorizes files, manages transactions with rollback, and offers interactive terminal UI.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

_HELD_LOCKS: dict[str, int] = {}
_LOCK_FDS: dict[str, Any] = {}


@contextlib.contextmanager
def file_lock(lock_file: Path) -> Generator[None, None, None]:
    """Reentrant cross-process advisory file lock context manager."""
    resolved = str(lock_file.resolve())
    if resolved in _HELD_LOCKS and _HELD_LOCKS[resolved] > 0:
        _HELD_LOCKS[resolved] += 1
        try:
            yield
        finally:
            _HELD_LOCKS[resolved] -= 1
        return

    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file, "a+", encoding="utf-8") as f:
        try:
            if fcntl is not None:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            _HELD_LOCKS[resolved] = 1
            _LOCK_FDS[resolved] = f
            yield
        finally:
            _HELD_LOCKS.pop(resolved, None)
            _LOCK_FDS.pop(resolved, None)
            try:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass

DEFAULT_ACTIVE_DOWNLOAD_EXTS = ('.crdownload', '.part', '.download', '.partial')
ACTIVE_DOWNLOAD_EXTS = DEFAULT_ACTIVE_DOWNLOAD_EXTS
CONFIG_DIR = Path.home() / ".config" / "laya"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.json"

COMPOUND_EXTENSIONS = (
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".tar.zst",
    ".tar.br",
    ".backup.zip",
    ".d.ts",
    ".spec.ts",
    ".test.ts",
    ".spec.js",
    ".test.js",
    ".min.js",
    ".min.css",
)

SCRAP_EXTENSIONS = {".tmp", ".temp", ".swp", ".crdownload", ".part", ".partial", ".download"}
SCRAP_EXACT_NAMES = {"thumbs.db", ".ds_store"}
SCRAP_PREFIXES = ("temp_", "cache_")

DEFAULT_FOLDER_NAMES = {
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
    "Uncertain": "Uncertain",
}

SHORT_FOLDER_NAMES = {
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
    "Uncertain": "Unsorted",
}

NESTED_FOLDER_NAMES = {
    "Financial": "Documents/Financial",
    "Documents": "Documents/General",
    "Code_and_Scripts": "Development/Code",
    "Data_and_Configs": "Development/Data",
    "Logs_and_Diagnostics": "Development/Logs",
    "Images_and_Graphics": "Media/Images",
    "Audio_and_Music": "Media/Audio",
    "Video_and_Movies": "Media/Videos",
    "Archives_and_Installers": "Installers_and_Archives",
    "Books_and_Manuals": "Documents/Books",
    "Design_and_3D": "Media/3D_Design",
    "Other": "Other",
    "Junk_Candidates": "Junk_Candidates",
    "Uncertain": "Uncertain",
}


def format_size(bytes_val: float) -> str:
    """Formats raw bytes into human-readable string (KB, MB, GB)."""
    val = float(bytes_val)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024 or unit == "TB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024
    return f"{val:.1f} PB"


def format_table(headers: list[str], rows: list[list[str]], alignments: list[str] | None = None) -> str:
    """Builds clean Unicode table without third-party dependencies."""
    num_cols = len(headers)
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < num_cols:
                widths[i] = max(widths[i], len(str(cell)))

    def make_border(left: str, mid: str, right: str, fill: str = "─") -> str:
        return left + mid.join(fill * (w + 2) for w in widths) + right

    aligns = alignments or ["left"] * num_cols

    def format_row(cells: list[str]) -> str:
        parts = []
        for cell, w, align in zip(cells, widths, aligns):
            s = str(cell)
            if align == "right":
                parts.append(f" {s.rjust(w)} ")
            elif align == "center":
                parts.append(f" {s.center(w)} ")
            else:
                parts.append(f" {s.ljust(w)} ")
        return "│" + "│".join(parts) + "│"

    lines = [
        make_border("┌", "┬", "┐"),
        format_row(headers),
        make_border("├", "┼", "┤"),
    ]
    for row in rows:
        full_row = [str(c) for c in row] + [""] * (num_cols - len(row))
        lines.append(format_row(full_row[:num_cols]))
    lines.append(make_border("└", "┴", "┘"))
    return "\n".join(lines)


def get_compound_extension(path_or_name: Path | str) -> str:
    """Returns compound extension if matched (e.g. .tar.gz), otherwise normal suffix (.txt)."""
    name = path_or_name.name if isinstance(path_or_name, Path) else Path(str(path_or_name)).name
    name_lower = name.lower()
    for ce in COMPOUND_EXTENSIONS:
        if name_lower.endswith(ce):
            return ce
    return Path(name).suffix.lower()


def split_stem_and_ext(path_or_name: Path | str) -> tuple[str, str]:
    """Splits filename into (stem, extension) taking compound extensions into account."""
    name = path_or_name.name if isinstance(path_or_name, Path) else Path(str(path_or_name)).name
    name_lower = name.lower()
    for ce in COMPOUND_EXTENSIONS:
        if name_lower.endswith(ce):
            return name[:-len(ce)], name[-len(ce):]
    p = Path(name)
    return p.stem, p.suffix


def is_junk_candidate(path_or_name: Path | str) -> bool:
    """Safe scrap junk detection: triggers only on explicit scrap extensions, names, or prefixes."""
    name = path_or_name.name if isinstance(path_or_name, Path) else Path(str(path_or_name)).name
    name_lower = name.lower()

    if name_lower in SCRAP_EXACT_NAMES:
        return True
    if name_lower.startswith("~"):
        return True
    for ext in SCRAP_EXTENSIONS:
        if name_lower.endswith(ext):
            return True
    return bool(name_lower.startswith(SCRAP_PREFIXES))


def validate_confidence_threshold(val: Any) -> float:
    """Validates confidence threshold is a float between 0.0 and 1.0."""
    if val is None:
        return 0.50
    try:
        f_val = float(val)
    except (TypeError, ValueError):
        raise ValueError(f"Confidence threshold must be a float between 0.0 and 1.0, got: {val!r}") from None
    if not (0.0 <= f_val <= 1.0):
        raise ValueError(f"Confidence threshold must be between 0.0 and 1.0, got: {f_val}")
    return f_val


def atomic_write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Atomically writes JSON to disk via tempfile.mkstemp, fsync, os.replace, and parent dir fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    parent_dir = path.parent
    fd, temp_path_str = tempfile.mkstemp(dir=parent_dir, prefix=f".{path.name}.tmp.")
    temp_path = Path(temp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
        dir_flag = getattr(os, "O_DIRECTORY", 0)
        try:
            dir_fd = os.open(str(parent_dir), os.O_RDONLY | dir_flag)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise


def load_config() -> dict[str, Any]:
    """Loads configuration from ~/.config/laya/config.json with default fallback."""
    config = {
        "folder_names": dict(DEFAULT_FOLDER_NAMES),
        "ignored_extensions": list(DEFAULT_ACTIVE_DOWNLOAD_EXTS),
        "custom_rules": {},  # ext -> folder_name, e.g. ".torrent": "Torrents"
        "default_confidence": 0.50,
        "auto_confirm": False,
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_conf = json.load(f)
                if isinstance(user_conf, dict):
                    if "folder_names" in user_conf and isinstance(user_conf["folder_names"], dict):
                        config["folder_names"].update(user_conf["folder_names"])
                    if "ignored_extensions" in user_conf and isinstance(user_conf["ignored_extensions"], list):
                        config["ignored_extensions"] = user_conf["ignored_extensions"]
                    if "custom_rules" in user_conf and isinstance(user_conf["custom_rules"], dict):
                        config["custom_rules"].update(user_conf["custom_rules"])
                    if "default_confidence" in user_conf and isinstance(user_conf["default_confidence"], (int, float)):
                        config["default_confidence"] = float(user_conf["default_confidence"])
                    if "auto_confirm" in user_conf:
                        config["auto_confirm"] = bool(user_conf["auto_confirm"])
        except (OSError, json.JSONDecodeError, ValueError, KeyError):
            pass
    return config


def save_config(config: dict[str, Any]) -> None:
    """Persists config to ~/.config/laya/config.json atomically."""
    atomic_write_json(CONFIG_FILE, config)


def load_history(history_file: Path | None = None) -> list[dict[str, Any]]:
    """Loads move journal history from history.json with advisory locking."""
    target_history = history_file or HISTORY_FILE
    if not target_history.exists():
        return []
    lock_file = target_history.with_suffix(".lock")
    with file_lock(lock_file):
        try:
            with open(target_history, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("batches", [])
        except (OSError, json.JSONDecodeError, ValueError, KeyError):
            return []


def save_history(batches: list[dict[str, Any]], history_file: Path | None = None) -> None:
    """Saves move journal history atomically with advisory locking."""
    target_history = history_file or HISTORY_FILE
    lock_file = target_history.with_suffix(".lock")
    with file_lock(lock_file):
        atomic_write_json(target_history, {"batches": batches[-50:]})


def record_batch_moves(
    batch_id: str,
    target_dir: str,
    moves: list[dict[str, Any]],
    status: str = "completed",
    planned_count: int | None = None,
    history_file: Path | None = None,
) -> None:
    """Atomically records or updates a sorting batch in history journal with advisory locking."""
    target_history = history_file or HISTORY_FILE
    lock_file = target_history.with_suffix(".lock")
    with file_lock(lock_file):
        batches = load_history(history_file=target_history)
        existing_idx = None
        for idx, b in enumerate(batches):
            if b.get("batch_id") == batch_id:
                existing_idx = idx
                break

        completed_count = sum(1 for m in moves if m.get("state") == "completed")
        effective_count = completed_count if any("state" in m for m in moves) else len(moves)

        entry = {
            "batch_id": batch_id,
            "timestamp": datetime.datetime.now().isoformat(),
            "target_dir": str(target_dir),
            "status": status,
            "planned_count": planned_count if planned_count is not None else len(moves),
            "count": effective_count,
            "moves": moves,
        }
        if existing_idx is not None:
            batches[existing_idx] = entry
        else:
            batches.append(entry)
        save_history(batches, history_file=target_history)


def check_pending_transactions(history_file: Path | None = None) -> list[dict[str, Any]]:
    """Checks for interrupted, in-progress, or partially rolled-back transactions."""
    batches = load_history(history_file=history_file)
    return [b for b in batches if b.get("status") in ("in_progress", "interrupted", "partial_rollback")]


def inspect_pending_transactions(history_file: Path | None = None) -> list[dict[str, Any]]:
    """Inspects pending, interrupted, or partially rolled-back transactions on disk.

    Examines actual file existence for sources and destinations to determine
    the precise status of every move in interrupted batches without mutating anything.
    """
    batches = load_history(history_file=history_file)
    pending = [b for b in batches if b.get("status") in ("in_progress", "interrupted", "partial_rollback")]
    inspected_batches = []

    for b in pending:
        batch_info = dict(b)
        moves = b.get("moves", [])
        detailed_moves = []
        moved_on_disk = 0
        unmoved_on_disk = 0
        conflict_on_disk = 0
        missing_on_disk = 0

        for m in moves:
            src = Path(m["source"])
            dst = Path(m["dest"])
            src_exists = os.path.lexists(src)
            dst_exists = os.path.lexists(dst)
            restored_to = Path(m["restored_to"]) if m.get("restored_to") else None
            restored_exists = os.path.lexists(restored_to) if restored_to else False

            if dst_exists and not src_exists:
                disk_status = "moved"
                moved_on_disk += 1
            elif src_exists and not dst_exists:
                disk_status = "unmoved"
                unmoved_on_disk += 1
            elif src_exists and dst_exists:
                disk_status = "conflict"
                conflict_on_disk += 1
            elif restored_exists:
                disk_status = "restored"
                unmoved_on_disk += 1
            else:
                disk_status = "missing"
                missing_on_disk += 1

            m_copy = dict(m)
            m_copy["disk_status"] = disk_status
            detailed_moves.append(m_copy)

        batch_info["moves"] = detailed_moves
        batch_info["disk_summary"] = {
            "total": len(moves),
            "moved": moved_on_disk,
            "unmoved": unmoved_on_disk,
            "conflict": conflict_on_disk,
            "missing": missing_on_disk,
        }
        inspected_batches.append(batch_info)

    return inspected_batches


def resume_interrupted_batch(batch_id: str, history_file: Path | None = None) -> bool:
    """Safely resumes an interrupted batch by completing unmoved files."""
    batches = load_history(history_file=history_file)
    target_batch = None
    for b in batches:
        if b.get("batch_id") == batch_id:
            target_batch = b
            break

    if target_batch is None:
        print(f"Error: Batch '{batch_id}' not found.")
        return False

    moves = target_batch.get("moves", [])
    completed_count = 0
    failed_count = 0

    print(f"\nResuming interrupted batch {batch_id}...")
    for m in moves:
        src = Path(m["source"])
        dst = Path(m["dest"])

        if m.get("state") == "completed" or (os.path.lexists(dst) and not os.path.lexists(src)):
            m["state"] = "completed"
            continue

        if not os.path.lexists(src):
            print(f"  [Skipped] Source {src.name} does not exist.")
            m["state"] = "failed"
            m["error"] = "Source file missing"
            failed_count += 1
            continue

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(dst) and dst != src:
                stem, ext = split_stem_and_ext(dst.name)
                counter = 1
                new_dst = dst
                while os.path.lexists(new_dst) and new_dst != src:
                    new_dst = dst.parent / f"{stem}_dup{counter}{ext}"
                    counter += 1
                dst = new_dst
                m["dest"] = str(dst)

            shutil.move(str(src), str(dst))
            m["state"] = "completed"
            m.pop("error", None)
            completed_count += 1
            print(f"  [Moved] {src.name} -> {dst.parent}/")
            save_history(batches, history_file=history_file)
        except (OSError, RuntimeError) as e:
            print(f"  [Failed] Could not move {src.name}: {e}")
            m["state"] = "failed"
            m["error"] = str(e)
            failed_count += 1
            save_history(batches, history_file=history_file)

    if failed_count == 0:
        target_batch["status"] = "completed"
    else:
        target_batch["status"] = "partial_completed"

    save_history(batches, history_file=history_file)
    print(f"\nResume finished: {completed_count} files moved, {failed_count} failed.")
    return failed_count == 0


def dismiss_interrupted_batch(batch_id: str, history_file: Path | None = None) -> bool:
    """Marks an interrupted batch as dismissed so it stops prompting for recovery."""
    batches = load_history(history_file=history_file)
    for b in batches:
        if b.get("batch_id") == batch_id:
            b["status"] = "dismissed"
            save_history(batches, history_file=history_file)
            print(f"Batch {batch_id} marked as dismissed.")
            return True
    print(f"Error: Batch '{batch_id}' not found.")
    return False


def run_startup_recovery(history_file: Path | None = None) -> None:
    """Checks for interrupted transactions on startup and prompts or warns."""
    pending = inspect_pending_transactions(history_file=history_file)
    if not pending:
        return

    # Non-interactive mode: warn to stderr without blocking or mutating files
    if not sys.stdin.isatty():
        for b in pending:
            s = b.get("disk_summary", {})
            sys.stderr.write(
                f"[Laya Startup Alert] Interrupted transaction detected: Batch '{b.get('batch_id')}' "
                f"({s.get('moved', 0)}/{s.get('total', 0)} files moved on disk). "
                "Run 'laya recover' or 'laya undo' to resolve.\n"
            )
        return

    # Interactive mode: prompt user
    print("\n=== Laya Crash Recovery Alert ===\n")
    print(f"Found {len(pending)} interrupted or incomplete transaction(s):\n")
    for b in pending:
        s = b.get("disk_summary", {})
        print(f"  Batch ID: {b.get('batch_id')}")
        print(f"  Target:   {b.get('target_dir')}")
        print(f"  Status:   {b.get('status')} ({s.get('moved', 0)} moved on disk, {s.get('unmoved', 0)} unmoved, {s.get('missing', 0)} missing)")
        print()

    print("Options:")
    print("  [1] Roll back moved files to original locations")
    print("  [2] Resume and complete remaining moves")
    print("  [3] Dismiss alert (retain in history without prompting)")
    print("  [4] Continue current command")

    try:
        choice = input("\nSelect option [1-4] (default: 4): ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    first_batch_id = pending[0].get("batch_id")
    if choice == "1":
        rollback_last_batch(batch_id=first_batch_id, history_file=history_file)
    elif choice == "2":
        if first_batch_id:
            resume_interrupted_batch(batch_id=first_batch_id, history_file=history_file)
    elif choice == "3":
        if first_batch_id:
            dismiss_interrupted_batch(batch_id=first_batch_id, history_file=history_file)
    else:
        pass


def rollback_last_batch(
    batch_id: str | None = None,
    history_file: Path | None = None
) -> bool:
    """Reverts the last (or specified) sorting transaction batch.

    Fully idempotent, crash-safe, and lossless:
    - Assigns distinct rollback transaction ID
    - Persists each restored file incrementally
    - Records actual restored_to paths (including collisions)
    - Recognizes already-restored files on retries
    - Retains failed and unresolved entries in the journal
    - Only removes the batch when 100% of moves are confirmed restored
    """
    batches = load_history(history_file=history_file)
    if not batches:
        print("No organization history found to roll back.")
        return False

    target_batch = None
    target_idx = -1
    if batch_id:
        for idx, b in enumerate(reversed(batches)):
            if b.get("batch_id") == batch_id:
                target_batch = b
                target_idx = len(batches) - 1 - idx
                break
    else:
        target_batch = batches[-1]
        target_idx = len(batches) - 1

    if not target_batch:
        print(f"Error: Batch '{batch_id}' not found in history.")
        return False

    moves = target_batch.get("moves", [])
    if not moves:
        # Empty batch with 0 moves recorded, safe to remove
        batches.pop(target_idx)
        save_history(batches, history_file=history_file)
        return True

    rollback_tx_id = f"rb_{target_batch.get('batch_id')}_{int(time.time() * 1000)}"
    print(f"\nRolling back batch {target_batch.get('batch_id')} ({len(moves)} files) [tx: {rollback_tx_id}]...")

    reverted = 0
    folders_to_clean: set[Path] = set()
    unresolved_moves: list[dict[str, Any]] = []

    for item in reversed(moves):
        src = Path(item["source"])
        dst = Path(item["dest"])
        is_symlink = item.get("is_symlink", False)
        orig_target = item.get("original_target")
        restored_to = item.get("restored_to")
        state = item.get("state", "completed")

        # Skip moves that never actually executed on disk
        if state == "planned" and not os.path.lexists(dst) and os.path.lexists(src):
            item["rollback_state"] = "unmoved_original_preserved"
            item["rollback_tx_id"] = rollback_tx_id
            continue

        # Check if already restored in previous rollback attempt
        if item.get("rollback_state") == "restored":
            check_target = Path(restored_to) if restored_to else src
            if not os.path.lexists(dst) and os.path.lexists(check_target):
                print(f"  [Already Restored] {dst.name} -> {check_target.parent}/")
                reverted += 1
                folders_to_clean.add(dst.parent)
                continue

        if os.path.lexists(dst):
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                final_src = src
                counter = 1
                stem, ext = split_stem_and_ext(src.name)
                while os.path.lexists(final_src) and final_src != dst:
                    final_src = src.parent / f"{stem}_restored{counter}{ext}"
                    counter += 1

                if is_symlink and orig_target is not None:
                    if os.path.lexists(final_src):
                        final_src.unlink()
                    final_src.symlink_to(orig_target)
                    dst.unlink()
                else:
                    shutil.move(str(dst), str(final_src))

                print(f"  [Restored] {dst.name} -> {final_src.parent}/")
                reverted += 1
                folders_to_clean.add(dst.parent)
                item["restored_to"] = str(final_src)
                item["rollback_state"] = "restored"
                item["rollback_tx_id"] = rollback_tx_id
                item.pop("last_rollback_error", None)

                save_history(batches, history_file=history_file)
            except (OSError, RuntimeError) as e:
                print(f"  [Failed] Could not restore {dst.name}: {e}")
                err_item = dict(item)
                err_item["rollback_state"] = "failed"
                err_item["last_rollback_error"] = str(e)
                err_item["rollback_tx_id"] = rollback_tx_id
                unresolved_moves.append(err_item)
                save_history(batches, history_file=history_file)
        else:
            # Destination missing on disk. Check if already restored to src or restored_to
            check_target = Path(restored_to) if restored_to else src
            if os.path.lexists(check_target):
                print(f"  [Already Restored] {dst.name} -> {check_target.parent}/")
                reverted += 1
                item["rollback_state"] = "restored"
                item["restored_to"] = str(check_target)
                item["rollback_tx_id"] = rollback_tx_id
                item.pop("last_rollback_error", None)
                save_history(batches, history_file=history_file)
            else:
                print(f"  [Skipped] {dst} no longer exists.")
                err_item = dict(item)
                err_item["rollback_state"] = "unresolved_missing"
                err_item["last_rollback_error"] = "Destination file no longer exists"
                err_item["rollback_tx_id"] = rollback_tx_id
                unresolved_moves.append(err_item)
                save_history(batches, history_file=history_file)

    # Clean empty category folders if left empty, innermost first
    for folder in sorted(folders_to_clean, key=lambda p: len(str(p)), reverse=True):
        try:
            if folder.exists() and folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
                print(f"  [Cleaned empty folder] {folder.name}/")
        except OSError:
            pass

    if not unresolved_moves:
        # All files restored cleanly: remove batch from history
        batches.pop(target_idx)
        save_history(batches, history_file=history_file)
        print(f"\nRollback complete. Successfully restored {reverted}/{len(moves)} files.")
        return True

    # Partial rollback: retain unresolved items in journal so records are not lost!
    target_batch["moves"] = unresolved_moves
    target_batch["count"] = len(unresolved_moves)
    target_batch["status"] = "partial_rollback"
    target_batch["rollback_tx_id"] = rollback_tx_id
    save_history(batches, history_file=history_file)
    print(
        f"\nRollback partial. Restored {reverted}/{len(moves)} files. "
        f"{len(unresolved_moves)} unresolved record(s) retained in history."
    )
    return False
    print(
        f"\nRollback partial. Restored {reverted}/{len(moves)} files. "
        f"{len(unresolved_moves)} unresolved record(s) retained in history."
    )
    return False


def extract_pdf_snippet(file_path: Path, max_chars: int = 1000) -> str:
    """Pure Python minimal PDF text & metadata extractor (no external dependencies)."""
    try:
        with open(file_path, "rb") as f:
            data = f.read(131072)
        extracted: list[str] = []

        # Metadata dictionary matches /Title, /Subject, /Keywords, /Author
        meta_matches = re.findall(rb'/(Title|Subject|Keywords|Author)\s*\(([^)]+)\)', data)
        for key, val in meta_matches:
            try:
                t = val.decode("utf-8", errors="ignore").strip()
                if t:
                    extracted.append(f"{key.decode()}: {t}")
            except (UnicodeDecodeError, ValueError, AttributeError):
                pass

        # Text stream operators (text) Tj
        tj_matches = re.findall(rb'\(([^()]{2,})\)\s*Tj', data)
        for tm in tj_matches:
            try:
                t = tm.decode("utf-8", errors="ignore").strip()
                if len(t) > 1 and t not in extracted:
                    extracted.append(t)
            except (UnicodeDecodeError, ValueError, AttributeError):
                pass

        # Text stream array operators [(part1) 10 (part2)] TJ
        tj_arrays = re.findall(rb'\[(.*?)\]\s*TJ', data)
        for arr in tj_arrays:
            parts = re.findall(rb'\(([^()]+)\)', arr)
            combined = " ".join(p.decode("utf-8", errors="ignore").strip() for p in parts if p.strip())
            if len(combined) > 2 and combined not in extracted:
                extracted.append(combined)

        # XML / XMP metadata if present
        xmp_matches = re.findall(rb'<dc:(?:title|description)[^>]*>[\s\S]*?<rdf:li[^>]*>([^<]+)</rdf:li>', data)
        for xm in xmp_matches:
            try:
                t = xm.decode("utf-8", errors="ignore").strip()
                if t and t not in extracted:
                    extracted.append(t)
            except (UnicodeDecodeError, ValueError, AttributeError):
                pass

        snippet = " ".join(extracted).strip()
        return snippet[:max_chars]
    except (OSError, ValueError):
        return ""


# ponytail: stdlib text extraction helper with 1KB ceiling to keep forward pass instant
def extract_file_sample(file_path: Path, max_chars: int = 1000) -> str:
    """Extract filename and text content snippet for Laya context."""
    ext = get_compound_extension(file_path)
    try:
        size = file_path.stat().st_size
    except OSError:
        size = 0
    info = f"Filename: {file_path.name}\nExtension: {ext}\nSize: {size} bytes\n"

    text_exts = {
        ".txt", ".md", ".json", ".csv", ".tsv", ".py", ".js", ".ts", ".jsx", ".tsx",
        ".rs", ".go", ".cpp", ".c", ".h", ".java", ".html", ".css", ".log", ".yaml",
        ".yml", ".sh", ".sql", ".xml", ".toml", ".env", ".ini", ".conf", ".d.ts"
    }

    if ext in text_exts:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                snippet = f.read(max_chars)
                if snippet:
                    info += f"Content Snippet:\n{snippet}"
        except (OSError, UnicodeDecodeError):
            pass
    elif ext == ".pdf":
        pdf_snippet = extract_pdf_snippet(file_path, max_chars=max_chars)
        if pdf_snippet:
            info += f"Content Snippet:\n{pdf_snippet}\n"
    return info


def get_laya_questions() -> dict[str, Any]:
    return {
        "category": {
            "type": "choice",
            "instructions": "Which folder category should this file be organized into?",
            "criteria": {
                "Financial": "invoices, receipts, tax documents, bank statements, billing, paystubs, financial reports",
                "Documents": "resumes, CVs, contracts, letters, notes, reports, PDFs, academic papers, articles",
                "Code_and_Scripts": "source code files, Python, JavaScript, TypeScript, Rust, C++, Go, HTML, CSS, Shell scripts, SQL",
                "Data_and_Configs": "JSON, CSV, TSV, YAML, TOML, XML, env configuration files, database dumps",
                "Logs_and_Diagnostics": "system log files, crash dumps, build logs, debug traces, stack traces",
                "Images_and_Graphics": "PNG, JPG, JPEG, SVG, WebP, GIF, PSD, AI, Figma exports, screenshots",
                "Audio_and_Music": "MP3, WAV, FLAC, AAC, OGG, M4A, podcasts, voice recordings, music tracks",
                "Video_and_Movies": "MP4, MKV, AVI, MOV, WebM, screen recordings, video clips, movies",
                "Archives_and_Installers": "ZIP, TAR, GZ, 7Z, RAR, ISO, DEB, RPM, AppImage, EXE, DMG, software installers",
                "Books_and_Manuals": "EPUB, MOBI, AZW3, user manuals, technical documentation PDFs, ebooks",
                "Design_and_3D": "STL, OBJ, BLEND, STEP, CAD drawings, 3D models, graphics projects",
                "Other": "everything else that does not clearly fit above"
            }
        },
        "is_temporary_junk": {
            "type": "noul",
            "instructions": "Is this a temporary download, cache, or scrap log file that should be flagged for cleaning?"
        }
    }


class HeuristicRouter:
    """Built-in fast heuristic classifier when upstream laya neural engine or PyTorch is unavailable."""

    EXT_GROUPS: ClassVar[dict[str, set[str]]] = {
        "Code_and_Scripts": {
            ".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".c", ".cpp", ".cc", ".h", ".hpp",
            ".cs", ".java", ".html", ".css", ".scss", ".sass", ".sh", ".bash", ".zsh", ".sql",
            ".php", ".rb", ".swift", ".kt", ".lua", ".r", ".m", ".asm",
            ".d.ts", ".spec.ts", ".test.ts", ".spec.js", ".test.js"
        },
        "Data_and_Configs": {
            ".json", ".yaml", ".yml", ".toml", ".xml", ".ini", ".conf", ".env", ".tsv", ".csv"
        },
        "Logs_and_Diagnostics": {
            ".log", ".trace", ".dump", ".dmp", ".stacktrace"
        },
        "Images_and_Graphics": {
            ".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".bmp", ".ico", ".tiff", ".psd", ".ai"
        },
        "Audio_and_Music": {
            ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"
        },
        "Video_and_Movies": {
            ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v"
        },
        "Archives_and_Installers": {
            ".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".iso", ".deb", ".rpm", ".appimage", ".exe", ".dmg", ".pkg", ".msi",
            ".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst", ".tar.br", ".backup.zip"
        },
        "Books_and_Manuals": {
            ".epub", ".mobi", ".azw3", ".cbr", ".cbz"
        },
        "Design_and_3D": {
            ".stl", ".obj", ".blend", ".step", ".stp", ".fbx", ".3ds", ".dxf", ".dwg"
        },
        "Documents": {
            ".docx", ".doc", ".odt", ".rtf", ".txt", ".pages", ".md", ".tex", ".pptx", ".ppt"
        }
    }

    FINANCIAL_KEYWORDS: ClassVar[set[str]] = {
        "invoice", "receipt", "billing", "bill", "tax", "statement", "paystub", "payroll",
        "salary", "expense", "bank", "financial", "payment", "due", "amount", "usd", "inr"
    }

    MANUAL_KEYWORDS: ClassVar[set[str]] = {
        "manual", "handbook", "guide", "documentation", "tutorial", "spec", "specification"
    }

    def predict(self, sample_text: str, questions: dict[str, Any]) -> dict[str, Any]:
        lower_sample = sample_text.lower()
        ext = ""
        filename = ""
        for line in sample_text.splitlines():
            if line.startswith("Filename:"):
                filename = line.split(":", 1)[1].strip()
            elif line.startswith("Extension:"):
                ext = line.split(":", 1)[1].strip().lower()

        if not ext and filename.startswith("."):
            ext = filename.lower()
        if filename.startswith(".env"):
            ext = ".env"

        is_junk = is_junk_candidate(filename)

        # Check financial signals
        is_financial = any(kw in lower_sample for kw in self.FINANCIAL_KEYWORDS) and (
            ext in {".pdf", ".csv", ".xlsx", ".xls", ".txt"} or not ext
        )

        # Check manual/documentation signals for PDFs
        is_manual = ext == ".pdf" and any(kw in lower_sample for kw in self.MANUAL_KEYWORDS)

        # Check diagnostic logs in text files with crash/trace keywords
        is_diag_txt = ext == ".txt" and any(
            k in lower_sample for k in ("traceback", "stacktrace", "nullpointer", "fatal error", "exception:")
        )

        if is_financial:
            category = "Financial"
            confidence = 0.95
        elif is_diag_txt:
            category = "Logs_and_Diagnostics"
            confidence = 0.90
        elif is_manual:
            category = "Books_and_Manuals"
            confidence = 0.90
        elif ext == ".pdf":
            category = "Documents"
            confidence = 0.88
        else:
            category = "Other"
            confidence = 0.70
            for cat, exts in self.EXT_GROUPS.items():
                if ext in exts:
                    category = cat
                    confidence = 0.95
                    break

        return {
            "answers": {
                "category": {
                    "choice": category,
                    "confidence": confidence,
                    "probabilities": {category: confidence}
                },
                "is_temporary_junk": {
                    "noul": 0.95 if is_junk else 0.05
                }
            }
        }


_ROUTER_CACHE: tuple[Any, str] | None = None


def get_router(force_fallback: bool = False) -> tuple[Any, str]:
    """Returns upstream Laya Router if installed; otherwise falls back to fast HeuristicRouter.

    Cached to prevent repeated instantiation.
    """
    global _ROUTER_CACHE
    if force_fallback:
        return HeuristicRouter(), "heuristic"
    if _ROUTER_CACHE is not None:
        return _ROUTER_CACHE
    try:
        from laya import Router
        _ROUTER_CACHE = (Router(), "neural")
    except (ImportError, RuntimeError, AttributeError, OSError, TypeError, ValueError):
        _ROUTER_CACHE = (HeuristicRouter(), "heuristic")
    return _ROUTER_CACHE


@dataclass
class PlannedMove:
    source: Path
    destination: Path
    category: str
    confidence: float
    reason: str
    engine: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "destination": str(self.destination),
            "category": self.category,
            "confidence": self.confidence,
            "reason": self.reason,
            "engine": self.engine,
        }


def scan_files(target_path: Path, ignored_exts: tuple[str, ...] = ()) -> list[Path]:
    """Discovers files in target_path skipping active downloads and hidden files."""
    files: list[Path] = []
    for f in sorted(target_path.iterdir()):
        if not (f.is_file() or f.is_symlink()):
            continue
        if f.is_dir() and not f.is_symlink():
            continue
        if f.name.startswith(".") and not f.name.startswith(".~"):
            continue
        name_lower = f.name.lower()
        if f.name.startswith(".~") or any(name_lower.endswith(ext) for ext in ignored_exts):
            continue
        files.append(f)
    return files


def plan_organization(
    target_dir: str | Path,
    output_dir: str | Path | None = None,
    min_confidence: float | None = None,
    config_override: dict[str, Any] | None = None,
    router_bundle: tuple[Any, str] | None = None,
) -> tuple[list[PlannedMove], dict[str, int], dict[str, Any]]:
    """Separates planning from movement, generating validated PlannedMoves and statistics."""
    config = config_override or load_config()
    folder_mapping = config.get("folder_names", DEFAULT_FOLDER_NAMES)
    ignored_exts = tuple(config.get("ignored_extensions", DEFAULT_ACTIVE_DOWNLOAD_EXTS))
    custom_rules = config.get("custom_rules", {})
    confidence_threshold = validate_confidence_threshold(
        min_confidence if min_confidence is not None else config.get("default_confidence", 0.50)
    )

    target_path = Path(target_dir).expanduser().resolve()
    if not target_path.exists() or not target_path.is_dir():
        raise FileNotFoundError(f"Target directory '{target_dir}' does not exist.")

    dest_base = Path(output_dir).expanduser().resolve() if output_dir else target_path

    router, engine_type = router_bundle if router_bundle is not None else get_router()
    questions = get_laya_questions()

    files = scan_files(target_path, ignored_exts)
    planned_moves: list[PlannedMove] = []
    stats: dict[str, int] = {}

    for file_path in files:
        ext = get_compound_extension(file_path)

        if is_junk_candidate(file_path):
            category_key = "Junk_Candidates"
            confidence = 0.95
            reason = "Explicit scrap pattern"
            engine = "rule"
        elif ext in custom_rules:
            category_key = custom_rules[ext]
            confidence = 1.0
            reason = f"Custom extension rule for {ext}"
            engine = "rule"
        else:
            sample_text = extract_file_sample(file_path)
            res = router.predict(sample_text, questions)

            cat_ans = res["answers"]["category"]
            choice = cat_ans.get("choice", "Other")
            probs = cat_ans.get("probabilities", {})
            conf = float(probs.get(choice, cat_ans.get("confidence", 0.70)))

            if conf < confidence_threshold:
                category_key = "Uncertain"
                confidence = conf
                reason = f"Confidence {conf:.2f} below threshold {confidence_threshold:.2f}"
            else:
                category_key = choice
                confidence = conf
                reason = f"Classified by {engine_type} engine"
            engine = engine_type

        category_folder = folder_mapping.get(category_key, category_key)
        dest_folder = dest_base / category_folder
        planned_dest = dest_folder / file_path.name

        move = PlannedMove(
            source=file_path,
            destination=planned_dest,
            category=category_folder,
            confidence=confidence,
            reason=reason,
            engine=engine,
        )
        planned_moves.append(move)
        stats[category_folder] = stats.get(category_folder, 0) + 1

    return planned_moves, stats, {
        "engine_type": engine_type,
        "target_dir": target_path,
        "dest_base": dest_base,
        "confidence_threshold": confidence_threshold,
    }


def execute_plan(
    planned_moves: list[PlannedMove],
    batch_id: str | None = None,
    target_dir: str | Path | None = None,
    history_file: Path | None = None,
) -> list[dict[str, Any]]:
    """Executes approved PlannedMoves safely with per-file intent journaling and crash-safe rollback."""
    if batch_id is None:
        batch_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # Map source paths to planned/actual destinations for robust symlink resolution
    # Use abspath (not resolve()) to avoid prematurely dereferencing symlinks
    planned_dest_map = {Path(os.path.abspath(move.source)): move.destination for move in planned_moves}
    actual_dest_map: dict[Path, Path] = {}
    target_dir_str = str(target_dir) if target_dir else ""

    # Initialize all planned moves with "planned" intent in journal before any file operation begins
    initial_moves: list[dict[str, Any]] = []
    for move in planned_moves:
        is_symlink = move.source.is_symlink()
        orig_target = None
        if is_symlink:
            try:
                orig_target = os.readlink(move.source)
            except OSError:
                pass
        initial_moves.append({
            "source": str(move.source),
            "dest": str(move.destination),
            "category": move.category,
            "confidence": move.confidence,
            "reason": move.reason,
            "engine": move.engine,
            "is_symlink": is_symlink,
            "original_target": orig_target,
            "state": "planned",
        })

    # Record initial transaction intent with all planned moves prior to touching any file on disk
    if target_dir:
        record_batch_moves(
            batch_id=batch_id,
            target_dir=target_dir_str,
            moves=initial_moves,
            status="in_progress",
            planned_count=len(planned_moves),
            history_file=history_file,
        )

    moved_records: list[dict[str, Any]] = [dict(m) for m in initial_moves]
    idx = 0

    try:
        for idx, move in enumerate(planned_moves):
            src = move.source
            dest = move.destination
            dest_folder = dest.parent
            dest_folder.mkdir(parents=True, exist_ok=True)

            # Collision-proof atomic file move (_dup1, _dup2)
            if os.path.lexists(dest) and dest != src:
                stem, ext = split_stem_and_ext(dest.name)
                counter = 1
                new_dest = dest
                while os.path.lexists(new_dest) and new_dest != src:
                    new_dest = dest_folder / f"{stem}_dup{counter}{ext}"
                    counter += 1
                dest = new_dest

            actual_dest_map[Path(os.path.abspath(src))] = dest
            # Update intended destination in journal record before moving
            moved_records[idx]["dest"] = str(dest)

            is_symlink = src.is_symlink()
            original_target = None
            if is_symlink:
                raw_target = os.readlink(src)
                original_target = raw_target
                if not os.path.isabs(raw_target):
                    resolved_raw = Path(os.path.abspath(src.parent / raw_target))
                else:
                    resolved_raw = Path(os.path.abspath(raw_target))

                # If the target file is also being moved in this batch, track its new destination
                if resolved_raw in actual_dest_map:
                    canonical_target = str(actual_dest_map[resolved_raw])
                elif resolved_raw in planned_dest_map:
                    canonical_target = str(planned_dest_map[resolved_raw])
                else:
                    canonical_target = str(resolved_raw)

                dest.symlink_to(canonical_target)
                src.unlink()
            else:
                shutil.move(str(src), str(dest))

            moved_records[idx]["original_target"] = original_target
            moved_records[idx]["state"] = "completed"

            # Incremental journal record after each move
            if target_dir:
                record_batch_moves(
                    batch_id=batch_id,
                    target_dir=target_dir_str,
                    moves=moved_records,
                    status="in_progress",
                    planned_count=len(planned_moves),
                    history_file=history_file,
                )
    except Exception as exc:
        # Mark interrupted move as failed, retain all planned and completed records in journal
        if idx < len(moved_records) and moved_records[idx]["state"] != "completed":
            moved_records[idx]["state"] = "failed"
            moved_records[idx]["error"] = str(exc)
        if target_dir:
            record_batch_moves(
                batch_id=batch_id,
                target_dir=target_dir_str,
                moves=moved_records,
                status="interrupted",
                planned_count=len(planned_moves),
                history_file=history_file,
            )
        raise

    if target_dir:
        record_batch_moves(
            batch_id=batch_id,
            target_dir=target_dir_str,
            moves=moved_records,
            status="completed",
            planned_count=len(planned_moves),
            history_file=history_file,
        )

    return moved_records


# Modular Architecture Interfaces
class Scanner:
    """Discovers files and extracts metadata including compound extensions and symlinks."""

    @staticmethod
    def get_extension(path: Path | str) -> str:
        return get_compound_extension(path)

    @staticmethod
    def split_stem_and_ext(path: Path | str) -> tuple[str, str]:
        return split_stem_and_ext(path)

    @staticmethod
    def is_junk(path: Path | str) -> bool:
        return is_junk_candidate(path)

    @staticmethod
    def scan(target_dir: Path, ignored_exts: tuple[str, ...] = ()) -> list[Path]:
        return scan_files(target_dir, ignored_exts)


class Extractor:
    """Extracts text snippets and PDF stream content with 1KB ceiling."""

    @staticmethod
    def extract_snippet(file_path: Path, max_chars: int = 1000) -> str:
        return extract_file_sample(file_path, max_chars=max_chars)

    @staticmethod
    def extract_pdf(file_path: Path, max_chars: int = 1000) -> str:
        return extract_pdf_snippet(file_path, max_chars=max_chars)


class Classifier:
    """Classification engine handling neural and heuristic routing with calibrated certainty."""

    def __init__(self, router=None, engine_type: str | None = None):
        if router is None:
            self.router, self.engine_type = get_router()
        else:
            self.router = router
            self.engine_type = engine_type or "custom"

    def predict(self, sample_text: str, questions: dict[str, Any] | None = None) -> dict[str, Any]:
        q = questions or get_laya_questions()
        return self.router.predict(sample_text, q)


class Planner:
    """Separates planning from file movement, producing validated PlannedMoves."""

    @staticmethod
    def validate_threshold(val: Any) -> float:
        return validate_confidence_threshold(val)

    @staticmethod
    def create_plan(
        target_dir: str | Path,
        output_dir: str | Path | None = None,
        min_confidence: float | None = None,
        config: dict[str, Any] | None = None,
        router_bundle: tuple[Any, str] | None = None,
    ) -> tuple[list[PlannedMove], dict[str, int], dict[str, Any]]:
        return plan_organization(
            target_dir=target_dir,
            output_dir=output_dir,
            min_confidence=min_confidence,
            config_override=config,
            router_bundle=router_bundle,
        )


class Executor:
    """Executes planned moves safely with collision handling and transaction recording."""

    @staticmethod
    def execute(
        planned_moves: list[PlannedMove],
        batch_id: str | None = None,
        target_dir: str | Path | None = None,
        history_file: Path | None = None,
    ) -> list[dict[str, Any]]:
        return execute_plan(
            planned_moves=planned_moves,
            batch_id=batch_id,
            target_dir=target_dir,
            history_file=history_file,
        )


class HistoryManager:
    """Manages transaction journal and rollbacks in history.json."""

    @staticmethod
    def load(history_file: Path | None = None) -> list[dict[str, Any]]:
        return load_history(history_file=history_file)

    @staticmethod
    def save(batches: list[dict[str, Any]], history_file: Path | None = None) -> None:
        save_history(batches=batches, history_file=history_file)

    @staticmethod
    def record(
        batch_id: str,
        target_dir: str,
        moves: list[dict[str, Any]],
        status: str = "completed",
        planned_count: int | None = None,
        history_file: Path | None = None,
    ) -> None:
        record_batch_moves(
            batch_id=batch_id,
            target_dir=target_dir,
            moves=moves,
            status=status,
            planned_count=planned_count,
            history_file=history_file,
        )

    @staticmethod
    def check_pending(history_file: Path | None = None) -> list[dict[str, Any]]:
        return check_pending_transactions(history_file=history_file)

    @staticmethod
    def rollback(batch_id: str | None = None, history_file: Path | None = None) -> bool:
        return rollback_last_batch(batch_id=batch_id, history_file=history_file)


def scan_directory(
    target_dir: str | Path,
    min_confidence: float | None = None,
    json_output: bool = False,
    config_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Discovers and displays classification breakdown without creating folders or moving files."""
    target_path = Path(target_dir).expanduser().resolve()
    if not target_path.exists() or not target_path.is_dir():
        print(f"Error: Target directory '{target_dir}' does not exist.")
        sys.exit(1)

    planned_moves, stats, meta = plan_organization(
        target_dir=target_path,
        min_confidence=min_confidence,
        config_override=config_override,
    )

    engine_type = meta["engine_type"]
    file_results = [m.to_dict() for m in planned_moves]

    report = {
        "target_dir": str(target_path),
        "total_files": len(planned_moves),
        "breakdown": stats,
        "files": file_results,
        "engine_used": engine_type,
    }

    if json_output:
        print(json.dumps(report, indent=2))
        return report

    print(f"\nLaya Scan: {target_path}")
    print(f"Engine: {engine_type.upper()} | Discovered: {len(planned_moves)} file(s)\n")

    if not planned_moves:
        print("No files found to classify.")
        return report

    print("Classification Breakdown:")
    total = len(planned_moves)
    for cat, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
        pct = (count / total * 100) if total > 0 else 0
        print(f"  * {cat:24} : {count:3d} file(s) ({pct:5.1f}%)")

    print("\nProposed Classification Details:")
    table_rows = []
    for m in planned_moves:
        conf_str = f"{int(m.confidence * 100)}%" if m.confidence is not None else "100%"
        table_rows.append([
            m.source.name[:32],
            m.category,
            conf_str,
            m.reason[:36],
        ])
    print(format_table(["File", "Category", "Conf", "Reason"], table_rows, ["left", "left", "right", "left"]))
    return report


def inspect_directory(
    target_dir: str | Path,
    json_output: bool = False,
) -> dict[str, Any]:
    """Detailed breakdown of directory: file counts, categories, sizes, top extensions."""
    target_path = Path(target_dir).expanduser().resolve()
    if not target_path.exists() or not target_path.is_dir():
        print(f"Error: Target directory '{target_dir}' does not exist.")
        sys.exit(1)

    files = []
    subdirs = []
    total_bytes = 0

    for item in sorted(target_path.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir() and not item.is_symlink():
            subdirs.append(item)
        elif item.is_file() or item.is_symlink():
            try:
                sz = item.stat().st_size
                files.append((item, sz))
                total_bytes += sz
            except OSError:
                continue

    brackets = {
        "< 10 KB": 0,
        "10 KB - 1 MB": 0,
        "1 MB - 100 MB": 0,
        "> 100 MB": 0,
    }
    ext_counts: dict[str, int] = {}
    ext_sizes: dict[str, int] = {}

    for item, sz in files:
        ext = get_compound_extension(item) or "[no ext]"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1
        ext_sizes[ext] = ext_sizes.get(ext, 0) + sz

        if sz < 10 * 1024:
            brackets["< 10 KB"] += 1
        elif sz <= 1024 * 1024:
            brackets["10 KB - 1 MB"] += 1
        elif sz <= 100 * 1024 * 1024:
            brackets["1 MB - 100 MB"] += 1
        else:
            brackets["> 100 MB"] += 1

    _planned_moves, stats, meta = plan_organization(target_dir=target_path)
    engine = meta["engine_type"]

    top_exts_by_count = sorted(ext_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_exts_by_size = sorted(ext_sizes.items(), key=lambda x: x[1], reverse=True)[:5]

    total_files = len(files)
    category_percentages = {
        cat: round((cnt / total_files * 100), 1) if total_files > 0 else 0.0
        for cat, cnt in stats.items()
    }

    report = {
        "target_dir": str(target_path),
        "total_files": total_files,
        "total_subdirectories": len(subdirs),
        "total_size_bytes": total_bytes,
        "total_size_formatted": format_size(total_bytes),
        "avg_size_bytes": (total_bytes / total_files) if total_files > 0 else 0,
        "avg_size_formatted": format_size((total_bytes / total_files) if total_files > 0 else 0),
        "size_distribution": brackets,
        "category_counts": stats,
        "category_percentages": category_percentages,
        "top_extensions_by_count": top_exts_by_count,
        "top_extensions_by_size": [
            {"extension": ext, "bytes": sz, "formatted": format_size(sz)}
            for ext, sz in top_exts_by_size
        ],
        "engine_used": engine,
    }

    if json_output:
        print(json.dumps(report, indent=2))
        return report

    print(f"\nLaya Inspection Report: {target_path}")
    print("=" * 64)
    print(f"Total Files       : {total_files}")
    print(f"Subdirectories    : {len(subdirs)}")
    print(f"Total Disk Space  : {format_size(total_bytes)}")
    print(f"Average File Size : {format_size((total_bytes / total_files) if total_files > 0 else 0)}")
    print(f"Classifier Engine : {engine.upper()}")
    print("-" * 64)

    print("Category Breakdown:")
    for cat, cnt in sorted(stats.items(), key=lambda x: x[1], reverse=True):
        pct = category_percentages.get(cat, 0.0)
        print(f"  * {cat:24} : {cnt:3d} file(s) ({pct:5.1f}%)")

    print("\nSize Distribution:")
    for bracket, count in brackets.items():
        print(f"  * {bracket:24} : {count:3d} file(s)")

    print("\nTop File Extensions (by count):")
    for ext, cnt in top_exts_by_count:
        print(f"  * {ext:12} : {cnt} file(s)")

    print("\nTop File Extensions (by size):")
    for ext_info in report["top_extensions_by_size"]:
        print(f"  * {ext_info['extension']:12} : {ext_info['formatted']}")
    print("=" * 64)
    return report


def find_duplicates(
    target_dir: str | Path,
    min_size: int = 1,
    json_output: bool = False,
) -> dict[str, Any]:
    """Detects identical files using SHA-256 hashes on equal-sized files and reports candidates."""
    target_path = Path(target_dir).expanduser().resolve()
    if not target_path.exists() or not target_path.is_dir():
        print(f"Error: Target directory '{target_dir}' does not exist.")
        sys.exit(1)

    size_map: dict[int, list[Path]] = {}
    for item in sorted(target_path.iterdir()):
        if item.is_file() and not item.is_symlink() and not item.name.startswith("."):
            try:
                sz = item.stat().st_size
                if sz >= min_size:
                    size_map.setdefault(sz, []).append(item)
            except OSError:
                continue

    dup_groups = []
    total_wasted = 0
    total_dup_files = 0

    for sz, file_list in size_map.items():
        if len(file_list) < 2:
            continue
        hash_map: dict[str, list[str]] = {}
        for p in file_list:
            try:
                h = hashlib.sha256()
                with open(p, "rb") as fp:
                    while chunk := fp.read(65536):
                        h.update(chunk)
                hash_map.setdefault(h.hexdigest(), []).append(str(p))
            except OSError:
                continue

        for digest, paths in hash_map.items():
            if len(paths) > 1:
                wasted = (len(paths) - 1) * sz
                total_wasted += wasted
                total_dup_files += len(paths) - 1
                dup_groups.append({
                    "sha256": digest,
                    "size_bytes": sz,
                    "size_formatted": format_size(sz),
                    "count": len(paths),
                    "wasted_bytes": wasted,
                    "wasted_formatted": format_size(wasted),
                    "files": sorted(paths),
                })

    dup_groups.sort(key=lambda g: g["wasted_bytes"], reverse=True)

    report = {
        "target_dir": str(target_path),
        "total_duplicate_groups": len(dup_groups),
        "total_duplicate_files": total_dup_files,
        "total_wasted_bytes": total_wasted,
        "total_wasted_formatted": format_size(total_wasted),
        "duplicate_groups": dup_groups,
    }

    if json_output:
        print(json.dumps(report, indent=2))
        return report

    print(f"\nLaya Duplicate Detection: {target_path}")
    print("=" * 64)
    if not dup_groups:
        print("No duplicate files detected.")
        print("=" * 64)
        return report

    print(f"Found {len(dup_groups)} duplicate group(s), {total_dup_files} redundant file(s).")
    print(f"Total Recoverable Space: {format_size(total_wasted)}\n")

    for idx, grp in enumerate(dup_groups, 1):
        print(f"Group #{idx} [SHA-256: {grp['sha256'][:12]}...] — {grp['size_formatted']} each ({grp['wasted_formatted']} wasted):")
        for i, fpath in enumerate(grp["files"]):
            label = "Original" if i == 0 else "Duplicate"
            print(f"  [{label}] {Path(fpath).name} ({fpath})")
        print()
    print("=" * 64)
    return report


def organize_directory(
    target_dir: str,
    output_dir: str | None = None,
    dry_run: bool = False,
    apply: bool = False,
    auto_confirm: bool = False,
    min_confidence: float | None = None,
    json_output: bool = False,
    config_override: dict[str, Any] | None = None,
    router_bundle: tuple[Any, str] | None = None,
    history_file: Path | None = None,
) -> dict[str, Any]:
    """Organizes files in target_dir into categorized subdirectories with rollback journaling."""
    config = config_override or load_config()

    target_path = Path(target_dir).expanduser().resolve()
    if not target_path.exists() or not target_path.is_dir():
        print(f"Error: Target directory '{target_dir}' does not exist.")
        sys.exit(1)

    dest_base = Path(output_dir).expanduser().resolve() if output_dir else target_path

    planned_moves, stats, meta = plan_organization(
        target_dir=target_path,
        output_dir=dest_base,
        min_confidence=min_confidence,
        config_override=config,
        router_bundle=router_bundle,
    )

    engine_type = meta["engine_type"]

    if not planned_moves:
        if not json_output:
            print("No files found to organize.")
        res = {"count": 0, "stats": {}, "batch_id": None, "plan": []}
        if json_output:
            print(json.dumps(res, indent=2))
        return res

    # Execution consent protocol:
    # 1. If dry_run is requested (and apply not set): strictly preview.
    # 2. If apply or auto_confirm is provided:
    #    - If interactive terminal and not auto_confirm: prompt user once to confirm.
    #    - If non-interactive terminal with apply/auto_confirm: execute.
    # 3. If neither apply nor auto_confirm is provided:
    #    - If non-interactive terminal (scripts, pipes, CI): strictly dry_run preview.
    #      Never treat non-interactive execution as consent to move files!
    #    - If interactive terminal: display preview and prompt user.
    if dry_run and not apply:
        is_dry_run = True
    elif apply or auto_confirm:
        if apply and not auto_confirm and sys.stdin.isatty():
            table_rows = [
                [
                    m.source.name[:32],
                    f"{m.category}/{m.destination.name}"[:32],
                    f"{int(m.confidence * 100)}%" if m.confidence is not None else "100%",
                    m.reason[:36],
                ]
                for m in planned_moves
            ]
            print(f"\nLaya Organize: {target_path}")
            print(f"Engine: {engine_type.upper()} | Files to organize: {len(planned_moves)}\n")
            print(format_table(["File", "Target Destination", "Conf", "Reason"], table_rows, ["left", "left", "right", "left"]))
            try:
                confirm = input(f"\nExecute organization for {len(planned_moves)} file(s)? [y/N]: ").strip().lower()
                if confirm not in ("y", "yes"):
                    print("Organization cancelled.")
                    return {"count": 0, "stats": stats, "batch_id": None, "plan": planned_moves}
            except (KeyboardInterrupt, EOFError):
                print("\nCancelled.")
                return {"count": 0, "stats": stats, "batch_id": None, "plan": planned_moves}
        is_dry_run = False
    elif not sys.stdin.isatty():
        # Non-interactive without explicit --apply or --yes -> strictly preview!
        is_dry_run = True
    else:
        # Interactive TTY without apply/auto_confirm: prompt user with preview table
        table_rows = [
            [
                m.source.name[:32],
                f"{m.category}/{m.destination.name}"[:32],
                f"{int(m.confidence * 100)}%" if m.confidence is not None else "100%",
                m.reason[:36],
            ]
            for m in planned_moves
        ]
        print(f"\nLaya Organize Preview: {target_path}")
        print(f"Engine: {engine_type.upper()} | Files: {len(planned_moves)}\n")
        print(format_table(["File", "Proposed Destination", "Conf", "Reason"], table_rows, ["left", "left", "right", "left"]))
        try:
            confirm = input(f"\nApply organization and move {len(planned_moves)} file(s)? [y/N]: ").strip().lower()
            if confirm in ("y", "yes"):
                is_dry_run = False
            else:
                print("Organization cancelled. Pass --apply to execute directly.")
                return {"count": 0, "stats": stats, "batch_id": None, "plan": planned_moves}
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return {"count": 0, "stats": stats, "batch_id": None, "plan": planned_moves}

    if is_dry_run:
        dry_result = {
            "target_dir": str(target_path),
            "dry_run": True,
            "applied": False,
            "count": len(planned_moves),
            "stats": stats,
            "proposed_moves": [m.to_dict() for m in planned_moves],
            "batch_id": None,
            "plan": planned_moves,
        }
        if json_output:
            print(json.dumps(dry_result, indent=2, default=str))
        else:
            print(f"\nLaya Organize: {target_path} [DRY RUN PREVIEW]")
            print(f"Engine: {engine_type.upper()} | Proposed Moves: {len(planned_moves)}\n")
            table_rows = [
                [
                    m.source.name[:32],
                    f"{m.category}/{m.destination.name}"[:32],
                    f"{int(m.confidence * 100)}%" if m.confidence is not None else "100%",
                    m.reason[:36],
                ]
                for m in planned_moves
            ]
            print(format_table(["File", "Proposed Destination", "Conf", "Reason"], table_rows, ["left", "left", "right", "left"]))
            print("\nDry Run Summary:")
            for cat, count in sorted(stats.items()):
                print(f"  * {cat:24} : {count:3d} file(s)")
            if not sys.stdin.isatty() and not (apply or auto_confirm):
                print("\nNotice: Non-interactive execution defaults to preview. Pass --apply or --yes to execute moves.")
            else:
                print("\nNote: Simulation only, no files moved. Pass --apply to execute.")
        return dry_result

    batch_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if not json_output:
        print(f"\nEngine: {engine_type.upper()} | Target: {target_path} | Files: {len(planned_moves)}")
        print("[MODE: LIVE SORT - Changes tracked for undo/rollback]\n")

    moved_records = execute_plan(
        planned_moves=planned_moves,
        batch_id=batch_id,
        target_dir=target_path,
        history_file=history_file,
    )

    if not json_output:
        for r in moved_records:
            print(f"  -> [{r['category']}] {Path(r['source']).name}")

        print("\nOrganization Complete:")
        for cat, count in sorted(stats.items()):
            print(f"  * {cat}: {count} file(s)")

        if moved_records:
            print(f"\nAudit Log: Saved batch ID '{batch_id}'. Run 'laya undo' anytime to reverse.")

    res = {
        "target_dir": str(target_path),
        "dry_run": False,
        "applied": True,
        "batch_id": batch_id,
        "count": len(moved_records),
        "stats": stats,
        "plan": planned_moves,
        "moves": moved_records,
    }

    if json_output:
        print(json.dumps(res, indent=2, default=str))
    return res


def undo_subcommand(
    batch_id: str | None = None,
    json_output: bool = False,
    history_file: Path | None = None,
) -> dict[str, Any]:
    """Reverses the last or specified batch with JSON reporting."""
    batches = load_history(history_file=history_file)
    if not batches:
        msg = "No organization history found to roll back."
        res = {"success": False, "error": msg}
        if json_output:
            print(json.dumps(res, indent=2))
        else:
            print(msg)
        return res

    target_batch = None
    if batch_id:
        for b in reversed(batches):
            if b.get("batch_id") == batch_id:
                target_batch = b
                break
    else:
        target_batch = batches[-1]

    if not target_batch:
        msg = f"Batch '{batch_id}' not found in history."
        res = {"success": False, "error": msg}
        if json_output:
            print(json.dumps(res, indent=2))
        else:
            print(f"Error: {msg}")
        return res

    success = rollback_last_batch(batch_id=target_batch.get("batch_id"), history_file=history_file)
    res = {
        "success": success,
        "batch_id": target_batch.get("batch_id"),
        "count": target_batch.get("count", 0),
        "target_dir": target_batch.get("target_dir"),
    }
    if json_output:
        print(json.dumps(res, indent=2))
    return res


def history_subcommand(
    limit: int = 10,
    json_output: bool = False,
    history_file: Path | None = None,
) -> list[dict[str, Any]]:
    """Lists recent sorting batches with timestamps, directories, file counts."""
    batches = load_history(history_file=history_file)
    recent = list(reversed(batches[-limit:]))

    if json_output:
        print(json.dumps({"total_batches": len(batches), "batches": recent}, indent=2))
        return recent

    if not batches:
        print("\nNo organization history recorded yet.")
        return []

    print("\nOrganization History (Recent Batches):")
    rows = []
    for b in recent:
        rows.append([
            b.get("batch_id", ""),
            b.get("timestamp", "")[:19].replace("T", " "),
            str(b.get("count", 0)),
            b.get("target_dir", ""),
        ])
    print(format_table(["Batch ID", "Timestamp", "Files", "Directory"], rows, ["left", "left", "right", "left"]))
    print("\nTo roll back a specific batch, run: laya undo --batch-id <ID>")
    return recent


def config_subcommand(
    show: bool = False,
    reset: bool = False,
    set_confidence: float | None = None,
    set_naming: str | None = None,
    add_rule: list[str] | None = None,
    json_output: bool = False,
) -> dict[str, Any]:
    """Interactive / flag-based configuration management."""
    config = load_config()

    if reset:
        config = {
            "folder_names": dict(DEFAULT_FOLDER_NAMES),
            "ignored_extensions": list(DEFAULT_ACTIVE_DOWNLOAD_EXTS),
            "custom_rules": {},
            "default_confidence": 0.50,
            "auto_confirm": False,
        }
        save_config(config)
        if not json_output:
            print("Configuration reset to factory defaults.")

    if set_confidence is not None:
        if 0.05 <= set_confidence <= 0.99:
            config["default_confidence"] = set_confidence
            save_config(config)
            if not json_output:
                print(f"Default confidence threshold set to {set_confidence:.2f}")
        else:
            print("Error: Confidence threshold must be between 0.05 and 0.99")

    if set_naming:
        if set_naming == "short":
            config["folder_names"] = dict(SHORT_FOLDER_NAMES)
            save_config(config)
            if not json_output:
                print("Folder naming style set to short (Docs, Code, etc.)")
        elif set_naming == "nested":
            config["folder_names"] = dict(NESTED_FOLDER_NAMES)
            save_config(config)
            if not json_output:
                print("Folder naming style set to nested hierarchy (Documents/Financial, Media/Images, etc.)")
        elif set_naming == "default":
            config["folder_names"] = dict(DEFAULT_FOLDER_NAMES)
            save_config(config)
            if not json_output:
                print("Folder naming style set to standard (Documents, Code_and_Scripts, etc.)")

    if add_rule and len(add_rule) == 2:
        ext, folder = add_rule
        if not ext.startswith("."):
            ext = "." + ext
        config.setdefault("custom_rules", {})[ext.lower()] = folder
        save_config(config)
        if not json_output:
            print(f"Added custom rule: {ext.lower()} -> {folder}")

    if json_output:
        print(json.dumps(config, indent=2))
        return config

    if show or reset or set_confidence is not None or set_naming or add_rule:
        print("\nCurrent Configuration (~/.config/laya/config.json):")
        print("=" * 64)
        print(f"Default Confidence Threshold : {config.get('default_confidence', 0.50):.2f}")
        print(f"Auto-confirm Moves           : {config.get('auto_confirm', False)}")
        print("\nActive Folder Mappings:")
        for k, v in config.get("folder_names", {}).items():
            print(f"  {k:24} -> {v}")
        custom = config.get("custom_rules", {})
        if custom:
            print("\nCustom Extension Rules:")
            for ext, fld in custom.items():
                print(f"  {ext:12} -> {fld}")
        print("=" * 64)
    elif sys.stdin.isatty():
        settings_menu(config)
    else:
        print(json.dumps(config, indent=2))

    return config


def get_top_directories() -> list[tuple[str, Path, int]]:
    """Discovers top user directories (Downloads, Desktop, etc.) with file counts."""
    home = Path.home()
    candidates = [
        ("Downloads", home / "Downloads"),
        ("Desktop", home / "Desktop"),
        ("Documents", home / "Documents"),
        ("Pictures", home / "Pictures"),
        ("Videos", home / "Videos"),
        ("Current Directory", Path.cwd()),
    ]
    results = []
    for label, p in candidates:
        if p.exists() and p.is_dir():
            try:
                count = sum(1 for item in p.iterdir() if (item.is_file() or item.is_symlink()) and not item.name.startswith("."))
            except OSError:
                count = 0
            results.append((label, p, count))
    return results


def interactive_menu():
    """Friendly terminal interface allowing user to choose directory, settings, and undo."""
    config = load_config()

    while True:
        print("\n" + "=" * 54)
        print("          LAYA AUTO FILE ORGANIZER")
        print("       Sub-35ms Local Decision Engine")
        print("=" * 54)
        print(" [1] Sort a Directory (Downloads, Desktop, etc.)")
        print(" [2] Preview Sorting (Dry Run Simulation)")
        print(" [3] Scan Directory (Classification Breakdown)")
        print(" [4] Inspect Directory (Sizes, Extensions, Stats)")
        print(" [5] Find Duplicate Files (SHA-256 Check)")
        print(" [6] Undo / Rollback Last Organization")
        print(" [7] Folder Naming & File Rules Settings")
        print(" [8] View Organization History")
        print(" [0] Exit")
        print("=" * 54)

        try:
            choice = input("Select an option [0-8]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(0)

        if choice in ("1", "2"):
            dry_run = (choice == "2")
            print("\nChoose Target Directory:")
            top_dirs = get_top_directories()
            for idx, (label, p, count) in enumerate(top_dirs, 1):
                print(f" [{idx}] {label:18} ({p}) — {count} file(s)")
            print(f" [{len(top_dirs) + 1}] Custom Path...")
            print(" [0] Back to Main Menu")

            try:
                dir_choice = input(f"Select directory [0-{len(top_dirs) + 1}]: ").strip()
            except (KeyboardInterrupt, EOFError):
                continue

            if dir_choice == "0" or not dir_choice:
                continue

            target_path = None
            if dir_choice.isdigit():
                val = int(dir_choice)
                if 1 <= val <= len(top_dirs):
                    target_path = str(top_dirs[val - 1][1])
                elif val == len(top_dirs) + 1:
                    raw_custom = input("Enter custom folder path: ").strip()
                    if raw_custom:
                        target_path = raw_custom

            if not target_path:
                print("Invalid selection.")
                continue

            organize_directory(target_path, dry_run=dry_run, config_override=config)

        elif choice == "3":
            try:
                raw_path = input("Enter folder path to scan (default: current dir): ").strip()
                target_path = raw_path if raw_path else "."
                scan_directory(target_path, config_override=config)
            except (KeyboardInterrupt, EOFError):
                continue

        elif choice == "4":
            try:
                raw_path = input("Enter folder path to inspect (default: current dir): ").strip()
                target_path = raw_path if raw_path else "."
                inspect_directory(target_path)
            except (KeyboardInterrupt, EOFError):
                continue

        elif choice == "5":
            try:
                raw_path = input("Enter folder path to check for duplicates (default: current dir): ").strip()
                target_path = raw_path if raw_path else "."
                find_duplicates(target_path)
            except (KeyboardInterrupt, EOFError):
                continue

        elif choice == "6":
            batches = load_history()
            if not batches:
                print("\nNo previous sorting history found.")
                continue
            last = batches[-1]
            print(f"\nLast batch: {last['batch_id']} ({last['timestamp']})")
            print(f"Directory : {last['target_dir']}")
            print(f"Files     : {last['count']} files moved")
            try:
                confirm = input("\nRoll back and restore all files? [y/N]: ").strip().lower()
                if confirm in ("y", "yes"):
                    rollback_last_batch()
                else:
                    print("Rollback cancelled.")
            except (KeyboardInterrupt, EOFError):
                continue

        elif choice == "7":
            settings_menu(config)

        elif choice == "8":
            history_subcommand()

        elif choice == "0":
            print("\nGoodbye!")
            break
        else:
            print("Invalid option. Please choose 0-8.")


def settings_menu(config: dict[str, Any]):
    """Settings submenu to customize folder names, custom extension rules, and ignore lists."""
    while True:
        print("\n" + "=" * 54)
        print("              LAYA SETTINGS")
        print("=" * 54)
        print(" [1] View Current Folder Naming")
        print(" [2] Switch to Short/Clean Folder Names (Docs, Code, Media...)")
        print(" [3] Reset to Standard Folder Names (Documents, Code_and_Scripts...)")
        print(" [4] Add Custom Extension Rule (e.g. .torrent -> Torrents)")
        print(" [5] Adjust Confidence Threshold (Currently: {:.2f})".format(config.get("default_confidence", 0.50)))
        print(" [0] Save & Return to Main Menu")
        print("=" * 54)

        try:
            choice = input("Select setting option [0-5]: ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if choice == "0":
            save_config(config)
            print("Settings saved.")
            break
        elif choice == "1":
            print("\nCurrent Folder Mappings:")
            for k, v in config.get("folder_names", {}).items():
                print(f"  {k:24} -> {v}")
            if config.get("custom_rules"):
                print("\nCustom Extension Rules:")
                for ext, folder in config["custom_rules"].items():
                    print(f"  {ext} -> {folder}")
        elif choice == "2":
            config["folder_names"] = dict(SHORT_FOLDER_NAMES)
            save_config(config)
            print("Switched to clean/short folder naming style.")
        elif choice == "3":
            config["folder_names"] = dict(DEFAULT_FOLDER_NAMES)
            save_config(config)
            print("Reset to standard folder naming style.")
        elif choice == "4":
            try:
                ext = input("Enter file extension with dot (e.g. .torrent): ").strip().lower()
                if not ext.startswith("."):
                    ext = "." + ext
                target_f = input(f"Enter target folder name for '{ext}': ").strip()
                if target_f:
                    config.setdefault("custom_rules", {})[ext] = target_f
                    save_config(config)
                    print(f"Added rule: {ext} -> {target_f}")
            except (KeyboardInterrupt, EOFError):
                continue
        elif choice == "5":
            try:
                val = float(input("Enter min confidence (0.10 to 0.95): ").strip())
                if 0.05 <= val <= 0.99:
                    config["default_confidence"] = val
                    save_config(config)
                    print(f"Confidence threshold set to {val:.2f}")
                else:
                    print("Value out of valid range.")
            except ValueError:
                print("Invalid number.")
            except (KeyboardInterrupt, EOFError):
                continue


def recover_subcommand(
    batch_id: str | None = None,
    inspect_only: bool = False,
    do_rollback: bool = False,
    do_resume: bool = False,
    do_dismiss: bool = False,
    json_output: bool = False,
    history_file: Path | None = None,
) -> None:
    """Subcommand handler for 'laya recover'."""
    inspected = inspect_pending_transactions(history_file=history_file)
    if not inspected:
        if json_output:
            print(json.dumps({"pending_batches": [], "message": "No pending transactions found"}))
        else:
            print("No pending or interrupted transactions found.")
        return

    target_batches = inspected
    if batch_id:
        target_batches = [b for b in inspected if b.get("batch_id") == batch_id]
        if not target_batches:
            if json_output:
                print(json.dumps({"error": f"Batch '{batch_id}' not found among pending transactions"}))
            else:
                print(f"Error: Batch '{batch_id}' not found among pending transactions.")
            return

    target_batch = target_batches[0]
    target_id = target_batch["batch_id"]

    if json_output and (inspect_only or (not do_rollback and not do_resume and not do_dismiss)):
        print(json.dumps({"pending_batches": target_batches}, indent=2))
        return

    if inspect_only or (not do_rollback and not do_resume and not do_dismiss):
        print("\n=== Pending Transaction Inspection ===\n")
        for b in target_batches:
            s = b.get("disk_summary", {})
            print(f"Batch ID: {b.get('batch_id')}")
            print(f"Target:   {b.get('target_dir')}")
            print(f"Status:   {b.get('status')}")
            print(f"Disk Summary: {s.get('moved', 0)} moved, {s.get('unmoved', 0)} unmoved, {s.get('conflict', 0)} conflict, {s.get('missing', 0)} missing\n")
            print("Moves breakdown:")
            for m in b.get("moves", []):
                print(f"  [{m.get('disk_status', 'unknown')}] {Path(m['source']).name} -> {m['dest']}")
                if m.get("error"):
                    print(f"      Error: {m['error']}")
                if m.get("last_rollback_error"):
                    print(f"      Rollback Error: {m['last_rollback_error']}")
        return

    if do_rollback:
        rollback_last_batch(batch_id=target_id, history_file=history_file)
    elif do_resume:
        resume_interrupted_batch(batch_id=target_id, history_file=history_file)
    elif do_dismiss:
        dismiss_interrupted_batch(batch_id=target_id, history_file=history_file)


def self_check() -> bool:
    """Minimal runnable check for Laya organizer and fallback router."""
    router, engine = get_router()
    q = get_laya_questions()

    samples = [
        ("Filename: invoice_2026_march.pdf\nExtension: .pdf\nContent Snippet: Invoice #402. Total amount due $450.00", "Financial"),
        ("Filename: main.rs\nExtension: .rs\nContent Snippet: fn main() { println!(\"Hello\"); }", "Code_and_Scripts"),
        ("Filename: config.yaml\nExtension: .yaml\nContent Snippet: server:\n  port: 8080", "Data_and_Configs"),
    ]
    for sample, expected in samples:
        res = router.predict(sample, q)
        got = res["answers"]["category"]["choice"]
        assert got == expected, f"Expected {expected}, got {got}"
    print(f"Self-check passed: All test samples classified correctly using {engine.upper()} engine!")
    return True


def build_parser() -> argparse.ArgumentParser:
    """Builds top-level parser with subcommands and root-level fallback flags."""
    parser = argparse.ArgumentParser(
        prog="laya",
        description="Laya Sub-35ms Local File Organizer with Rollback and Intelligent Classification",
    )
    # Root level options for backwards compatibility
    parser.add_argument("--check", action="store_true", help="Run self-check validation")
    parser.add_argument("--undo", "--rollback", dest="rollback", action="store_true", help="Undo last file organization batch")
    parser.add_argument("--batch-id", help="Specific batch ID to undo (used with --undo)")
    parser.add_argument("--history", action="store_true", help="Show recent organization history")
    parser.add_argument("--config", action="store_true", help="Open configuration settings")
    parser.add_argument("-v", "--version", action="version", version="%(prog)s 1.0.0")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan directory and display classification breakdown without moving files")
    p_scan.add_argument("target_dir", nargs="?", default=".", help="Directory to scan (default: current directory)")
    p_scan.add_argument("--json", action="store_true", help="Output results as JSON")
    p_scan.add_argument("--confidence", type=float, default=None, help="Min confidence threshold (default: 0.50)")

    # organize
    p_org = subparsers.add_parser("organize", help="Organize files in directory with rollback safety")
    p_org.add_argument("target_dir", nargs="?", default=".", help="Directory to organize (default: current directory)")
    p_org.add_argument("-o", "--output-dir", help="Destination base folder (default: inside target_dir)")
    p_org.add_argument("--dry-run", action="store_true", help="Preview proposed moves in tabular format without moving files")
    p_org.add_argument("--apply", action="store_true", help="Prompt for confirmation and apply organization")
    p_org.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt and apply changes immediately")
    p_org.add_argument("--confidence", type=float, default=None, help="Min confidence threshold (default: 0.50)")
    p_org.add_argument("--json", action="store_true", help="Output results as JSON")

    # undo
    p_undo = subparsers.add_parser("undo", help="Reverse a previous organization batch")
    p_undo.add_argument("--batch-id", help="Specific batch ID to revert (default: most recent)")
    p_undo.add_argument("--json", action="store_true", help="Output result as JSON")

    # history
    p_hist = subparsers.add_parser("history", help="List recent organization batches")
    p_hist.add_argument("--limit", type=int, default=10, help="Number of batches to display (default: 10)")
    p_hist.add_argument("--json", action="store_true", help="Output history as JSON")

    # inspect
    p_insp = subparsers.add_parser("inspect", help="Detailed breakdown of directory (file counts, categories, sizes, top extensions)")
    p_insp.add_argument("target_dir", nargs="?", default=".", help="Directory to inspect (default: current directory)")
    p_insp.add_argument("--json", action="store_true", help="Output inspection report as JSON")

    # duplicates
    p_dup = subparsers.add_parser("duplicates", help="Detect identical files using SHA-256 hashes on equal-sized files")
    p_dup.add_argument("target_dir", nargs="?", default=".", help="Directory to inspect for duplicates (default: current directory)")
    p_dup.add_argument("--min-size", type=int, default=1, help="Minimum file size in bytes to check (default: 1)")
    p_dup.add_argument("--json", action="store_true", help="Output duplicates report as JSON")

    # config
    p_cfg = subparsers.add_parser("config", help="Manage Laya configuration")
    p_cfg.add_argument("--show", action="store_true", help="Print current configuration")
    p_cfg.add_argument("--json", action="store_true", help="Output config as JSON")
    p_cfg.add_argument("--reset", action="store_true", help="Reset configuration to defaults")
    p_cfg.add_argument("--set-confidence", type=float, help="Set default confidence threshold")
    p_cfg.add_argument("--set-naming", choices=["default", "short"], help="Set folder naming style")
    p_cfg.add_argument("--add-rule", nargs=2, metavar=("EXT", "FOLDER"), help="Add custom extension rule (e.g. --add-rule .torrent Torrents)")

    # recover
    p_rec = subparsers.add_parser("recover", help="Inspect and recover interrupted transactions")
    p_rec.add_argument("--batch-id", help="Target specific batch ID (default: most recent interrupted)")
    p_rec.add_argument("--inspect", action="store_true", help="Inspect disk state of interrupted batches without mutating")
    p_rec.add_argument("--rollback", action="store_true", help="Roll back moved files to original locations")
    p_rec.add_argument("--resume", action="store_true", help="Resume and finish remaining planned moves")
    p_rec.add_argument("--dismiss", action="store_true", help="Dismiss alert and mark batch as dismissed")
    p_rec.add_argument("--json", action="store_true", help="Output inspection report as JSON")

    return parser


def main():
    parser = build_parser()

    argv = list(sys.argv[1:])
    known_cmds = {"scan", "organize", "undo", "history", "inspect", "duplicates", "config", "recover", "-h", "--help", "-v", "--version"}
    root_flags = {"--check", "--undo", "--rollback", "--batch-id", "--history", "--config"}

    if argv:
        first = argv[0]
        if first not in known_cmds and first not in root_flags:
            argv.insert(0, "organize")

    args = parser.parse_args(argv)

    if args.command not in ("recover", "undo") and not args.rollback and not args.check:
        run_startup_recovery()

    if args.check:
        self_check()
    elif args.rollback:
        rollback_last_batch(args.batch_id)
    elif args.history and args.command != "history":
        history_subcommand()
    elif args.config and args.command != "config":
        config_subcommand(show=True)
    elif args.command == "scan":
        scan_directory(args.target_dir, min_confidence=args.confidence, json_output=args.json)
    elif args.command == "organize":
        organize_directory(
            target_dir=args.target_dir,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
            apply=args.apply,
            auto_confirm=args.yes,
            min_confidence=args.confidence,
            json_output=args.json,
        )
    elif args.command == "undo":
        undo_subcommand(batch_id=args.batch_id, json_output=args.json)
    elif args.command == "history":
        history_subcommand(limit=args.limit, json_output=args.json)
    elif args.command == "inspect":
        inspect_directory(args.target_dir, json_output=args.json)
    elif args.command == "duplicates":
        find_duplicates(args.target_dir, min_size=args.min_size, json_output=args.json)
    elif args.command == "config":
        config_subcommand(
            show=args.show,
            reset=args.reset,
            set_confidence=args.set_confidence,
            set_naming=args.set_naming,
            add_rule=args.add_rule,
            json_output=args.json,
        )
    elif args.command == "recover":
        recover_subcommand(
            batch_id=args.batch_id,
            inspect_only=args.inspect,
            do_rollback=args.rollback,
            do_resume=args.resume,
            do_dismiss=args.dismiss,
            json_output=args.json,
        )
    else:
        if sys.stdin.isatty():
            interactive_menu()
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
